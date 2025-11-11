# Inference Harness (Cursor CLI friendly)

`scripts/inference/custom.py` is a self-contained harness for running agent-style
inference workloads inside the prebuilt SWE-fficiency Docker images and
materializing git patches for the evaluation pipeline.

## Key features
  `datasets.load_dataset("swefficiency/swefficiency", split="test")`, so no
  `swefficiency` Python package imports are required.
  env vars, and artifact copying using reusable templates. The provided
  `specs/cursor_cli.yaml` showcases how to install and run Cursor CLI.
  `mem_limit`/`memswap` settings mirror the eval harness defaults (4 vCPUs,
  32 GiB cap) and can be overridden per run.
  (`git diff --binary HEAD > /tmp/model.patch` by default) and copies the patch
  plus any extra artifacts back to `logs/run_inference/<run_id>/<spec>/<id>/`.
- **Auto cleanup** – containers and per-instance images are removed when each run
  completes (toggle with `--keep-containers` / `--keep-images`). Because image
  cleanup requires the container to be removed first, pass both flags if you need
  to keep a container around for debugging.
- **Live streaming** – pass `--stream-logs` (or set `DEBUG=1` on the Cursor CLI
  wrapper) to mirror container stdout/stderr to your console while logs are still
  written to disk.

## Directory layout
```
scripts/inference/
├── custom.py                # CLI entrypoint
├── README.md                # this file
├── specs/
│   └── cursor_cli.yaml      # example spec for Cursor CLI
└── templates/
    └── install_cursor_cli.sh.j2
```

## Running the harness
```bash
python scripts/inference/custom.py \
  --run-id cursor_dryrun \
  --spec scripts/inference/specs/cursor_cli.yaml \
  --num-workers 4 \
  --instance-ids numpy__numpy-18065 pandas-dev__pandas-28447 \
  --var cursor_cli_args="--max-steps 75" \
  --vars-file my_harness_vars.yaml
```

Important flags:
- `--dataset/--split` – override the HF source if you have a forked dataset.
- `--instance-ids` / `--instance-regex` / `--max-instances` – limit which tasks
  run.
- `--hf-token` + `--hf-cache-dir` – supply auth/caching for private mirrors.
- `--no-pull` – skip the default `docker pull swefficiency/swefficiency_images:<id>`
  if the image already lives locally.

Each instance writes logs + artifacts under:
```
logs/run_inference/<run_id>/<spec_name>/<instance_id>/
├── install_cursor_cli.log
├── cursor_cli.log
├── patch.log
└── patch.diff
```

## Spec anatomy
`scripts/inference/specs/cursor_cli.yaml` demonstrates the schema:

- `docker`: runtime defaults (image template, user, workdir).
- `variables`: run-level defaults that can be overridden via `--vars-file` or
  repeated `--var KEY=VAL` flags.
- `prework.scripts`: list of template-backed shell scripts copied into the
  container. Each entry supports `env`, `timeout_sec`, `continue_on_error`, and
  is rendered with the instance metadata plus `vars` map.
- `inference`: the command that triggers your agent / CLI. The `env` keys are
  Jinja-rendered, making it easy to inject secrets (e.g., `CURSOR_API_KEY`).
- `patch`: how to produce the git diff; customize the target path or command if
  you need staged changes only.
- `artifacts`: arbitrary `container_path -> host_filename` copies executed after
  the patch finishes (handy for custom logs or metrics).

### Template context
Every template (file or inline command) can reference:
- `instance`: the raw HF row (e.g., `instance.repo`, `instance.workload`).
- `instance_id`: shorthand for `instance["instance_id"]`.
- `spec`: the parsed spec dataclass (useful for `spec.docker_workdir`).
- `vars`: merged variables from the spec defaults, `--vars-file`, and `--var`
  CLI flags (later sources win).

## Producing predictions for `swefficiency eval`
Once the harness completes, convert each `patch.diff` into a JSONL prediction
record expected by the evaluation CLI (instance_id + model_patch). A minimal
helper script could walk `logs/run_inference/<run_id>/<spec>/` and assemble a
`predictions/converted/<run>.jsonl` file.

## Future extensions
- Add more spec examples (OpenHands, SWE-agent, etc.).
- Surface GPU/NVMe knobs if required for alternative environments.
- Integrate per-step timeouts or heartbeat telemetry if we start running longer
  LLM loops in-container.
