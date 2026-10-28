# Online deterministic comparison, frozen 2026-10-03

The public task JSON becomes available at time zero. Every method times its own
file read, parsing, event-engine creation, public-option enumeration, greedy
repair, model construction, solving, candidate extraction and validation.
Python and library imports are one-time runtime initialization outside this
clock. No reference plan or model answer enters a deterministic run.

The independent methods are G; one neighborhood around G with radius 4; the
unrestricted Full-MILP; iterative radius-4 repair; and one neighborhood with
radius max(4,ceil(M/4)). The last method reuses the exact R4 run when M<=16.
Each online run has a 600-second total wall-clock budget. HiGHS 1.15.1 uses one
thread, seed zero, zero absolute and relative MIP gaps and the original
feasibility tolerances. The original public objective order and comparator are
unchanged. The historical R4 records remain a separate comparison.

Only proved objective prefixes are fixed. The existing public final-departure
pad-capacity lower bounds may certify the first two layers. Other layers are
fixed only after HiGHS returns optimal. A time limit never proves the current
objective value. Prefix scaling and equality tolerances match the original
engine. Full-MILP global proof and neighborhood proof are separately labeled.

For Iter-R4, a local attempt has a 60-second time slice, including neighborhood
construction and validation. At the first solver callback after a slice ends,
a strictly improved validated candidate causes a center update. If no
improvement exists, the next slice continues the same live HiGHS solve, retaining
its branch-and-bound state and all proved prefixes. Completed objective layers
continue within the neighborhood. A fully proved neighborhood with no strict
improvement terminates. A fully solved improved neighborhood updates the center
immediately. Interrupt callbacks are cooperative, so the recorded slice end may
slightly exceed its nominal boundary. The hard evaluation rule remains that
only validation completed by the total budget yields an available candidate.

The `cbMipSolution` callback records integer feasible proposals and calls the
unchanged independent verifier synchronously. Generation and validation-finish
times are separate. Duplicate decisions are not revalidated; unique candidates
are retained, including rejected proposals. Every improvement is retained with
its complete plan. The incumbent is updated in actual arrival order using the
original tolerance comparator. No offline validation is relabeled as online.

Official callback interface consulted before implementation:
[HiGHS callback documentation](https://ergo-code.github.io/HiGHS/dev/callbacks/)
and the installed highspy 1.15.1 `HighsCallbackEvent` implementation. A smoke run
on NET_S01_A verified callbacks and all six proof layers. Smoke uses its own
directory and is excluded from the formal batch.

Reference service and quality thresholds are applied only by the offline
summary script. At 30,60,180,300,600 seconds it reconstructs the best delivered
candidate by replaying improvements. First-hit times retain hit denominators.
The final objective may match a certified reference before its optimality proof
finishes; these times are distinct.

Historical model logs contain response-completion latency, followed by later
offline scoring. They do not contain online validation-finish timestamps.
Therefore the historical timing table asks whether a newly measured optimizer
had already delivered service/quality before that recorded response. It does
not invent an exact historical verified model availability time or simultaneous
paired execution. A complete deterministic candidate before response is enough
to establish that the model had no earlier deliverable candidate in that case.

Formal runs are sequential and require no concurrent heavy CPU work. Completed
task-method files are reused on restart. The fixed order prioritizes NET_L02_B,
then task ID, and uses G,R4,Full-MILP,Iter-R4,R_frac within each task. Output
serialization after the terminal result is not delivery time; callback logging
and validation during a run are included. Budget overruns cannot add delivered
candidates or proofs after 600 seconds.

The archived task schema specifies intervention intervals and fleet availability,
but does not identify the time the disruption information becomes known or the
already-executed prefix. Thus its minute-zero static schedules do not determine
an operational decision lead time. No departure is artificially shifted to make
response latency appear feasible; these data support computational response
comparisons, not a demonstrated rolling execution policy.
