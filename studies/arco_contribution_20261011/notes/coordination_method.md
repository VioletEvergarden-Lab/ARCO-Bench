# Direct coordination queries and development findings

## Query meaning and implementation

`coordination_solver.py` is a direct MIP baseline over the unchanged finite public option model. It is not a new optimization algorithm. The task, reference vector and comparison origin are explicit inputs. The usual origin is stored G; the original incumbent is a different origin and may itself be infeasible after the disruption.

For each mission m, the original option/hold variables select exactly one decision. Let x_match(m) denote the option identical to the origin. Introduce binary y_m with y_m + x_match(m) = 1; if the origin decision is absent from the disrupted public options, fix y_m = 1. For each UAV u, introduce binary z_u with y_m <= z_u for every mission on u, and z_u <= sum(y_m on u). Consequently sum(y_m) is the exact number of changed complete mission decisions and sum(z_u) is the exact number of affected chains. These distances do not replace the incumbent-relative L3 objective.

The direct queries minimize either sum(y_m), sum(z_u), or zero for feasibility. An allowed support S fixes z_u=0 outside S. Optional task and chain budgets bound their respective sums. An optional no-good support excludes one exact support pattern; this supports alternative-set checks without confusing minimum-cardinality and inclusion-minimal sets.

`target_mode='match'` enforces each requested prefix component within its established quality tolerance of the supplied reference. `target_mode='ceiling'` instead imposes separate upper aspiration bounds. The latter is **not** lexicographic no-worse comparison. For equality queries the fixed L2 hold contribution can be removed from L3 for numerical conditioning; this transformation is not used for the ceiling mode, where L2 can vary. Core uses its archived public-domain builder and evaluator, including the six-decimal energy rounding cells; network queries use the continuous event engine. Held decisions have their canonical null fields.

Every proposed witness is reconstructed and evaluated by the original independent verifier, then rechecked for the target, support, budgets and actual distance. The output separates a verified upper witness, the integer-rounded MIP dual lower bound, proved infeasibility and unknown status. Absence of a returned plan is never a proof of infeasibility. If the origin is outside the target set, distance zero is impossible; this elementary lower bound closes a supplied one-change or one-chain witness without another solve. A zero budget with no usable witness remains unknown.

The mathematical target can be queried for any prefix 1–6; E1 primarily uses 2 and 6, with prefix 3 or 4 where needed to identify the transition. Reference optimality and target provenance come from the supplied research records rather than being re-proved by the coordination query.

## Interface and cost accounting

```python
from coordination_solver import CoordinationProblem
p = CoordinationProblem(task, origin_decisions, origin_name='G')
p.prepare()  # optional: share one built finite model across queries
r = p.solve(reference_objective, target_prefix=6,
            minimize='missions', allowed_uavs=None,
            task_budget=None, chain_budget=None, seconds=60,
            witness=reference_decisions, target_mode='match')
```

`solve_coordination(...)` provides a one-query wrapper. `CoordinationProblem` caches the finite model for repeated queries on the same task and origin. A new resource intervention or origin needs a new object. Preparation, per-query construction, solver and independent-validation times are retained; the wrapper includes construction in total elapsed time. Lazy first-query preparation is charged to that query. HiGHS uses one thread, zero MIP relative/absolute gaps and the established numerical feasibility tolerance. Solver limits are not treated as exact end-to-end deadlines: the actual elapsed time and `completed_within_budget` are saved. Research timings with concurrent local work are not exclusive-machine speed comparisons.

## Development results

| Task | T2: minimum tasks / chains | T3 | T6: minimum tasks / chains |
|---|---:|---:|---:|
| M01-B | 4 / 1 | 4 / 1 | 5 / 2 |
| L02-B | mission query unresolved; chain minimum 1 | — | 4 / 1 |
| L02-C | unresolved in the short development budget | — | 9 / 7 |
| Core-034 | 0 / 0 | — | 4 / 2 |

M01-B's only minimum-cardinality two-chain quality support is {U01,U02}: a T6 feasibility query with chain budget two and that exact support excluded is infeasible. That alternative-support query alone would not establish necessity in larger supports. The later unrestricted complement queries in `analysis/e1_support_identity.json` also exclude omitting U01 and omitting U02, proving that both must change in every quality repair. Opening only U02 permits T2 and T3 but excludes T4 and T6, identifying L4 as the first target upgrade that needs a larger scope. A task budget of four also excludes T6.

The L02-C chain optimum of seven is new relative to the prior [2,7] chain bound. Both its task minimum nine and chain minimum seven were proved by direct target queries in about 29 seconds each. L02-B's quality queries took about three seconds. The two L02 service mission queries retained incomplete bounds after nominal 45-second limits; their unknown states were kept. Twenty-four development query records total 342.41 seconds of per-query elapsed time; this is a sum of query durations, not a measured exclusive batch speed. Core-034's nonzero optimization queries took approximately 0.030 and 0.011 seconds.

