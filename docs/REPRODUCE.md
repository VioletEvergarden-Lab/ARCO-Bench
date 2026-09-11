# Offline reproduction

All commands below exist in this package and make no model calls. Run them from the repository root after installing `requirements.txt`.

## 1. Quick smoke test

```sh
python -B smoke_test.py
```

Expected: `status: PASS`, a valid policy answer for CA12_CORE_012 and rejection of a malformed JSON answer. The default check is a two-fixture smoke test; it is not the full 504-record replay.

## 2. Score one complete candidate set

```sh
python -B rescore.py --responses responses/luna.jsonl --output local_results/luna
python -B admit.py --responses responses/luna.jsonl --output local_results/luna_admission.jsonl
```

- `local_results/luna/SUMMARY.json`: record count, schema validity, admissibility, reference quality, construct fidelity and historical strict count.
- `local_results/luna/SCORED_RECORDS.jsonl`: per-task objectives, failure attribution and evaluator fields.
- `local_results/luna_admission.jsonl`: public-only admission/objective computation.

`admit.py --output` is a FILE; `rescore.py --output` is a DIRECTORY.

## 3. Optional full archival replay

After step 2 creates `local_results/`:

```sh
python -B smoke_test.py --all --output local_results/FULL_REPLAY.json
```

Expected: 504 records across seven sets; historical field-by-field agreement and public-admission/objective agreement. The shipped root `OFFLINE_VALIDATION_RESULTS.json` is the earlier completed validation record. Write new validation output under `local_results/` to preserve it.

## 4. Bring your own answers

Use UTF-8 JSONL, one line per task:

```json
{"record_id":"CA12_CORE_001","raw_text":"{\"record_id\":\"CA12_CORE_001\",\"decisions\":[...]}"}
```

The ellipsis illustrates a structure; replace it with complete decisions. Each decision contains `mission_id`, `uav_id`, `held`, `path_id`, `depart_slot`, and `charge_blocks`. Existing `responses/*.jsonl` are complete working examples.

```sh
python -B rescore.py --responses runs/my_run/responses.jsonl --output runs/my_run/scores
python -B admit.py --responses runs/my_run/responses.jsonl --output runs/my_run/admission.jsonl
```

The scorer evaluates the rows supplied. **It does not fill missing task IDs or enforce the full-run denominator.** A formal Core-72 result must supply every ID from `data/CORE_72.json` once, including `raw_text: ""` for a generation failure with no usable answer. Keep provider failure/status details in sidecars. Report `records=72`; a subset is a subset result.

There is no JSON repair, continuation or reference-guided answer modification in these commands. Generation is separate from evaluation.
