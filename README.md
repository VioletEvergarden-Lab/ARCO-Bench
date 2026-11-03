# ARCO-Bench

ARCO-Bench evaluates model-generated repairs to disrupted UAV logistics plans. It supplies public task instances, prompts, API adapters, executable feasibility checks and reference-quality scoring. UAV assignments and mission order stay fixed; a repair controls holds, service paths, departures and charging.

The primary panel contains 147 tasks: Core-72, 36 original network conditions, 24 paired conditions and 15 ADDS conditions. ADDS is a simulation-derived network with operational context; UAV schedules and disruptions are benchmark adaptations.

## Install

Open this folder in VS Code and use a PowerShell terminal. The tested environment is Windows x86-64 with Python 3.12.4.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B smoke_submission.py
```

The smoke check prints `PASS` and uses a reference solution. Dependencies are NumPy 1.26.4, SciPy 1.13.1 and HiGHS/highspy 1.15.1. The package contains the task and scoring data required to run the benchmark; no external repository access is needed.

## Run a model

Copy the credential template outside the project and edit the copy:

```powershell
Copy-Item credentials\provider.env.example ..\arco_keys.env
```

Fill `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` or the variable used by your configuration. The runner reads this file only when passed with `--env-file`.

Prepare one task without a network call, then run it:

```powershell
.\.venv\Scripts\python.exe -B run_benchmark.py prepare --config configs/paper_deepseek.json --suite core72 --limit 1 --output runs/first_task
.\.venv\Scripts\python.exe -B run_benchmark.py run --config configs/paper_deepseek.json --env-file ../arco_keys.env --suite core72 --limit 1 --output runs/first_task
```

`run` calls the selected API and may incur charges. It parses the answer, checks feasibility, scores reference quality and writes results. For all 147 primary tasks, omit `--suite core72 --limit 1` and choose a new output directory. `configs/paper_luna.json` selects the other paper preset. Presets retain the corresponding prompt and generation settings; a new model generation need not reproduce a previous answer.

For another model, create `configs/local/`, copy `configs/custom_chat_completions.json` or `configs/custom_responses.json` there, and edit its API URL, model ID, credential-variable name and generation options. Pass that configuration to the same command. Other JSON interfaces can use an adapter following `benchmark/example_adapter.py`.

## Read results

| File in your output directory | Contents |
|---|---|
| `summary.json` | Per-suite quality counts, completeness and greedy/model selection |
| `results.csv` | Per-task results, readable in Excel |
| `scored.jsonl` | Verifier details, objectives and selected repair decisions |
| `responses.jsonl` | Your model's answers, available for independent rescoring |
| `request_status.jsonl` | Requests that did not produce a model output |
| `run.json`, `requests/`, `attempts/` | Run configuration and request/response records |

To score answers collected with another client, use `run_benchmark.py score`. See [REPRODUCING.md](REPRODUCING.md) for configuration, input format and resuming a run.

## Contents

| Path | Purpose |
|---|---|
| `run_benchmark.py`, `benchmark/`, `configs/` | Unified execution, API adapters and model configurations |
| `data/catalog.json`, `data/tasks/` | Task selection and public problem definitions |
| `prompts/`, `schema/` | Prompt templates and Core-72 answer schema; network contracts are in their prompts |
| `data/public/`, `data/private/`, `references/` | Core task records and evaluator reference solutions |
| `vendor/`, `admit.py`, `rescore.py` | Verifiers, optimization kernels, greedy policy and scoring |
| `tests/`, `smoke_submission.py` | Local HTTP and reference-based interface checks |
| `LICENSES/` | Distribution terms and source attribution |

Reference solutions supply the scoring targets and are withheld from model requests. The greedy comparator is computed from each public task. Results and request records are created in your chosen output directory when you run the benchmark. Repository and anonymous distributions use the same execution code.
