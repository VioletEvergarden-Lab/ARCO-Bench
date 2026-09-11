# ARCO-Bench Candidate A V12P1 — offline archival release candidate

ARCO denotes **Aerial Recovery and Coordination**.

This self-contained directory reproduces the TRC V2.1 candidate results. It evaluates disrupted UAV logistics plans under fixed assignment, service order, vehicle type and incoming route. A repair jointly selects service paths, departures, mission holds and post-service charging.

## Quick start

Tested with Python 3.12.4, NumPy 1.26.4 and SciPy 1.13.1. Install the pinned dependencies in your chosen environment if needed, then run:

```text
python -m pip install -r requirements.txt
python smoke_test.py
python admit.py --responses responses/luna.jsonl --output local_results/luna_admission.jsonl
python rescore.py --responses responses/luna.jsonl --output local_results/luna
python smoke_test.py --all --output OFFLINE_VALIDATION_RESULTS.json
```

The smoke test uses an existing reference-quality case and a malformed-JSON negative fixture. The full run compares seven groups × 72 records with the archived scores, including objective vectors and first differences. It also matches public-only admission and objective computation with the archival scorer. Network connections are disabled by these entry points.

Expected reference-quality counts: DeepSeek V4-Pro (11 August 2026 UTC) 28; Qwen 34; Luna 48; policy 38; policy+DeepSeek 52; policy+Qwen 50; policy+Luna 63. See `OFFLINE_VALIDATION_RESULTS.json` for the completed 504-record comparison.

## Two usable entry points

`admit.py` reads only public task records and candidate text. It returns schema/formal status and the candidate objective vector. It does not load references or constructor metadata.

`rescore.py` invokes the unchanged archival scorer and uses evaluator records for offline reference comparison and construct diagnostics. It adds reporting aliases `online_admissible`, `reference_quality` and `construct_fidelity`, retaining historical scorer fields. Reference quality requires admission, exact L1–L5 equality and L6 within 1e-4 kWh of the reference.

Here private means withheld during candidate generation. Both public and private records are included for archival reproduction. Once distributed with answers, this snapshot is a static reproduction suite.

## Artifact flow

| Stage | Location | Role |
|---|---|---|
| Task | `data/public/records/` | 72 complete public operating states |
| Prompt and request | `provenance/requests/` | All exact primary requests and prompt text |
| Provider output | `provenance/raw_provider_responses/`, `provenance/raw_transport/` | Terminal JSON, original transport bytes, final text and binding |
| Candidate text | `responses/*.jsonl` | One record_id and raw_text per line |
| Public admission | `admit.py` | Schema, formal feasibility and L1–L6 |
| Reference evaluation | `rescore.py`, `data/private/evaluator_records/` | Reference quality, construct fidelity, historical scores |
| Original results | `results/original/*.jsonl` | Record-level reproduction targets |

To score your own stored answers, provide JSONL records containing a known `record_id` and string `raw_text`. The raw text must contain the candidate JSON object. The response has exactly `record_id` and `decisions`; each decision has `mission_id`, `uav_id`, `held`, `path_id`, `depart_slot`, `charge_blocks`. `schema/output.schema.json` documents static syntax; the unchanged parser checks instance-specific IDs, ranges and coverage. No answer repair is performed.

## Endpoint provenance

The original panel uses one POST per task, concurrency one, a 128000-token output cap, no tools or scoring feedback and no quality retry.

| Model identity | Execution interval UTC | Interface and explicit parameters |
|---|---|---|
| `deepseek-v4-pro`, DeepSeek service | 2026-08-11 08:15:17–12:24:29 | Chat Completions, nonstream; temperature 0; thinking/effort omitted |
| `qwen3.7-plus`, Qwen adapter | 2026-08-11 12:24:29–17:00:54 | Chat Completions SSE with usage; temperature 0; thinking/effort omitted |
| `gpt-5.6-luna`, OpenAI service | 2026-08-11 17:00:54–2026-08-12 01:33:22 | Responses background polling; reasoning effort max, mode standard, context current_turn; store false, stream false, tools []; temperature omitted |

The earlier DeepSeek realization is identified by alias and date; no unverified snapshot suffix is assigned. Request JSON records explicit fields. Provider defaults and deterministic execution are not inferred from an omitted field or temperature zero.

The original HTTP transport uses Python urllib with zero SDK retries. Chat timeout is 7200 s. Luna POST timeout is 120 s, GET timeout 60 s, polling interval 10 s and polling window 14400 s. A durable response ID permits same-response GET recovery. Exact fields and response model IDs are in `provenance/MODEL_REQUEST_PROTOCOLS.json` and `FORMAL_RESPONSE_REGISTRY.jsonl`.

The connection base was supplied externally. The DeepSeek retest confirms `https://api.deepseek.com`; the Luna runner enforces `https://api.openai.com/v1`. The historical Qwen connection origin is absent from the archived request bodies, so the current mutable environment is not used to reconstruct it.

## Dependencies and archival modules

`vendor/scripts/` contains eleven byte-preserved modules required by the current scorer and selector. Historical filenames and internal flags remain unchanged to preserve imports and semantics. Users need only the top-level commands. The loader imports constructor-era functions used for mechanism checks; the documented commands do not execute construction or optimize new references. The optional oracle code uses `scipy.optimize.milp` with SciPy's bundled HiGHS.

`provenance/OFFLINE_REPLAY_ENVIRONMENT.json` describes the current replay environment, not historical experiment hardware. The model-generation runner and credential loaders are not exposed as runnable commands. Exact request files document the adapter contract for separately authorized future tests.

## Distribution status

This is a tested local release candidate. Code and task/result data may require different licenses; author selection is pending. Citation metadata, permanent URL and reuse terms must be completed before public distribution. No historical project files were moved or deleted.
