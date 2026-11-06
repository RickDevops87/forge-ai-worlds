# Forge AI Worlds

This is the reusable environment layer for AI-security exercises—not a retail
application. A “skin” here means a versioned **world pack**: an OCI image plus a
small TOML manifest describing how to run it. A world can model whatever scoped
system we choose to build (for example, an office workflow, a support operation,
a cloud console, or a Web3 application). The environment's own code and state
rules live in its image; the runner does not hard-code business semantics.

## Layers and trust boundaries

- **World pack:** the target environment/image, exposed through its HTTP API.
- **Agent/model:** selected independently. The world image contains no model
  weights, provider key, Jupyter credentials, or host home mounts.
- **Jupyter:** trusted operator console on the host. Existing Jupyter IPC stays
  unchanged. A notebook connects to the world through its host-published
  `127.0.0.1:<host_port>` HTTP endpoint.

This keeps “which world?” separate from “which model/agent?” Reuse the same model
against different world packs, or compare models against one fixed world. The
world runner never launches an agent or makes inference requests. The email-action
pack includes an explicit host-side Ollama client; it receives only a per-session
agent token, while the operator token stays outside the writable container mount.
Provider credentials stay outside the world image. A cloud-backed model requires
explicit opt-in because its prompts leave the host.

Candidate assessment definitions live in [`scenarios/`](scenarios/). The initial
[email content-to-action scenario](scenarios/email-content-to-action.md) is a
draft until its image and end-to-end path are built and reviewed.

## Pack layout

```text
worlds/<world-id>/
  world.toml       # ports, image and resource bounds
  Containerfile    # authored for this world
  ...              # environment app, synthetic data, tests and documentation
```

The OCI image should run its HTTP service on `0.0.0.0:<container_port>` and use
`/world-state` for mutable per-run data. Keep world fixtures, prompts, tools,
policies and expected outcomes versioned with the pack. Build the image locally;
the runner deliberately does not pull images or inherit ambient environment
variables. Only declared non-secret `FORGE_WORLD_*` settings and a generated
operator token are passed to the world process.

Example `world.toml`:

```toml
schema_version = 1

[world]
id = "example-world"
title = "Example synthetic environment"
image = "localhost/forge-example-world:dev"

[interface]
container_port = 8080
host_port = 18080

[resources]
memory = "2g"
cpus = 2
pids_limit = 256
container_uid = 1000

[storage]
state_root = "../../var/world-runs/example-world"
```

Copy the manifest into a new pack, assign a unique ID and loopback port, author
the environment image, then build it with Podman. Images are local inputs: a
missing image is an error, not a trigger for registry access.

## Run lifecycle

From the Simple Systems project root:

```bash
PYTHONPATH=. python3 -m world_harness.cli --config worlds/<world-id>/world.toml start
PYTHONPATH=. python3 -m world_harness.cli --config worlds/<world-id>/world.toml status <run-id>
PYTHONPATH=. python3 -m world_harness.cli --config worlds/<world-id>/world.toml stop <run-id>
```

`start` requires rootless Podman and an already-built local image. It creates a
per-run internal network (no external egress), publishes only the configured
container port on host loopback, and applies read-only root filesystem, a
per-run writable state directory, unprivileged UID mapping, no added Linux
capabilities, `no-new-privileges`, and CPU/memory/PID limits. `stop` removes only
the container and private network carrying the exact Forge world/run labels;
it preserves run state for review. State cleanup is a separate operator action.

From a trusted Jupyter notebook, the API URL returned by `start` is the target:

```python
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:18080/health", timeout=3) as response:
    print(json.load(response))
```

Do not expose a world on `0.0.0.0`, use host networking, mount host credentials,
or put secrets in a pack. World containers run rootless under Rick's user; this
reduces privilege but is not a VM boundary. Treat images as executable code and
review them before building/running. Unit tests of the runner are not isolation
evidence.

## First world: email content to action

The first pack implements four fixed cases: benign summary, prompt injection,
draft-only, and an explicitly approved synthetic send. Its vulnerable mode can
read a synthetic internal note and write only to a local outbox. Its defended
mode denies that note and requires trusted case-level recipient approval before
an outbox write. Neither mode has SMTP or a real delivery path.

Build the image locally, then start a defended instance:

```bash
podman build --file worlds/email_action/Containerfile \
  --tag localhost/forge-email-action:dev worlds/email_action
PYTHONPATH=. python3 -m world_harness.cli \
  --config worlds/email_action/world.toml start
```

`start` returns a `run_id` and a host-only `operator_token_path`; do not show or
send that token to the model. Check the environment without invoking a model:

```bash
curl --fail http://127.0.0.1:18080/health
```

An explicit model test is separate. It uses the local Ollama API from the
host-side agent client and permits at most five model requests by default:

```bash
PYTHONPATH=. python3 -m worlds.email_action.agent \
  --run-id <run-id> --case injection --model fable-forge:latest
```

Case choices: `benign`, `injection`, `draft_control`, `approved_send`. A
cloud-tagged Ollama model requires `--allow-cloud`; use that only after accepting
that synthetic prompts leave the host. Model invocation was not part of this
build. Inspect host `agent-evidence.jsonl`, container `events.jsonl`, and
`outbox.jsonl` together; client completion alone is not an assessment verdict.

To compare controller modes, change `FORGE_WORLD_MODE` in the manifest to
`vulnerable`, start a **new run**, and keep the model, case, and prompt unchanged.
Vulnerable mode is synthetic-only and cannot send real email. Automated scoring
and repeated trials are not yet wired up.

The additive [Gemma Cloud lab runbook](email_action/GEMMA-CLOUD-LAB-RUNBOOK.md)
records the Ollama Cloud Gemma 4 integration, a separate synthetic vulnerable
profile, bounded execution commands, and the first model-driven results. Cloud
inference requires `--allow-cloud` because synthetic prompts leave the host.

## Categories 5–7: fixed-job sandbox, RAG/memory, and monitoring

Three runnable synthetic worlds now use the generic authenticated tool API and
rootless world runner. Each has separate defended and vulnerable manifests,
ports, and state roots. Build and operator steps are in
[`codex-qualification/CATEGORY-05-07-WORLDS.md`](codex-qualification/CATEGORY-05-07-WORLDS.md).
These are local scenario targets; model inference stays in a separately
authorized host adapter. The runtime smokes demonstrated the synthetic backend
effects in both modes, but they are not real-model qualification or client-grade
containment evidence.

Category 8 has no environment in this lab. The retained artifact-integrity
scenario is only an adjacent release-governance control exercise; it does not
qualify model extraction, training-data privacy, or training-data poisoning.
Those tests require an owner-authorized model, relevant weights/data and access,
plus a dedicated evaluation environment.
