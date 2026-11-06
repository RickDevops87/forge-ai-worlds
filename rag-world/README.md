# Category 6 — RAG and persistent-memory integrity

Runnable synthetic lexical-retrieval and memory-provenance scenario. It does not use embeddings, a production vector database, or real company documents.

From the `AI-Security-Simple-Systems` root, build the image and run `world_harness` using this folder's `world.toml` (defended) or `world-vulnerable.toml` (paired vulnerable control). It serves on loopback port `18086` or `18186` respectively.

Follow [`../codex-qualification/CATEGORY-05-07-WORLDS.md`](../codex-qualification/CATEGORY-05-07-WORLDS.md) for the exact build/start/test/inspect/stop commands, operator-only document revocation, and the `WorldClient` tool-call example.
