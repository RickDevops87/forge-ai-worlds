# Category 7 — Monitoring and response

Runnable synthetic support-action, event-detection, and containment scenario. Its synchronous detector is a fixture, not a SIEM or production monitoring service.

From the `AI-Security-Simple-Systems` root, build the image and run `world_harness` using this folder's `world.toml` (defended) or `world-vulnerable.toml` (paired vulnerable control). It serves on loopback port `18087` or `18187` respectively.

Follow [`../codex-qualification/CATEGORY-05-07-WORLDS.md`](../codex-qualification/CATEGORY-05-07-WORLDS.md) for the exact build/start/test/inspect/stop commands, operator-only identity containment, and the `WorldClient` tool-call example.
