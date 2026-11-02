# Running and reproducing ARCO-Bench

Run commands from the directory containing `README.md`. The supported and tested platform for the complete replay below is Windows x86-64 with Python 3.12.4. The Core-72 scorer requires NumPy 1.26.4 and SciPy 1.13.1. Study replay also imports HiGHS/highspy 1.15.1 and NetworkX 3.2.1; openpyxl 3.1.5 reads the ADDS workbook.

The eight-group study entry is Windows-only in this version: archived helpers import `msvcrt` and read Windows-style paths in saved records. Linux and macOS are not supported for the complete study replay; success of an individual command does not establish full-platform support.

## Unified model workflow

The examples below use `python` from the installed environment. In an unactivated VS Code PowerShell terminal, replace it with `.\.venv\Scripts\python.exe` as shown in the README. Every command can also be invoked from another working directory using absolute script/config paths; output paths are relative to that working directory.

1. Copy `credentials/provider.env.example` to a local file outside the package, such as `../arco_keys.env`. Enter `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` or `MODEL_API_KEY` as needed. Values in the explicit env file take precedence over process environment variables. The file supports `NAME=value` and quoted values; it does not execute shell expressions. No credential file is discovered automatically.
2. Select `configs/paper_deepseek.json`, `configs/paper_luna.json` or your own configuration. Paper presets reuse each archived request's model identifier, prompt and generation options, with the recorded per-provider concurrency (Core-72: 1; original networks: 4; paired and ADDS: 2). They run one selected model at a time. Access to those model versions is required for a new generation run.
3. Prepare the requests, inspect `run.json` and `requests/`, then run with the same configuration and selection. `prepare` does not need credentials or access the network. `run` submits API requests and automatically evaluates the responses.

```sh
python -B run_benchmark.py prepare --config configs/paper_deepseek.json --output runs/deepseek_new
python -B run_benchmark.py run --config configs/paper_deepseek.json --env-file ../arco_keys.env --output runs/deepseek_new
```

`run` also prepares a new directory automatically. Use `--suite core72 --limit 1` on both commands for an initial single-task run. `--record-id CA12_CORE_001` selects a particular condition and can be repeated. The selected requests, including a limited test run, are recorded in `run.json`. Each new experiment uses its own output directory; files under the benchmark's data, references and studies are not overwritten.

| Suite | Attempts per model | Scope |
|---|---:|---|
| `core72` | 72 | Complete-public Core-72 condition |
| `original36` | 36 | Original network conditions |
| `paired24` | 24 | First responses for paired network conditions |
| `adds15` | 15 | ADDS simulation-derived conditions |
| `paired_repeats` | 24 | Archived repeated conditions, with their original repeat IDs |
| `core_anchors` | 12 | Core anchors used in the network study |

The default `all` selection comprises the first four suites (147 attempts). For optional groups, use e.g. `--suite paired_repeats core_anchors`. `python run_benchmark.py list` lists the available suites. Repeated conditions remain separate from first responses in the summaries.

To resume an interrupted run, repeat its `run` command with `--resume`. Completed attempts are reused. An accepted Responses API request resumes by querying its stored response ID. A POST whose delivery is uncertain is never automatically repeated; the status is retained for inspection. An unsuccessful or partial run exits with code 2 and still writes available results. No automatic retry seeks a better-quality answer.

## Test another model or API

Create `configs/local/`, copy a custom configuration template there, and edit:

| Field | Meaning |
|---|---|
| `adapter` | `chat_completions`, `responses`, or `module:Class` |
| `base_url` | API base, e.g. `https://host/v1`; the adapter adds its endpoint path |
| `model` | Model ID understood by that API |
| `api_key_env` | Name of the local credential variable; use `null` for an unauthenticated local service |
| `parameters` | Supported generation options, including the output limit; no automatic parameter substitution |
| `prompt_variant` | `deepseek` (archived system/user messages) or `luna` (archived user messages) |
| `suites`, `concurrency` | Selected conditions and parallel requests; concurrency may also be a per-suite mapping |
| `accepted_models` | Optional returned model aliases; the requested ID and its dated suffixes are accepted by default |

```sh
python -B run_benchmark.py run --config configs/local/my_model.json --env-file ../arco_keys.env --output runs/my_model
```

