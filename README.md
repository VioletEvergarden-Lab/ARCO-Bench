# ARCO-Bench

> **Version notice — 12 September 2026:** this remains the archival reproduction package. Read [V4 contract reconciliation and known limitations](V4_CONTRACT_RECONCILIATION.md) before interpreting the original counts or preparing new experiments. The complete-instruction, reconciled-contract panel has not been executed. Historical tasks, requests, responses and scoring code are unchanged.


**Aerial Recovery and Coordination — Candidate A V12P1, Core-72.**

ARCO-Bench evaluates candidate repairs for disrupted UAV logistics plans. Assignment, service order, vehicle type and incoming route are fixed; candidates adjust mission holds, service paths, departures and post-service charging under time, SOC and shared-resource constraints.

This release candidate provides the **archival reproduction suite**: public tasks, reference records, exact historical requests, primary raw outputs, operational-policy and portfolio candidates, and a self-contained offline evaluator. New-model adapter requirements are specified in `docs/MODEL_ADAPTER_INTERFACE.md`; the network runner is still to be implemented. The example credentials/configuration files reserve that interface and are not executable launch configurations.

## Install and check

Python 3.12.4, NumPy 1.26.4 and SciPy 1.13.1 are the recorded replay environment.

```sh
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -B smoke_test.py
python -B rescore.py --responses responses/luna.jsonl --output local_results/luna
python -B admit.py --responses responses/luna.jsonl --output local_results/luna_admission.jsonl
```

Read `local_results/luna/SUMMARY.json` for aggregate results and `SCORED_RECORDS.jsonl` for per-task diagnostics. The smoke and scoring entry points disable network connections and require no API key.

## Results and their roles

| Evidence group | Candidate source | Historical strict / 72 |
|---|---|---:|
| Original 128K panel | DeepSeek V4-Pro endpoint, 11 August 2026 UTC | 28 |
| Original 128K panel | Qwen 3.7-Plus | 34 |
| Original 128K panel | GPT-5.6 Luna | 48 |
| Operational policy | Resource-aware sequential greedy | 38 |
| Secondary candidate selection | Policy + DeepSeek | 52 |
| Secondary candidate selection | Policy + Qwen | 50 |
| Secondary candidate selection | Policy + Luna | 63 |

`responses/` and `results/original/` contain these seven groups. Online admissibility, offline reference quality and construct fidelity have separate fields; historical strict success is retained for traceability. See `docs/SCIENTIFIC_SCOPE.md`.

Optional `paper_evidence/` stores precomputed plotting data and separately labelled Flash-0731 and Pro-0813 summary evidence. These are not additional candidate files for the seven-group replay check. Full supplementary raw-response archives remain in the research workspace.

## Where to look

| Path | Contents |
|---|---|
| `data/CORE_72.json` | Task order and IDs |
| `data/public/records/` | 72 public problem states |
| `data/private/evaluator_records/` | 72 reference/evaluator records, withheld at generation |
| `schema/output.schema.json` | Output syntax |
| `provenance/requests/` | Exact request body for each of the 216 primary calls |
| `provenance/raw_provider_responses/`, `provenance/raw_transport/` | Provider terminals, transport and candidate text |
| `provenance/MODEL_REQUEST_PROTOCOLS.json` | Recorded model and request protocol |
| `responses/` | Normalized candidate JSONL files |
| `admit.py`, `rescore.py`, `smoke_test.py` | Supported offline commands |
| `vendor/scripts/` | Archival implementation dependencies and policy source |
| `docs/REPRODUCE.md` | Input format, commands and result interpretation |
| `docs/MODEL_ADAPTER_INTERFACE.md` | Reserved model-runner interface and implementation work |

Historical module names are retained because the loader depends on them. Use the top-level offline commands. The additional policy source records the original algorithm; its research-workspace CLI has not been made portable. Policy and portfolio outputs can already be rescored.

## Protocol and distribution

The archived prompts omit some numerical objective coefficients and contain time-field ambiguities documented in `docs/SCIENTIFIC_SCOPE.md`. New runs with clarified instructions need their own protocol version. Historical requests and scores remain unchanged.

Reference answers are included for reproduction. This is a static published-answer suite. A hidden-test service is a separate project.

Code/data licensing and author citation metadata are pending; see `LICENSES/README.md`. This is a local release candidate, not a statement that a GitHub release or license has already been issued.
