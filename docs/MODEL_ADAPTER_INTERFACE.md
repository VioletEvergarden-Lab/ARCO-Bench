# Reserved new-model interface

**Implementation status: specification, not a shipped live runner.** The package currently supports offline scoring of stored answers. No command here reads API credentials or calls a model. This distinction prevents the research-only 216-attempt runner from being mistaken for a portable arbitrary-model tool.

## Proposed user-facing files

| GitHub path | Responsibility | Status |
|---|---|---|
| `credentials/provider.env.example` | Non-secret template | Included |
| `credentials/provider.env` | Local key and base URL | User-created; gitignored |
| `configs/model_run.example.json` | Visible protocol/interface configuration | Included as specification |
| `run_model.py` | Serial 72-task orchestration, preparation, explicit execution and safe resume | To implement |
| `adapters/base.py` | Common request/response/terminal contract | To implement |
| `adapters/chat_completions.py` | Nonstream JSON and SSE response handling | To implement |
| `adapters/responses.py` | Background response ID, terminal status and same-ID polling | To implement |
| `adapters/mock.py` | Offline deterministic transport fixtures | To implement |
| `tests/test_runner_offline.py` | Failure, resume, denominator and credential-redaction tests | To implement |

The adapters can be implemented with Python's HTTP facilities or an explicitly pinned SDK with implicit retries disabled. The original three-model wrapper at `scripts/run_integrated_repair_candidate_a_v12p1_core72_standardized_128k_main_v1.py` in the research workspace is **not** an acceptable drop-in: it imports the Challenge-12 runner, binds a 216-attempt registry and requires the historical phase directory.

## Credentials

Copy `credentials/provider.env.example` to `credentials/provider.env`, and edit that local copy. Use a separate file per provider if needed. Keep only key/base URL in this file; model ID and generation parameters belong in a versioned non-secret configuration. The runner must not log Authorization headers, credential text or unsanitized exception objects.

## Input boundary

`public task + protocol-specific exact prompt/request + explicit run configuration → one candidate and terminal metadata`.

For archival-interface extensions, pick one of the three historical request profiles explicitly. Do not silently map Qwen SSE, DeepSeek JSON and Luna Responses parameters into one universal request. `provenance/requests/` is the source for request bodies; `MODEL_REQUEST_PROTOCOLS.json` describes the original transports. Newly added or omitted fields create a protocol change that must be recorded. The sample configuration illustrates the historical DeepSeek Chat profile and is not a parameter recommendation for every provider.

## Required execution behavior

1. Default command prepares requests without network access. Live generation requires an explicit execution flag.
2. Freeze ordered IDs from `data/CORE_72.json`, exact request bodies, endpoint/model/configuration, and one attempt per task before generation.
3. Save an intent/attempt marker before POST. Serial concurrency one; no quality retry, JSON repair, tools or scorer feedback.
4. After an uncertain accepted POST, do not send another POST. A durable Responses ID permits querying the same response. Save raw bytes and terminal metadata; leave uncertainty visible.
5. Validate endpoint rejection/unsupported parameters without silently changing the request. Connection or provider failures occupy their formal task rows.
6. Complete exactly 72 normalized rows, including empty text for unusable answers. Resume uses durable task state and never infers a missing response file means a request was not sent.
7. Store usage, returned model ID/fingerprint, finish reason, HTTP status, POST/terminal time and protocol ID. Cost needs a separately recorded price snapshot.

## Output layout

```text
runs/<run_id>/
  run_config.public.json
  request_registry.jsonl
  requests/<record_id>.json
  attempts/<record_id>/intent.json
  attempts/<record_id>/provider_response.json
  attempts/<record_id>/transport.bin
  attempts/<record_id>/terminal.json
  responses.jsonl
  run_summary.json
  admission.jsonl
  scores/SUMMARY.json
  scores/SCORED_RECORDS.jsonl
```

This output layout is reserved. Current, working post-generation commands are in `docs/REPRODUCE.md`. No `run_model.py` command is advertised as executable until implementation and offline mock tests pass.

## Minimum implementation acceptance

Test JSON, SSE and background-terminal parsing; empty output, truncation, malformed JSON, HTTP rejection and ambiguous POST; restart after intent but before response save; same-ID polling; exactly-once task binding and 72-row output. Test that generation never accesses reference records. Tests must use mock transport and no real credentials. Live compatibility with a chosen current provider remains a separately authorized check.

## Protocol choice before public new-model testing

The archival route can preserve current scores and old inputs immediately. A clarified-contract route needs an approved prompt/domain definition before new comparable scores can be offered. Reserve versioned interfaces now; do not supply a new full-contract prompt while calling it the historical experiment.
