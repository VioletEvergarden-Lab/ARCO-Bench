# Running ARCO-Bench

Run commands from the project root with the environment installed as described in the README. The examples use `python` from that environment; in an unactivated PowerShell terminal use `.\.venv\Scripts\python.exe`. Python 3.12.4 on Windows x86-64 is the tested platform; other platforms have not been verified.

## Credentials and configuration

Copy `credentials/provider.env.example` to a file outside the project, such as `../arco_keys.env`, and enter the variable required by your configuration. `--env-file` loads `NAME=value` lines, including quoted values. File values take precedence over process environment variables. The file is read as data and no file is discovered automatically.

`configs/paper_deepseek.json` and `configs/paper_luna.json` select the paper's model IDs, prompts and generation parameters. Access to the chosen hosted model is required. Their per-provider concurrency is 1 for Core-72, 4 for original networks/core anchors, and 2 for paired/ADDS conditions.

For another model, copy a template into `configs/local/` and edit:

| Field | Meaning |
|---|---|
| `adapter` | `chat_completions`, `responses` or `module:Class` |
| `base_url` | API base URL; the adapter adds its endpoint path |
| `model` | Model ID understood by that service |
| `api_key_env` | Credential variable name, or `null` for an unauthenticated local service |
| `parameters` | Generation options supported by the service |
| `prompt_variant` | `deepseek` system/user format or `luna` user format |
| `suites`, `concurrency` | Task groups and number of parallel requests |
| `accepted_models` | Optional returned aliases; requested ID and its dated suffixes are accepted automatically |

Custom configurations keep the same task data, verifier and scoring tolerances. Match parameters to the target service, including its supported output-limit field. The single-answer protocol uses non-streaming responses without tools or multiple choices.

Built-in adapters handle non-streaming Chat Completions and synchronous/asynchronous Responses. For another JSON protocol, implement `build`, `headers`, `parse` and `poll_path` as demonstrated in `benchmark/example_adapter.py`, then use its `module:Class` as `adapter`. HTTP is allowed for loopback services; remote HTTP requires `allow_http: true`. Redirects are not followed.

## Execute

```sh
python -B run_benchmark.py prepare --config configs/paper_deepseek.json --output runs/deepseek
python -B run_benchmark.py run --config configs/paper_deepseek.json --env-file ../arco_keys.env --output runs/deepseek
```

`prepare` writes the exact requests without credentials or network access. `run` can also create a fresh run directly. Inspect `run.json` and `requests/` before submitting if desired. JSON files configure the run; `run_benchmark.py` is the executable entry point.

Use the same selectors on preparation and execution:

| Selector | Meaning |
|---|---|
| `--suite core72` | 72 Core-72 tasks |
| `--suite original36` | 36 original network conditions |
| `--suite paired24` | 24 paired conditions |
| `--suite adds15` | 15 ADDS conditions |
| `--suite paired_repeats core_anchors` | Optional repeat protocol: 24 repeated attempts and 12 Core anchors |
| `--record-id CA12_CORE_001` | Select a condition; may be repeated |
| `--limit 1` | Select the first attempt for a small initial run |

The default `all` means the four primary suites, 147 attempts. Optional repeated attempts remain separate in summaries. `python run_benchmark.py list` lists all groups. Each experiment uses a new output directory, normally under `runs/`.

Repeat the same `run` command with `--resume` after interruption. Completed attempts are reused; accepted asynchronous requests resume by querying their stored response IDs. A POST with uncertain delivery is not automatically repeated. Partial runs exit with code 2 and retain available results. No retry is used to seek a better answer.

## Interpret and rescore

`summary.json` reports each suite separately. `reference_quality` counts feasible answers matching the reference objective within the benchmark's tolerance; `admissible` counts answers accepted by the public verifier. `selected_reference_quality` evaluates the verifier-gated choice between the newly computed greedy plan and model plan; ties retain greedy. `results.csv` is the per-instance view, and `scored.jsonl` contains objectives, errors and selected decisions.

Requests without model outputs appear in `request_status.jsonl`. Summaries show planned and evaluated counts; a full-panel rate is `null` until all selected attempts have an output. Malformed, infeasible, refused or truncated model answers count as unsuccessful outputs.

`response_seconds` measures request preparation through response extraction; `available_seconds` additionally includes public validation. Resumed attempts include interruption time. The quality count within 600 seconds uses this recorded availability and is `null` if availability is absent.

Your own saved answers can be evaluated without an API key:

```sh
python -B run_benchmark.py score --config configs/local/my_model.json --responses my_answers.jsonl --output runs/my_model_scored
```

Each JSONL row needs `record_id` and `raw_text`, the unmodified answer string. Use `attempt_id` from a prepared `run.json` for repeated or overlapping conditions. A previous run's `responses.jsonl` is directly reusable. Unknown or duplicate identities are rejected; missing attempts remain visible. Use the same task selection and configuration as generation. `score` invokes neither the network nor an optimizer.

## Inputs and reference solutions

`data/catalog.json` defines task membership and hashes; `data/tasks/` supplies the public task text. Six prompt templates provide Core, network and ADDS instructions in the two supported prompt variants. Template composition preserves the paper presets' request content and parameters.

`references/` and `data/private/evaluator_records/` contain evaluator targets, witness plans and Core ID mappings. These are part of the benchmark definition and are never sent to the model. `private` denotes the evaluator side of this boundary and requires no private repository access. Greedy plans are generated from public tasks at evaluation time. Core-72 can also be checked with `admit.py` and scored with `rescore.py`.

ADDS tasks are simulation-derived networks with operational context. Source demand and model geometry are distinct from the adapted UAV assignments, deadlines, disruptions and capacities. All inputs needed for the supplied tasks are bundled; no FlexSim installation or source workbook download is required. Source attribution and the upstream DOI are in `LICENSES/README.md`.

## Interface checks

```sh
python -B smoke_submission.py
python -B -m unittest discover -s tests -p test_benchmark.py -v
```

Tests use reference solutions and synthetic invalid answers through a temporary loopback HTTP server. They cover all 147 primary tasks, both built-in API protocols, a custom adapter, independent scoring, interrupted-request recovery and credential handling. They do not call paid providers. Hosted model access is exercised only when running that service.
