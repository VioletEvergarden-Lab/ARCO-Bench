# Arrival-time selection reconstruction

`scripts/selection_arrival_analysis.py` aligns the independently measured
Full-MILP or Iter-R4 trajectory and each model's first formal response at a
common task-availability origin. It merges only the deterministic method's
published improving plans and the model's complete, independently verified
plan. This reconstructs a parallel-arrival selection policy; it does not
claim the pair was executed together in the same experimental run.

Each arriving proposal is compared with the currently selected plan using the
unchanged public tolerance comparator. The measured compare-and-select
processing time is added to its source availability. A serial selector queue
also accounts for any overlap between arrival and the previous comparison.
An exact arrival-time tie puts the deterministic proposal first; an objective
tie retains the already-selected plan. Source delivery time, selection
completion time and comparison overhead are saved separately. Millisecond
selection overhead is never reported as end-to-end repair latency.

The outputs contain individual methods and the four Full/Iter + model pairs
at 30,60,180,300,600 seconds. Incremental service/quality counts compare each
pair with the same task's deterministic method at that cutoff. All repeat-1
tasks remain in the scheduled denominator. Pending source runs leave formal
hit fields blank; known delivered plans remain available in explicitly named
`known_*` columns. Once all inputs exist, the same command produces the full
table without changing the analysis rule.

```powershell
python arco_focused_revision_20261002/scripts/selection_arrival_analysis.py
```

Files are written to `results/arrival_selection/`: single-method slices,
pair slices and gains, source status, selection events, and budget summaries.
The script performs no POST, optimization or new candidate generation.
