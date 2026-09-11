# Verifier-gated two-source portfolio selector

Status: frozen on 2026-08-14 before the formal offline Core-72 composition run.

## Scientific role

The selector is a post-freeze secondary system-composition analysis. It tests whether already generated candidates from a deterministic operational policy and one language model can be composed into an executable decision-intelligence pipeline without oracle access. It is not a new model, training method, heuristic family or replacement for the standardized three-model primary matrix.

The three formal portfolios are:

1. resource-aware sequential greedy + old DeepSeek V4-Pro endpoint;
2. resource-aware sequential greedy + Qwen 3.7-Plus;
3. resource-aware sequential greedy + GPT-5.6 Luna.

No candidate is regenerated, repaired, continued, spliced or quality-retried.

## Operationally implementable admission boundary

For each source candidate, the selector performs the frozen public schema check and then the independent formal evaluator on the public task state. A candidate is admitted only when it is parse/schema valid and formally feasible. For every admitted candidate, the evaluator computes the same six-component objective vector used by the frozen scorer:

`(urgent holds, total holds, repair distance, priority-weighted tardiness, departure-and-charging recovery time, service-plus-incoming-deadhead energy)`.

The current `required mechanism semantics` check is not an operational admission gate. Its registered implementation requires the private `selected_pair` and mechanism metadata deliberately excluded from the public task. Using it during selection would leak evaluator-only information. Mechanism semantics is therefore computed only after selection as an offline diagnostic, alongside oracle equivalence and strict success. This distinction must remain explicit in the manuscript.

## Fixed selection rule

1. If neither candidate is admitted, return a canonical selector failure with no synthesized repair.
2. If exactly one candidate is admitted, select it.
3. If both candidates are admitted, compare their public objective vectors lexicographically in the frozen L1-L6 order.
4. L1-L5 use exact registered numeric equality. L6 values within the scorer's `1e-4 kWh` equality tolerance are treated as tied.
5. Select the lexicographically smaller vector.
6. If the vectors are tied through L6, select the resource-aware policy candidate.

The policy-first tie-break is fixed for every task and model. It favors the deterministic, low-computation and directly explainable source when the registered operational outcome is indistinguishable. It is not conditioned on record identity, model identity, historical outcome or score.

## Forbidden information

The selector must not read or infer:

- oracle target or competitor decisions;
- oracle objective vectors or strict-success labels;
- private evaluator records, mechanism labels or selected-pair certificates;
- model historical scores, first-failure labels or per-record outcome tables;
- other model candidates outside the named two-source portfolio.

The generator and model response files remain immutable inputs. Oracle, private semantics and strict success are used only in the final offline evaluation of the selector output.

## Outputs and interpretation

Each portfolio records both candidates' schema/formal status and public objective vector, admission state, selection reason, selected source, tie flag and local selector runtime. The selected raw candidate is written unchanged to a new response file and re-evaluated by the frozen scorer and an independent offline replay.

The primary selector questions are formal robustness, mechanism-semantic retention, strict success, cumulative L1-L6 equality, source selection share and net gain over each constituent. The already observed set unions are diagnostic upper bounds until reproduced by actual selector outputs.

Any gain supports a narrow system claim: rule-based and generative candidate sources can be composed behind a common public verifier. It does not support a new model-capability claim, autonomous dispatch, expected pass probability, causal AI-versus-OR superiority, or a cost-optimal production ensemble.



## V2.1 analytical clarification — 2026-09-05

The frozen comparison rule above is unchanged. “Reference quality” means an offline reference comparison, not an online admission test. Exact lexicographic selection preserves the reference-quality union of its given candidate set. The implemented L6 tolerance needs an additional condition: no tolerance tie may straddle reference acceptance. All 216 recorded pairs meet this condition, with identical computed energy in every tie. A numerical counterexample to the unconditional tolerance claim is in V2.1 Appendix B. Private construct fidelity has no general union guarantee. See `TRC_V2P1_SCIENTIFIC_RECONCILIATION_NOTE.md` for the supporting derivation.

