from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import WorldConfig


class WorldClient:
    """Trusted host-side client. Keep operator credentials out of model messages."""

    def __init__(self, config: WorldConfig, run_id: str):
        if not run_id or any(ch not in "0123456789abcdef" for ch in run_id) or len(run_id) != 12:
            raise ValueError("run ID must be exactly 12 lowercase hexadecimal characters")
        self.config = config
        self.run_id = run_id
        self.base_url = f"http://127.0.0.1:{config.host_port}"
        token_path = config.state_root / run_id / "operator-token"
        if token_path.is_symlink() or not token_path.is_file():
            raise FileNotFoundError("operator token receipt is missing or unsafe")
        info = token_path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise PermissionError("operator token must be owned by the current user and mode 0600")
        self._operator_token = token_path.read_text(encoding="utf-8").strip()
        if len(self._operator_token) < 32:
            raise ValueError("operator token receipt is invalid")

    def _request(self, path: str, *, payload: dict | None = None, token: str | None = None) -> dict:
        if not path.startswith("/") or ".." in path.split("/"):
            raise ValueError("world API path must be absolute and traversal-free")
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base_url + path, data=body, headers=headers)
        try:
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"world API returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("world API is unavailable") from exc
        if not isinstance(result, dict):
            raise RuntimeError("world API response was not a JSON object")
        return result

    def create_session(self, case_id: str) -> dict:
        session = self._request("/api/operator/sessions", payload={"case_id": case_id},
                                token=self._operator_token)
        if not isinstance(session.get("agent_token"), str):
            raise RuntimeError("world did not return an agent session")
        return session

    def tool_call(self, session_id: str, agent_token: str, tool_name: str, arguments: dict) -> dict:
        return self._request("/api/agent/tools", payload={"session_id": session_id,
            "tool_name": tool_name, "arguments": arguments}, token=agent_token)

    def inspect(self, session_id: str | None = None) -> dict:
        path = "/api/operator/state"
        if session_id:
            from urllib.parse import quote
            path += "?session_id=" + quote(session_id, safe="")
        return self._request(path, token=self._operator_token)

    def operator_action(self, session_id: str, action: str, **arguments: object) -> dict:
        """Run a world-specific, allowlisted maintenance or response action."""
        if not session_id or len(session_id) > 64:
            raise ValueError("session ID is invalid")
        if not action or len(action) > 64:
            raise ValueError("operator action is invalid")
        return self._request("/api/operator/action",
            payload={"session_id": session_id, "action": action, **arguments},
            token=self._operator_token)