Additional bounded checks confirm that Core-034 T6 is infeasible with an empty support or three-task budget, that an unseeded zero-budget query is unknown, and that an invalid-after-disruption incumbent is still accepted as a distance origin. See `runs/development/support_checks.json`. All returned MIP witnesses in the development records passed the independent verifier and target checks. Details and costs are in `analysis/solver_development.json` and `.csv`.

## Joint budgets and candidate procedure

The marginal minima need not be attained together. For S02-C, origin G and target T2, the mission minimum is 2 and the chain minimum is 1. A direct feasibility query excludes the joint budget (2,1). Independently verified plans attain (2,2) and (3,1). Because the budgets are integers with lower bounds k>=2 and c>=1, those two witnesses and that exclusion establish the complete nondominated budget frontier. No general enumeration of every instance's frontier is needed to establish this counterexample. The other 119 condition/target combinations comprise 114 joint-minimum witnesses and 5 with unresolved marginal bounds.

For each complete candidate missing target j, the diagnostic procedure is:

```text
S := UAV chains changed by candidate relative to the declared origin b
k := number of candidate mission changes relative to b
query target j with all chains outside S fixed to b
if proved infeasible: classify support insufficient
if feasible: query the same support with mission budget k
    if proved infeasible: classify support sufficient, budget insufficient
    if feasible: retain a target witness within the same support and budget
preserve unknown if a required query has neither witness nor exclusion
```

Successful candidates provide controls, and unavailable decisions stay in the original population with no action-level diagnosis. A witness for a stronger prefix remains a witness for a weaker prefix under containing support and larger budgets. A proved exclusion for a weaker prefix remains an exclusion under a stronger prefix, contained support and smaller budgets. Reuse is confined to the same task, origin and target vector. `query_reuse.py` implements these standard implications; both computation variants receive the same initial stored plans.

## Local reproduction

The interface above illustrates the API, not a standalone input example. From the workspace parent, run `D:\Code\python.exe arco_contribution_20261011/scripts/reproduce.py --check` to replay saved witnesses and check query coverage. `README.md` gives batch commands, limits, and the separate resume option. Dependencies are NumPy, SciPy and HiGHS (the local backend first loads `arco_closing_study/.solver_deps`), together with the existing benchmark source and archived data folders listed in that README. This research folder extends those local inputs rather than duplicating the entire benchmark.

## Actual local-search neighborhoods

`local_neighborhood_diagnostics.py` screens all 60 network conditions and selects the 40 saved reference-quality misses from R4, Iter-R4 and R_frac. For each it reads the actual last neighborhood center and radius. It first looks for an independently verified quality witness inside that neighborhood, then uses an applicable certified prefix through L4, and only reuses G-relative E1 lower bounds when the saved center equals G decision by decision. Remaining cases receive a target-feasibility query at the actual center and radius. The output retains the old run status separately from later diagnostic knowledge. Conclusions concern that final neighborhood, not all earlier centers or every potential future Iter-R4 trajectory.

The completed classification is 36 proved scope exclusions and 4 within-neighborhood quality witnesses, with no unknown cases. By method, R4 has 16 exclusions and 2 witnesses, Iter-R4 has 8 and 2, and R_frac has 12 and 0. The four scope-sufficient misses are L02-B and L04-B for both R4 and Iter-R4. Only two new feasibility solves were needed: the final Iter-R4 neighborhoods of L01-C and L02-C were proved infeasible in 46.177 and 1.649 seconds, respectively (47.825 seconds combined). Their centers differ from G; these are new exclusions at the actual stored centers.

Reproduction: `D:\Code\python.exe arco_contribution_20261011/scripts/local_neighborhood_diagnostics.py --solve --seconds 60`. Completed direct-query records are resumed without another solve. Omitting `--solve` performs only evidence reuse. Results: `analysis/e2_actual_neighborhoods.json` and `.csv`.

## Fixed lexicographic targets under resource intervention

`derive_e3_fixed_lex.py` independently replays stored E3 witnesses and compares them to the original reference with the original lexicographic comparator. All seven E3 original targets have zero urgent and total holds, so every lexicographically no-worse plan must attain that service prefix. Stored T2 distance lower bounds therefore apply. Matching verified witness upper bounds close every G-origin case without new optimization: M01-B (4,1), regions-L01-long (5,1), and the remaining five cases (0,0).

For M01-B after V11 gains one charging position, the separate old aspiration box requires (5,2), while the old lexicographic threshold and the new reference quality each require (4,1). The new plan improves L3 and L4 but increases L5 from 112 to 114, explaining why the box and lexicographic questions differ. For regions-L01-long, the fixed old lexicographic threshold remains (5,1), whereas the newly improved reference requires (9,2).

`analysis/e3_fixed_lex_bounds.json` contains witnesses and bound sources. `e3_origin_witness_comparison.json` records each saved plan's actual distance to G and the original incumbent. Incumbent-origin witness distances are not presented as optimized minima: only independently justified lower bounds and verified upper bounds are reported. This keeps resource effects, target changes and origin changes distinct.
