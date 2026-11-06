from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .config import WorldConfig


class WorldRunner:
    """Run one declared environment image as a rootless, loopback-only Podman world."""

    def __init__(self, config: WorldConfig, podman: str | None = None):
        self.config = config
        self.podman = podman or shutil.which("podman")
        if not self.podman:
            raise RuntimeError("Podman is required")

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self.podman, *args], text=True, capture_output=True,
                              timeout=30, check=check)

    def _require_rootless(self) -> None:
        result = self._run(["info", "--format", "{{.Host.Security.Rootless}}"])
        if result.stdout.strip().lower() != "true":
            raise PermissionError("Forge worlds require rootless Podman")

    def _container_name(self, run_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{12}", run_id):
            raise ValueError("run ID must be exactly 12 lowercase hexadecimal characters")
        return f"forge-world-{self.config.world_id}-{run_id}"

    def _network_name(self, run_id: str) -> str:
        self._container_name(run_id)
        return f"forge-world-net-{self.config.world_id}-{run_id}"

    def start(self, run_id: str | None = None) -> dict[str, Any]:
        self._require_rootless()
        run_id = run_id or uuid.uuid4().hex[:12]
        name = self._container_name(run_id)
        network = self._network_name(run_id)
        state = self.config.state_root / run_id
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
        state.chmod(0o700)
        container_state = state / "world-state"
        container_state.mkdir(mode=0o700)
        operator_token = secrets.token_urlsafe(32)
        token_path = state / "operator-token"
        token_path.write_text(operator_token + "\n", encoding="utf-8")
        token_path.chmod(0o600)
        network_created = False
        try:
            image = self._run(["image", "exists", self.config.image], check=False)
            if image.returncode:
                raise FileNotFoundError(f"world image is not present locally: {self.config.image}")
            image_identity = self._run(["image", "inspect", "--format", "{{.Id}}", self.config.image])
            image_id = image_identity.stdout.strip()
            # Podman reports local image IDs as 64 hex chars (without the
            # algorithm prefix); run accepts that immutable full ID directly.
            if not re.fullmatch(r"[a-f0-9]{64}", image_id):
                raise RuntimeError("Podman did not return an immutable SHA-256 image ID")
            self._run(["network", "create", "--internal", "--disable-dns",
                       "--label", f"io.forge.world={self.config.world_id}",
                       "--label", f"io.forge.run={run_id}", network])
            network_created = True
            args = ["run", "--detach", "--name", name,
                    "--label", f"io.forge.world={self.config.world_id}",
                    "--label", f"io.forge.run={run_id}",
                    "--userns", f"keep-id:uid={self.config.container_uid},gid={self.config.container_uid}",
                    "--user", str(self.config.container_uid), "--read-only",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                    "--tmpfs", "/run:rw,noexec,nosuid,size=16m",
                    "--cap-drop", "all", "--security-opt", "no-new-privileges",
                    "--pids-limit", str(self.config.pids_limit),
                    "--memory", self.config.memory, "--cpus", str(self.config.cpus),
                    "--network", network,
                    "--publish", f"127.0.0.1:{self.config.host_port}:{self.config.container_port}",
                    "--env", f"FORGE_WORLD_OPERATOR_TOKEN={operator_token}",
                    "--volume", f"{container_state}:/world-state:rw"]
            for key, value in self.config.settings:
                args.extend(["--env", f"{key}={value}"])
            # Podman options must precede the image; after it they become the
            # container command/arguments rather than run configuration.
            args.append(image_id)
            result = self._run(args)
        except Exception:
            if network_created:
                self._run(["network", "rm", network], check=False)
            shutil.rmtree(state, ignore_errors=True)
            raise
        return {"world_id": self.config.world_id, "run_id": run_id, "container": name,
                "status": "running", "url": f"http://127.0.0.1:{self.config.host_port}",
                "container_id": result.stdout.strip(), "image_id": f"sha256:{image_id}",
                "network_policy": "internal_no_external_egress",
                "operator_token_path": str(token_path)}

    def status(self, run_id: str) -> dict[str, Any]:
        name = self._container_name(run_id)
        result = self._run(["inspect", "--format", "{{json .Config.Labels}}", name], check=False)
        if result.returncode:
            return {"world_id": self.config.world_id, "run_id": run_id, "status": "not_found"}
        try:
            labels = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Podman returned invalid container labels") from exc
        if labels.get("io.forge.world") != self.config.world_id or labels.get("io.forge.run") != run_id:
            raise PermissionError("refusing to inspect a container not owned by this world run")
        result = self._run(["inspect", "--format", "{{json .State}}", name])
        state = json.loads(result.stdout)
        return {"world_id": self.config.world_id, "run_id": run_id,
                "status": state.get("Status", "unknown"), "exit_code": state.get("ExitCode")}

    def stop(self, run_id: str) -> dict[str, Any]:
        name = self._container_name(run_id)
        self._require_rootless()
        ownership = self._run(["inspect", "--format", "{{json .Config.Labels}}", name], check=False)
        if ownership.returncode:
            return {"world_id": self.config.world_id, "run_id": run_id, "status": "not_found"}
        try:
            labels = json.loads(ownership.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Podman returned invalid container labels") from exc
        if labels.get("io.forge.world") != self.config.world_id or labels.get("io.forge.run") != run_id:
            raise PermissionError("refusing to stop a container not owned by this world run")
        result = self._run(["stop", "--time", "5", name], check=False)
        if result.returncode and "no such container" not in result.stderr.lower():
            raise RuntimeError(result.stderr.strip() or "Podman could not stop world")
        remove = self._run(["rm", "--force", name], check=False)
        if remove.returncode and "no such container" not in remove.stderr.lower():
            raise RuntimeError(remove.stderr.strip() or "Podman could not remove world")
        network_name = self._network_name(run_id)
        network_info = self._run(["network", "inspect", "--format", "{{json .Labels}}", network_name], check=False)
        if network_info.returncode == 0:
            try:
                network_labels = json.loads(network_info.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Podman returned invalid network labels") from exc
            if (network_labels.get("io.forge.world") != self.config.world_id
                    or network_labels.get("io.forge.run") != run_id):
                raise PermissionError("refusing to remove a network not owned by this world run")
            network = self._run(["network", "rm", network_name], check=False)
            if network.returncode:
                raise RuntimeError(network.stderr.strip() or "Podman could not remove private world network")
        return {"world_id": self.config.world_id, "run_id": run_id, "status": "stopped"}
