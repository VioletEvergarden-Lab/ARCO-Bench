# ARCO-Bench

ARCO-Bench evaluates repairs to disrupted UAV logistics plans using an executable event verifier and lexicographic recovery objectives. UAV assignments and mission order remain fixed; repair decisions control mission holds, service paths, departures and charging. The package supports candidate validation, reference-quality evaluation, verifier-gated selection and diagnosis of the coordination required to reach a recovery target.

The saved evidence covers Core-72, controlled network studies, coordination and capacity diagnostics, and ADDS simulation-derived networks with operational context. ADDS uses generated demand and saved simulation geometry; its recovery schedules are experimental adaptations.

## Install and run

The supported and tested platform for this replication package, including all eight study checks, is 64-bit Windows with Python 3.12.4, NumPy 1.26.4 and SciPy 1.13.1. The complete study replay is not supported on Linux or macOS in this version. From the package directory:

```sh
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -B smoke_submission.py
python -B rescore.py --responses responses/luna_complete.jsonl --output local_results/luna
```

The smoke check prints `PASS`. The scoring example writes `local_results/luna/SUMMARY.json` and `SCORED_RECORDS.jsonl`; the saved Luna panel contains 72 records and 68 reference-quality repairs. These commands disable network connections and require no API key.

Install `requirements-studies.txt` for the network studies, saved-query diagnostics and figure scripts. Those studies use HiGHS/highspy 1.15.1, NetworkX 3.2.1 and Matplotlib 3.8.4. Installation may download packages; the bundled experiment inputs and saved-output checks work offline.

## Contents

| Path | Use |
|---|---|
| `data/`, `references/` | Core-72 public tasks, evaluator records and reference plans |
| `prompts/`, `schema/`, `sources.json` | Generation instructions, answer format and source groups |
| `responses/`, `provenance/` | Saved answers, original requests and provider terminals |
| `admit.py`, `rescore.py`, `build_results.py` | Public validation, reference scoring and result summaries |
| `vendor/` | Implementation used by the Core-72 evaluator |
| `results/`, `evidence/` | Saved outcomes and supporting numerical records |
| `studies/` | Network instances, solvers, saved plans, queries and analysis scripts |
| `LICENSES/` | Distribution terms and third-party attribution |

[REPRODUCING.md](REPRODUCING.md) maps the paper's experiments to inputs, commands and outputs. Start with saved-output replay. Optional request preparation and model access are described separately there. Evaluator references are included for reproduction and were withheld during candidate generation.
