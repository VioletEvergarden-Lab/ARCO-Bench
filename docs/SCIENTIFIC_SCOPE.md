# Scientific scope of the archival release

## Stable reporting terms

- **Online admissibility:** parsable/schema-valid candidate satisfying the public formal model. The public evaluator can compute its L1–L6 vector.
- **Offline reference quality:** admissibility plus reference equality at L1–L5 and the scorer's 1e-4 kWh L6 tolerance. Equality requires the reference; it is not a public-only admission test.
- **Construct fidelity:** the historical required-mechanism diagnostic uses evaluator metadata withheld during candidate generation.
- **Historical strict success:** retained, unchanged, for reproducing past reports. It includes construct fidelity as well as reference-quality gates.

## Archived input contract

The V3 investigation found that all 216 original primary requests omitted numerical L3 action coefficients and the L4 urgent weight of 10. Policy/selector code has those values. Time-valued metadata also requires distinguishing discrete slot calculations from minute-valued fields. Some synthetic minute fields imply implausible physical speeds. The oracle's option domain and public verifier's terminal-horizon domain are not identical; the V3 expanded-domain check left the 72 reference vectors unchanged.

This release preserves the inputs and evaluation that produced the reported results. An archival-interface extension must use those exact inputs and be labelled accordingly. A clarified-contract experiment should version its prompt, time-field convention and domain contract, save separate outputs, and describe changes. That experiment has not been produced by this packaging work.

## Selection and evidence roles

The selector uses public admission and L1–L6 comparison and returns an existing candidate. Private construct metadata and reference vectors are absent from selection. Exact lexicographic minimization preserves a globally optimal objective if an admitted candidate has that objective. The archived implementation uses an L6 tolerance and policy-first ties; boundary-crossing conditions matter for tolerance-based reference equality. Core-72's verified pairwise reference-quality coverage is 52/50/63. Historical combined strict counts are empirical outcomes, because construct fidelity is a separate diagnostic.

The seven-group replay covers the primary model panel, operational policy and secondary pairwise selection. Flash-0731 and Pro-0813 are separate supplements; Pro-0813 is a temporal endpoint retest. MILP references and policy/selector computation do not establish a hosted-model speed advantage.

## Meaning of private

`data/private/` denotes information withheld at generation, not information promised to remain secret after release. Publishing the reference records enables static reproduction. Live model adapters must read public records/request templates only and never import the scorer or evaluator records while generating.

## Provenance of these scope updates

These statements follow the project's V3/V3.1 research decisions and analyses. The optional `paper_evidence/v3_figure_data/` files are ready plotting inputs. Archival specifications in `docs/archive/` preserve prior wording; this page supplies the current interpretation. The release does not claim that those plotting inputs alone are a standalone rebuild of the entire research history.
