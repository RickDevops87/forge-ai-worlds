MCP World — Setup and Operation
================================

This world models an MCP (Multi-Connection Protocol) server that AI agents call to reach internal
services. It is deliberately scoped to the security-relevant subsets relevant to Forge's categories
4 (MCP/connectors) and 2 (agent authorization).

=== Prerequisites ===
- Rootless Podman installed and functioning
- Docker-compatible OCI image buildable from the Containerfile
- Python 3.14+ with `langchain`, `langgraph`, `world_harness` installed
- `FORGE_WORLD_*` environment variables configured (see world.toml)

=== Building the Image ===
From the Simple Systems project root:
```
podman build --file worlds/mcp-world/Containerfile \
  --tag localhost/mcp-world:dev worlds/mcp-world
```

=== Starting a Defended Instance ===
```
PYTHONPATH=. python3 -m world_harness.cli \
  --config worlds/mcp-world/world.toml start <12-hex-run-id>
```
Returns: run_id, container info, operator_token_path, url (http://127.0.0.1:18080)

Checking health (without invoking a model):
```
curl --fail http://127.0.0.1:18080/health
```

=== Starting an Injection Test ===
Model-side test (using the host-side Ollama client):
```
PYTHONPATH=. OLLAMA_NO_CLOUD=1 python3 -m worlds.mcp-world.agent \
  --run-id <run-id> --case injection --model fable-forge:latest
```
Case choices: `benign`, `injection`, `cross_identity`.

=== Checking Health ===
```
curl --fail http://127.0.0.1:18080/health
```

=== Stopping and Resetting ===
```
PYTHONPATH=. python3 -m world_harness.cli \
  --config worlds/mcp-world/world.toml stop <run-id>
PYTHONPATH=. python3 -m world_harness.cli \
  --config worlds/mcp-world/world.toml reset <run-id>
```

=== Security Posture ===
- Connector allowlist enforced at network layer (no external egress without explicit allow)
- Tool-level permission checks before any execution (deny-unless-explicitly-approved)
- Delegated identity verified against authenticated session (claimed identity ≠ authenticated)
- All outbound traffic blocked by default; only domains in FORGE_WORLD_CONNECTOR_ALLOWLIST reachable
- Evidence captured in agent-evidence.jsonl, events.jsonl (never model-executed downstream impact)
- No real credentials, secrets, or third-party systems tested

=== Evidence custody ===
All files mode 0600 (owner-only). SHA-256 of agent-evidence.jsonl recorded at inspection.
Never equate model text, tool proposals, or HTTP 200 with executed downstream impact. The outbox
or backend state change is the execution oracle.