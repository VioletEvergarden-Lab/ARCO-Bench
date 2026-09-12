# ARCO-Bench: archival scope and contract reconciliation

Updated 12 September 2026. This document supplements the preserved archival release. It changes no task, original request, provider response, reference vector, scorer, policy or selector.

## What this repository currently supports

The repository reproduces the original-request Core-72 panel: DeepSeek V4-Pro (11 August 2026 UTC) 28/72, Qwen 3.7-Plus 34/72, GPT-5.6 Luna 48/72, policy 38/72 and the three stored pairwise selections 52/72, 50/72 and 63/72. These are historical combined-strict counts. Reference quality and construct fidelity remain separate fields.

Use the existing offline commands:

```sh
python -B smoke_test.py
python -B rescore.py --responses responses/luna.jsonl --output local_results/luna
python -B admit.py --responses responses/luna.jsonl --output local_results/luna_admission.jsonl
```

These commands need no API key. The existing validation JSON and release file list describe the archival build. This documentation update is not a new scientific dataset release or a rerun of those validations. The GitHub package currently reserves the network-adapter interface; a local experimental runner elsewhere in the research workspace is not automatically part of this repository.

## Three evaluation judgments

| Judgment | Required information | Role |
|---|---|---|
| Admissibility | Submitted decisions, public state, schema and formal constraints | Public candidate screening |
| Reference quality | Admissibility and the offline optimized vector | Exact L1–L5; L6 within 0.0001 kWh |
| Construct fidelity | Candidate and private construction annotations | Additional construct diagnostic |

“Public” describes the constraints and objective definition. It does not make oracle equality available without a reference. Private construction annotations were withheld during generation and selection; they are included in this archival distribution for reproduction.

## Findings that matter for a new experiment

1. **Instruction completeness.** All 216 original primary requests omit the L3 numeric formula and L4 urgent weight. The policy and comparator obtained these coefficients from code. The original counts measure alignment under those instructions; they are not a full-information policy–model comparison.
2. **Time domains.** The oracle uses a common latest-departure cutoff that reserves the maximum charging duration before actual charge choice. The public verifier bounds departure without a terminal-completion row. A local expanded-domain check preserved all 72 reference vectors and the archived admissible candidates lie in the original reference domain. The general domain mismatch still requires a versioned correction.
3. **Time metadata.** Some unrounded minute fields were construction search values and imply physically implausible speeds. Scheduled durations use segment-wise wind adjustment and rounding. A slot-preserving metadata prototype is not physical calibration.
4. **Energy representation.** The archived formula uses total distance and arithmetic mean segment wind. A segment-additive formulation avoids arbitrary subdivision effects. The 21 multi-segment service-path occurrences checked in Core-72 have equal arithmetic and distance-weighted wind, so this observation alone does not establish an erroneous historical score.
5. **Selection tolerance.** Exact lexicographic comparison has a reference-quality union property under a common domain/objective. The implemented final-tier epsilon tie additionally needs no tie crossing the reference acceptance boundary. Every historical tied pair has identical computed energy. Private construct fidelity is separate from that property.

## Reconciled-contract specification — not yet an executable release

Each future generation request must directly contain the following, together with the task JSON and output schema. A link to code is insufficient input to a no-tools model.

- Fixed assignment, service order, UAV type and incoming route; permitted suffix hold, service path, departure and post-service charge decisions.
- Slot length 5 minutes, turnaround 1 slot, charge blocks 0–3, hard releases and soft due times.
- For an actual path p and charge c: release <= departure < H and departure + travel_slots(p,u) + turnaround + c <= H. Enumerate these actual choices without reserving maximum charge for every option.
- Incoming flight, service flight, reserve check, turnaround and post-service charging event order. Charging ends before the next movement. Waiting/turnaround energy is zero in this model.
- Corridor occupancy, separate departure/arrival pad events, charger intervals, compatibility, initial SOC, reserve and battery capacity.
- Full lexicographic objective, all minimized:
  - L1: urgent missions held.
  - L2: total missions held.
  - L3: 1000 * holds + sum over served missions of [20 * path_change + absolute_departure_shift_slots + 10 * charge_activation_change + 2 * absolute_charge_block_change].
  - L4: 5 * sum(priority_weight * max(0, arrival_slot - due_slot)), urgent weight 10 and routine weight 1.
  - L5: 5 * sum(max(0, departure_slot - effective_release_slot) + charge_blocks).
  - L6: total flight energy in kWh, evaluated last.
- A declared time/energy parameter model, units and numerical tolerances shared by the generator-facing description, oracle and verifier.
- No reference plan/vector, competitor, private mechanism metadata or score feedback in candidate generation or public selection.

These coefficients describe a research preference contract, not an operator-calibrated universal utility. L5 is departure-after-release plus charging, not measured ground idle or fleet completion.

The revised energy candidate is a sum over physical segments:

`sum(distance_e * (empty_rate_u + payload * payload_rate_u) * (1 + wind_factor_u * wind_e))`.

Joint distance/time/energy/charging calibration and common-domain implementation must precede a new complete-contract panel. A new protocol or task version must preserve a mapping to the archive and record any changed task/reference. Existing historical requests must not be overwritten or relabelled as full-contract runs.

## Small illustrative checks

```sh
python -B check_v4_contract_examples.py
```

This standard-library-only script checks the horizon counterexample, numerical objective examples, SOC event arithmetic, segment subdivision and the epsilon-selection boundary. It makes no API calls and imports no archived runtime. Its success validates these small examples, not a corrected Core-72 release.

## Pending research and distribution decisions

- Complete-instruction generation after common-domain and parameter reconciliation; endpoint and repeat budget to be agreed before execution.
- One low-cost rule–rule comparison if a claim about source-specific generative added value is retained.
- New structural contrasts if results are to support breadth beyond the current construction recipes.
- Separate code/data licenses, citation metadata and review access. Repository visibility remains unchanged.

The manuscript revision is a writing version. It does not create new Core-72 outcomes or change the scientific status of the archival release.
