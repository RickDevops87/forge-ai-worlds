"""Bounded xKiro tool-use client for the synthetic email-action world."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from world_harness.client import WorldClient
from world_harness.config import WorldConfig


API_URL = "https://api.xkiro.com/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.7-flash:free"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class XKiroAgent:
    """Use an exact xKiro model while keeping credentials host-side."""

    def __init__(self, client: WorldClient, model: str, api_key: str,
                 max_requests: int = 4, endpoint: str = API_URL):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model):
            raise ValueError("model must be an exact safe xKiro model identifier")
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("OpenRouter API key is missing or malformed")
        if endpoint != API_URL:
            raise ValueError("xKiro endpoint must be the fixed HTTPS API URL")
        if not 1 <= max_requests <= 8:
            raise ValueError("model request budget must be between 1 and 8")
        self.client, self.model, self._api_key = client, model, api_key
        self.max_requests = max_requests
        self.evidence = client.config.state_root / client.run_id / "agent-evidence.jsonl"

    def _record(self, kind: str, **fields) -> None:
        entry = {"timestamp": utc(), "event": kind, "model_requested": self.model, **fields}
        with self.evidence.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        self.evidence.chmod(0o600)

    def _call_model(self, payload: dict) -> dict:
        request = Request(API_URL, data=json.dumps(payload).encode(), headers={
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            self._record("model_http_error", status=exc.code)
            raise RuntimeError(f"xKiro returned HTTP {exc.code}; no retry was made") from exc
        except (URLError, TimeoutError) as exc:
            self._record("model_transport_error", error_type=type(exc).__name__)
            raise RuntimeError("xKiro request failed; no retry was made") from exc
        try:
            choice = result["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError
        except (KeyError, IndexError, TypeError):
            self._record("model_malformed_response", response_type=type(result).__name__)
            raise RuntimeError("xKiro returned an unusable response; no retry was made")
        # Do not capture provider-specific hidden reasoning fields.
        self._record("model_response", response_model=result.get("model"),
                     provider=result.get("provider"), response_id=result.get("id"),
                     finish_reason=choice.get("finish_reason"), usage=result.get("usage"),
                     content=message.get("content", ""), tool_calls=message.get("tool_calls", []))
        return {"message": message, "model": result.get("model", self.model),
                "provider": result.get("provider"), "usage": result.get("usage"),
                "finish_reason": choice.get("finish_reason")}

    def run(self, case_id: str) -> dict:
        session = self.client.create_session(case_id)
        session_id, agent_token = session["session_id"], session["agent_token"]
        messages = [{"role": "system", "content": session["system_prompt"]}, *session["messages"]]
        self._record("assessment_session_started", case_id=case_id, session_id=session_id,
                     model_endpoint=API_URL, max_model_requests=self.max_requests)
        for request_number in range(1, self.max_requests + 1):
            payload = {"model": self.model, "messages": messages, "tools": session["tools"],
                       "parallel_tool_calls": False, "temperature": 0,
                       "max_tokens": 512, "stream": False}
            self._record("model_request", case_id=case_id, session_id=session_id,
                         request_number=request_number, request=payload)
            response = self._call_model(payload)
            message = response["message"]
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise RuntimeError("tool_calls field was malformed; stop as inconclusive")
            assistant = {"role": "assistant", "content": message.get("content") or ""}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)
            if not calls:
                self._record("assessment_turn_complete", case_id=case_id, session_id=session_id,
                             model_requests=request_number)
                return {"status": "completed", "case_id": case_id, "session_id": session_id,
                        "model": response["model"], "provider": response["provider"],
                        "model_requests": request_number, "usage": response["usage"],
                        "assistant_output": message.get("content", ""),
                        "evidence": str(self.evidence)}
            for call in calls:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments", {}) if isinstance(function, dict) else None
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = None
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    result = {"ok": False, "error": "invalid_model_tool_call"}
                else:
                    result = self.client.tool_call(session_id, agent_token, name, arguments)
                call_id = call.get("id", "") if isinstance(call, dict) else ""
                self._record("tool_result_received", case_id=case_id, session_id=session_id,
                             tool=name, arguments=arguments, result=result)
                messages.append({"role": "tool", "tool_call_id": call_id, "name": name or "unknown",
                                 "content": json.dumps(result, ensure_ascii=False)})
        self._record("model_request_budget_exhausted", case_id=case_id, session_id=session_id,
                     model_requests=self.max_requests)
        return {"status": "inconclusive", "reason": "model request budget exhausted",
                "case_id": case_id, "session_id": session_id,
                "model_requests": self.max_requests, "evidence": str(self.evidence)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("worlds/email_action/world.toml"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case", required=True,
                        choices=("benign", "injection", "draft_control", "approved_send"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-model-requests", type=int, default=4)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    file_values = dotenv_values(project_root / ".env")
    api_key = os.environ.get("XKIRO_API_KEY") or file_values.get("XKIRO_API_KEY")
    if not api_key:
        parser.error("XKIRO_API_KEY is not set in the environment or lab .env")
    config = WorldConfig.load(args.config)
    client = WorldClient(config, args.run_id)
    result = XKiroAgent(client, args.model, api_key, args.max_model_requests).run(args.case)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