Custom models use the same public tasks, instructions, schema, verifiers and reference-quality tolerances. Model options and chosen prompt variant are saved with the run. Match options to the target API's supported fields; for example, a compatible Chat Completions service may use `max_completion_tokens` rather than `max_tokens`. Streaming, tools and multiple returned choices are outside this benchmark's single-answer protocol.

The built-in adapters support non-streaming [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and synchronous/asynchronous [Responses](https://developers.openai.com/api/docs/guides/background). HTTP is accepted for loopback services; other unencrypted HTTP endpoints require `allow_http: true`. Redirects are not followed.

For a different JSON protocol, implement the four methods demonstrated in `benchmark/example_adapter.py`: `build(messages, config)` returns an endpoint path and request body; `headers(key)` supplies authentication; `parse(object)` returns a `Completion`; `poll_path(response_id)` returns an asynchronous retrieval path or `None`. Put the module in the package or on `PYTHONPATH` and select its `module:Class` in the configuration. The included example implements a small `/generate` JSON contract and is exercised by the local HTTP tests. Adapters do not change task construction or scoring.

## Read and rescore results

`summary.json` contains separate groups for each suite. `reference_quality` counts repairs meeting the existing reference-quality criterion; `admissible` counts plans accepted by the public verifier. `selected_reference_quality` evaluates the actual verifier-gated choice between the saved greedy plan and the candidate, with ties retaining greedy. Detailed objectives, first differing tiers, verifier messages and selection results are in `scored.jsonl`; `results.csv` provides a flat view.

Operational failures and missing responses are in `request_status.jsonl`, separate from model outputs. The summary always shows planned and evaluated counts. A full-panel quality rate is reported only when every selected attempt has a model output; otherwise it is `null`. A completed but malformed, infeasible, refused or truncated answer remains an unsuccessful model output. Saved historical panel counts can be compared using the quality numerator and planned conditions; the original table-building commands below retain the paper's existing presentation.

`response_seconds` measures the request through response extraction. `available_seconds` additionally includes public validation; resumed attempts include interruption time. The 600-second quality count uses recorded availability, and is `null` when availability was not recorded. These measurements describe the new run, not the historical machine or API latency.

To score outputs collected with another client, create JSONL rows with `record_id` and `raw_text` (the unmodified answer string). Use `attempt_id` from the prepared `run.json` to distinguish repeats or overlapping suites. The model must answer using the public ID shown in its request. Importing does not repair or complete an answer.

```sh
python -B run_benchmark.py score --config configs/local/my_model.json --responses my_answers.jsonl --output runs/my_model_scored
```

The same command can rescore a previous run's `responses.jsonl` in a new directory. Missing tasks remain visible and duplicate/unknown identities are rejected. `score` requires no API key, performs no network calls and invokes no optimizer.

## Saved-output reproduction

```sh
python -B run_benchmark.py replay --provider luna --output runs/saved_luna --checks
python -B run_benchmark.py replay --provider deepseek --output runs/saved_deepseek
```

Both commands evaluate the original saved outputs through the unified scoring path. `--checks` additionally executes the eight saved-study checks and writes `saved_studies/SUMMARY.json` under the chosen output directory. Expected primary quality counts (Core-72 / original36 / paired24 / ADDS15) are **68 / 32 / 22 / 15** for Luna and **69 / 24 / 19 / 13** for DeepSeek. Greedy/model selection reaches 71/72 in Core-72 for either model. The following original commands reproduce the detailed paper tables and diagnostic records:

```sh
python -m pip install -r requirements-studies.txt
python -B smoke_submission.py
python -B build_results.py --output local_results/core72
python -B studies/replay_saved.py --group all --output local_results/studies
```

`build_results.py` rescans the saved answers with the public verifier, evaluates reference quality and reconstructs the actual verifier-gated selections. It writes `MASTER.jsonl`, CSV tables, selection records and `BUILD_RESULT.json`. Its 936 rows include labelled historical instruction conditions as well as the complete-public panel used in the current paper. The latter has 69/72 DeepSeek and 68/72 Luna reference-quality repairs; the greedy policy has 38/72 and its selections with either model have 71/72.

`studies/replay_saved.py` checks stored decisions, target witnesses, query records and derived classifications. It blocks network connections and optimizer calls, writes only to the selected output directory and ends with `local_results/studies/SUMMARY.json`. A successful run reports `PASS`, zero network calls and zero optimizer calls. A single group can be selected with `--group networks`, `sensitivity`, `core_diagnostics`, `scope`, `candidate_diagnostics`, `origin_target`, `capacity` or `adds`.

## Inputs and result locations

The study folder names retain the original experiment identifiers. References, candidate responses, unsuccessful outputs and bounded-query records are included alongside successful plans.

| Paper evidence | Inputs and saved outputs under `studies/` |
|---|---|
| Core-72 R3/R4, action restrictions, capacity and preference diagnostics | `arco_codex_research_20260925/`, `arco_codex_research_20260930/`, `arco_closing_study/core_r4/`; derived tables in `arco_stage_research_20261009/analysis/core_*` |
| 36 original network conditions | `arco_closing_study/networks/`, `online/`, `evaluation/`; five-method comparison in `arco_focused_revision_20261002/results/comparison/` |
| 24 paired conditions (first responses in the main panel; repeats also retained) | `arco_focused_revision_20261002/new_networks/`, `online/new_generation/`, `results/new_comparison/` and `results/arrival_selection/` |
| Repair-scope minima, joint witnesses and candidate/neighborhood queries | `arco_contribution_20261011/runs/e1*/`, `runs/e2*/` and corresponding `analysis/` files |
| Fixed-origin capacity interventions and fresh networks | `arco_contribution_20261011/runs/e3/`, `inputs/fresh/`, `runs/fresh/` |
| Eight-condition origin/target panel | `arco_core_revision_20261023/runs/origin_target/`, `analysis/origin_target_*` |
| Candidate and final-neighborhood classification | `arco_core_revision_20261023/analysis/candidates_*` and the linked original query records |
| Paired events and reservation-window sensitivity | `arco_stage_research_20261009/analysis/paired_*`, `arco_closing_study/window_sensitivity/` |
| ADDS | `arco_adds_external_20261024/instances/`, `source/`, `runs/` and `analysis/` |

The network checks cover 60 conditions, 300 deterministic plans and 120 initial model terminals. The origin/target panel retains 108 exact positions and 20 intervals. ADDS contains 15 conditions, 75 deterministic plans and 30 model outputs; its saved model reference-quality counts are 13/15 and 15/15, or 9/15 and 11/15 when requiring availability within 600 seconds. The two ADDS quality misses remain in the package and are diagnosed with their original scope queries.


ADDS provides operational context through a public logistics simulation dataset. Generated source demand, locker assignments and saved model geometry are distinguished from the experimental UAV assignments, deadlines, closures and reservation capacities. The source workbook, geometry and construction inputs are bundled; the [ADDS dataset DOI](https://doi.org/10.5281/zenodo.20491777) supplies the full upstream dataset. No FlexSim installation is needed for replay.

For individual records, use `admit.py` for public feasibility or `rescore.py` for reference evaluation. Each response JSONL row contains `record_id` and `raw_text`; the output contract is `schema/output.schema.json`. The `private` evaluator directory names refer to information withheld at generation time, not to a private GitHub dependency.

## Optional optimizer recomputation

The original optimizer and diagnostic drivers are retained within each study. Examples are `arco_closing_study/run_network_study.py`, `arco_focused_revision_20261002/scripts/run_comparison.py`, `arco_contribution_20261011/scripts/coordination_study.py` and `arco_adds_external_20261024/scripts/run_deterministic.py`. They can invoke optimization and may write experiment outputs. Use a separate working copy for new computations; the saved replay above does not invoke these batches. A new solver run can return different time-limited bounds.

The study-specific generation scripts remain available as source provenance. Use `run_benchmark.py run` for new model experiments, including ADDS: it writes a new run and leaves the delivered evidence intact. The older `prepare_requests.py` also remains available for Core-72 request preparation alone.

## Interface checks

```sh
python -B -m unittest discover -s tests -p test_benchmark.py -v
```

These tests exercise actual HTTP requests against a temporary loopback server with saved-answer fixtures, including all 147 primary tasks, both built-in protocols, a custom adapter, interrupted-response recovery and credential handling. They do not contact paid providers. Provider access and the availability of a particular hosted model are checked only when a researcher runs that model.

See `LICENSES/README.md` for data provenance and distribution terms.
