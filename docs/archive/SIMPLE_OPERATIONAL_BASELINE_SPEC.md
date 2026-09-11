# Deterministic resource-aware operational repair baseline

Status frozen on 2026-08-14, before the one-shot Core-72 run. Implementation: `scripts/run_candidate_a_v12p1_resource_aware_greedy_baseline_v1.py`.

## Scientific role

The baseline estimates what a small, transparent scheduling policy can do after a disruption when it knows the published operating state and the same action boundary as the language models. It is an operational comparator between no repair and model-generated repair, not a proposed optimization algorithm and not an ablation of the language models.

Evidence gradient:

`no repair -> deterministic resource-aware operational policy -> language-model-generated repair -> lexicographic MILP oracle`

This comparator is distinct from the existing controls. The cue-only control probes construction shortcuts; the sequential local greedy deliberately ignores SOC, charging and shared resources; the resource-oblivious control relaxes shared capacity; and the verifier-guided control receives rejection information. The present policy explicitly maintains all registered resource and energy states and receives no verifier feedback.

## Information and action boundary

The generator reads only the frozen public `CORE_72.json` index and its 72 public records. It may use the published baseline plan, instance, intervention, fleet parameters, paths, time windows, SOC state and resource capacities. It may not read private evaluator records, oracle or competitor plans, mechanism labels, model outputs, scorer results or per-record outcomes.

Assignment, per-UAV service order and incoming deadhead paths remain fixed. The policy can select only the actions permitted to the evaluated models: suffix hold, service path, departure slot and post-service charge blocks. It emits the exact public response schema.

## Policy

1. Maintain a clock and SOC ledger for every UAV, plus discrete corridor, pad and charger calendars.
2. At each serial-schedule step, expose only the next mission in each UAV's fixed chain. Select a chain by a fixed key: more urgent missions remaining in its suffix first, then effective release, baseline departure, UAV ID, sequence index and mission ID.
3. Enumerate all public-kernel route, departure and charging options. Reject an option if it violates fixed chronology, corridor closure/capacity, pad capacity, charger capacity, SOC reserve or battery capacity.
4. For every feasible current option, perform one bounded check: after tentatively applying it, determine whether at least one feasible option exists for the immediate next mission on the same UAV. This is an existence check, not optimization and not verifier feedback.
5. Rank candidates by: next-mission serviceability; exact local L3 plan-change burden; L4 priority-weighted tardiness; L5 delay-plus-charge wait; L6 service-plus-deadhead energy; and deterministic departure/path/charge identifiers.
6. Commit the first candidate and update all ledgers. If no option is feasible, hold the current mission and the rest of that UAV's fixed suffix.

The policy never voluntarily holds a mission for a lower-tier improvement when a feasible option exists. It never invokes a solver or formal verifier during construction.

## Budget, tie-breaking and execution discipline

- Deterministic, single-threaded, no random seed required.
- Finite full enumeration of registered options and at most one same-UAV mission lookahead.
- One official generation per Core-72 record after source and registry hashes are frozen.
- No rule edits, outcome-conditioned tuning or reruns after Core-72 results are visible.
- A pre-run self-test is limited to deterministic execution and response completeness on one public record; it does not inspect a Core-72 score.
- Construction runtime, candidates considered, action trace and terminal state are retained per record.

## Evaluation

The response file is passed unchanged to the frozen Candidate A parser, formal evaluator, mechanism-semantic check and L1-L6 scorer. A separately implemented offline replay reconstructs the public-to-internal mapping and formal/objective conclusions from the response file. The formal denominator remains 72; failures are retained.

Primary descriptive outputs are schema validity, formal feasibility, required semantics, strict success, mutually exclusive first failure, operational L1-L6 components, fallback workload and runtime. Comparisons with no repair, the frozen three-model matrix and the MILP oracle retain their different scientific roles; this is not a single algorithm leaderboard.

## Interpretation boundary

The baseline can support a claim that explicit resource ledgers improve the operational relevance of a simple policy comparator and quantify the remaining gap to solver-certified repair. Its result cannot establish state-of-the-art heuristic performance, LLM superiority over optimized OR algorithms, deployment readiness, or the value of verifier feedback. The one-step policy is intentionally myopic and may make globally poor resource reservations.
