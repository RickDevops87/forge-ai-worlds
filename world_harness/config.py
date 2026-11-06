from __future__ import annotations

import re
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorldConfig:
    world_id: str
    title: str
    image: str
    container_port: int
    host_port: int
    memory: str
    cpus: float
    pids_limit: int
    container_uid: int
    settings: tuple[tuple[str, str], ...]
    config_path: Path
    state_root: Path

    @classmethod
    def load(cls, path: Path) -> "WorldConfig":
        path = Path(path)
        if path.is_symlink():
            raise ValueError("world manifest cannot be a symlink")
        path = path.resolve(strict=True)
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported world manifest schema")
        world, interface, resources = raw["world"], raw["interface"], raw["resources"]
        settings = world.get("environment", {})
        if not isinstance(settings, dict):
            raise ValueError("world.environment must be a TOML table")
        state_relative = Path(raw["storage"]["state_root"])
        if state_relative.is_absolute():
            raise ValueError("world state path must be relative to its manifest")
        project_root = path.parents[2]
        state_root = Path(os.path.abspath(path.parent / state_relative))
        if not state_root.is_relative_to(project_root):
            raise ValueError("world state must remain inside the Simple Systems project")
        config = cls(
            world_id=world["id"], title=world["title"], image=world["image"],
            container_port=int(interface["container_port"]), host_port=int(interface["host_port"]),
            memory=resources["memory"], cpus=float(resources["cpus"]),
            pids_limit=int(resources["pids_limit"]), container_uid=int(resources["container_uid"]),
            settings=tuple(sorted((str(k), str(v)) for k, v in settings.items())),
            config_path=path,
            state_root=state_root,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", self.world_id):
            raise ValueError("world id must be lowercase kebab-case")
        if not self.title.strip() or len(self.title) > 100:
            raise ValueError("world title must be 1-100 characters")
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?", self.image)
                or "@" in self.image or ".." in self.image.split("/")):
            raise ValueError("world image must be a safe local OCI image name or tag")
        if not 1 <= self.container_port <= 65535 or not 1024 <= self.host_port <= 65535:
            raise ValueError("world ports are outside allowed ranges")
        if not re.fullmatch(r"[1-9][0-9]*(?:[kKmMgG])?", self.memory):
            raise ValueError("memory must be a positive Podman quantity, e.g. 2g")
        if not 0.1 <= self.cpus <= 64:
            raise ValueError("CPU limit must be between 0.1 and 64")
        if not 16 <= self.pids_limit <= 65536:
            raise ValueError("PID limit must be between 16 and 65536")
        if not 1000 <= self.container_uid <= 60000:
            raise ValueError("container UID must be an unprivileged UID")
        for name, value in self.settings:
            if (not re.fullmatch(r"FORGE_WORLD_[A-Z0-9_]{1,48}", name)
                    or any(word in name for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))):
                raise ValueError("world settings must use non-secret FORGE_WORLD_* names")
            if len(value) > 1024 or "\x00" in value:
                raise ValueError("world setting value is too long or contains NUL")
        if self.config_path.is_symlink() or not self.config_path.is_file():
            raise ValueError("world manifest must be a regular file")
        pack = self.config_path.parent
        if self.state_root == pack or pack in self.state_root.parents or self.state_root in pack.parents:
            raise ValueError("world state must be separate from the immutable world pack")
        for parent in (self.state_root, *self.state_root.parents):
            if parent == self.config_path.parents[2]:
                break
            if parent.exists() and parent.is_symlink():
                raise ValueError("world state path cannot traverse symlinks")
