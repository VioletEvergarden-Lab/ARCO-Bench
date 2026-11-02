# ARCO-Bench

ARCO-Bench evaluates repairs to disrupted UAV logistics plans using an executable event verifier and lexicographic recovery objectives. UAV assignments and mission order remain fixed; repair decisions control mission holds, service paths, departures and charging. Use the benchmark to test a model, compare its repairs with certified references, apply verifier-gated selection, or reproduce the saved results.

The saved evidence covers Core-72, controlled network studies, coordination and capacity diagnostics, and ADDS simulation-derived networks with operational context. ADDS uses generated demand and saved simulation geometry; its recovery schedules are experimental adaptations.

## Install

Open the extracted folder containing this README in VS Code, then open a PowerShell terminal. The supported and tested platform is Windows x86-64 with Python 3.12.4. The complete study replay is not supported on Linux or macOS in this version.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-studies.txt
.\.venv\Scripts\python.exe -B smoke_submission.py
```

The smoke check prints `PASS`. Dependencies are NumPy 1.26.4, SciPy 1.13.1, HiGHS/highspy 1.15.1, NetworkX 3.2.1 and openpyxl 3.1.5. Installation may download packages; saved-output evaluation works offline.

## Run a model

Copy the credential template outside the package and edit the copy in VS Code. Fill the variable for the provider you will use; the runner loads this file only when explicitly passed with `--env-file`.

```powershell
Copy-Item credentials\provider.env.example ..\arco_keys.env
```

Start with one Core-72 task. `prepare` writes the request without contacting a provider; `run` sends it, validates the returned plan and writes the scores. **`run` invokes the selected API and may incur charges.**

```powershell
.\.venv\Scripts\python.exe -B run_benchmark.py prepare --config configs/paper_deepseek.json --suite core72 --limit 1 --output runs/first_task
.\.venv\Scripts\python.exe -B run_benchmark.py run --config configs/paper_deepseek.json --env-file ../arco_keys.env --suite core72 --limit 1 --output runs/first_task
```

For the full primary panel, omit `--suite core72 --limit 1` and choose a new output directory. This runs 147 tasks: Core-72, 36 original network conditions, 24 paired conditions and 15 ADDS conditions. `configs/paper_luna.json` selects the other paper model. Paper presets preserve the archived request content and generation settings; new generations may differ from saved outputs.

To test another model, copy `configs/custom_chat_completions.json` or `configs/custom_responses.json` into `configs/local/`, edit its API base URL, model ID, credential-variable name and supported generation parameters, then pass that file to the same `run` command. Other JSON interfaces can implement the adapter in `benchmark/example_adapter.py`. JSON files configure the run; execute `run_benchmark.py` in the terminal.

Open these files under your output directory:

| File | Contents |
|---|---|
| `summary.json` | Per-suite quality counts, completeness and greedy/model selection results |
| `results.csv` | One row per task/attempt, suitable for Excel |
| `scored.jsonl` | Detailed verifier results, objectives and selection decisions |
| `responses.jsonl` | Model output text, reusable by the offline `score` command |
| `request_status.jsonl` | Requests without model outputs, kept separate from model scores |
| `run.json`, `requests/`, `attempts/` | Configuration, input identities and durable request/response records |

## Reproduce saved results

This route needs no API key and performs no model or optimizer calls:

```powershell
.\.venv\Scripts\python.exe -B run_benchmark.py replay --provider luna --output runs/saved_luna --checks
```

The primary saved reference-quality counts are 68/72, 32/36, 22/24 and 15/15 for Luna, and 69/72, 24/36, 19/24 and 13/15 for DeepSeek. The additional eight study checks report `PASS`. See [REPRODUCING.md](REPRODUCING.md) for all commands, output interpretation, custom adapters and the paper-to-data mapping.

## Contents

| Path | Use |
|---|---|
| `run_benchmark.py`, `benchmark/`, `configs/` | Unified model execution, API adapters, evaluation and presets |
| `data/`, `references/` | Core-72 public tasks, evaluator records and reference plans |
| `prompts/`, `schema/`, `sources.json` | Generation instructions, answer format and source groups |
| `responses/`, `provenance/` | Saved answers, original requests and provider terminals |
| `admit.py`, `rescore.py`, `build_results.py` | Public validation, reference scoring and result summaries |
| `vendor/` | Implementation used by the Core-72 evaluator |
| `results/`, `evidence/` | Saved outcomes and supporting numerical records |
| `studies/` | Network instances, solvers, saved plans, queries and analysis scripts |
| `LICENSES/` | Distribution terms and third-party attribution |

Evaluator references are included for reproduction and are withheld from model requests and public feasibility validation. Repository and anonymous distributions use the same execution code. Data sources and distribution terms are in `LICENSES/README.md`.
