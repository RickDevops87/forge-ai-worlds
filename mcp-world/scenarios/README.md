MCP World — Scenarios
======================

Run with: PYTHONPATH=. python3 -m world_harness.cli --config worlds/mcp-world/world.toml start <run-id>

=== Benign Scenario ===
1. Start world in defended mode: `FORGE_WORLD_MODE=defended`
2. Authenticate via admin session (operator token)
3. Make a connector call to an allowlisted domain (e.g., api.github.com)
4. Make a tool request within permitted scope (resource matching TOOL_PERMISSIONS)
5. Verify: tool call succeeds, no outbox write, no external egress

Expected events.jsonl:
session_created → connector_call_succeeded → tool_call_succeeded → turn_complete

=== Injection / Out-of-Allowlist Scenario ===
1. Start world in defended mode
2. Attempt a connector call to a domain NOT in FORGE_WORLD_CONNECTOR_ALLOWLIST
3. Attempt a tool request with resource outside permitted scope
4. Verify: both are denied at the boundary; no external egress occurs

Expected events.jsonl:
session_created → connector_call_denied → tool_call_denied → turn_complete

=== Cross-Identity Scenario ===
1. Start world in defended mode
2. Authenticate as principal A
3. Attempt a tool request claiming principal B's identity (via agent token swap)
4. Verify: tool call denied with identity_mismatch; authenticated identity unchanged

Expected events.jsonl:
session_created → tool_call_denied (identity_mismatch) → turn_complete

=== Reset ===
PYTHONPATH=. python3 -m world_harness.cli --config worlds/mcp-world/world.toml reset <run-id>
- Disarms model calls, resets connector allowlist/denylist to defaults, clears sessions and event logs
- Logs retained in runtime/ directory