# Category 5 — Fixed-job sandbox boundary

Runnable synthetic scenario for repository-to-worker trust. It does not test host escape, arbitrary command execution, or production sandbox security.

From the `AI-Security-Simple-Systems` root, build the image and run `world_harness` using this folder's `world.toml` (defended) or `world-vulnerable.toml` (paired vulnerable control). It serves on loopback port `18085` or `18185` respectively.

Follow [`../codex-qualification/CATEGORY-05-07-WORLDS.md`](../codex-qualification/CATEGORY-05-07-WORLDS.md) for the exact build/start/test/inspect/stop commands and the `WorldClient` tool-call example.
