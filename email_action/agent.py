"""Host-side bounded Ollama agent loop for the synthetic email-action world."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from world_harness.client import WorldClient
from world_harness.config import WorldConfig


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class OllamaAgent:
    def __init__(self, client: WorldClient, model: str, endpoint: str, max_requests: int = 5):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model):
            raise ValueError("model must be an exact safe Ollama model identifier")
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port is None or parsed.query or parsed.fragment or parsed.username
                or parsed.password or not parsed.path.endswith("/api/chat")):
            raise ValueError("Ollama endpoint must be an explicit local /api/chat URL")
        if not 1 <= max_requests <= 8:
            raise ValueError("model request budget must be between 1 and 8")
        self.client, self.model, self.endpoint = client, model, endpoint
        self.max_requests = max_requests
        self.evidence = client.config.state_root / client.run_id / "agent-evidence.jsonl"

    def _record(self, kind: str, **fields) -> None:
        entry = {"timestamp": utc(), "event": kind, "model_requested": self.model, **fields}
        with self.evidence.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        self.evidence.chmod(0o600)

    def _call_model(self, payload: dict) -> dict:
        req = Request(self.endpoint, data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            self._record("model_http_error", status=exc.code)
            raise RuntimeError(f"Ollama returned HTTP {exc.code}; no retry was made") from exc
        except (URLError, TimeoutError) as exc:
            self._record("model_transport_error", error_type=type(exc).__name__)
            raise RuntimeError("Ollama is unavailable; no retry was made") from exc
        if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
            self._record("model_malformed_response", response_type=type(result).__name__)
            raise RuntimeError("Ollama returned an unusable response; no retry was made")
        message = result["message"]
        # Deliberately omit any provider-specific hidden `thinking` field.
        self._record("model_response", response_model=result.get("model"),
                     done=result.get("done"), done_reason=result.get("done_reason"),
                     prompt_eval_count=result.get("prompt_eval_count"),
                     eval_count=result.get("eval_count"),
                     content=message.get("content", ""),
                     tool_calls=message.get("tool_calls", []))
        return result

    def run(self, case_id: str) -> dict:
        session = self.client.create_session(case_id)
        session_id, agent_token = session["session_id"], session["agent_token"]
        messages = [{"role": "system", "content": session["system_prompt"]}, *session["messages"]]
        self._record("assessment_session_started", case_id=case_id, session_id=session_id,
                     model_endpoint=self.endpoint, max_model_requests=self.max_requests)
        for request_number in range(1, self.max_requests + 1):
            payload = {"model": self.model, "messages": messages, "tools": session["tools"],
                       "stream": False, "options": {"temperature": 0}}
            self._record("model_request", case_id=case_id, session_id=session_id,
                         request_number=request_number, request=payload)
            response = self._call_model(payload)
            message = response["message"]
            assistant_message = {k: message[k] for k in ("role", "content", "tool_calls") if k in message}
            messages.append(assistant_message)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise RuntimeError("Ollama tool_calls field was malformed; stop as inconclusive")
            if not calls:
                self._record("assessment_turn_complete", case_id=case_id, session_id=session_id,
                             model_requests=request_number)
                return {"status": "completed", "case_id": case_id, "session_id": session_id,
                        "model": response.get("model", self.model), "model_requests": request_number,
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
                self._record("tool_result_received", case_id=case_id, session_id=session_id,
                             tool=name, arguments=arguments, result=result)
                messages.append({"role": "tool", "tool_name": name or "unknown",
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
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "fable-forge:latest"))
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--max-model-requests", type=int, default=5)
    parser.add_argument("--allow-cloud", action="store_true",
                        help="acknowledge that a cloud-tagged model sends synthetic prompts off-host")
    args = parser.parse_args()
    if ("cloud" in args.model.casefold()) and not args.allow_cloud:
        parser.error("cloud model selected: pass --allow-cloud only after approving provider data egress")
    config = WorldConfig.load(args.config)
    client = WorldClient(config, args.run_id)
    result = OllamaAgent(client, args.model, args.ollama_url, args.max_model_requests).run(args.case)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
