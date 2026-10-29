# Reproducing the saved results

Run commands from the directory containing `README.md`. The supported and tested platform for the complete replay below is Windows x86-64 with Python 3.12.4. The Core-72 scorer requires NumPy 1.26.4 and SciPy 1.13.1. Study replay also imports HiGHS/highspy 1.15.1, NetworkX 3.2.1 and Matplotlib 3.8.4; openpyxl 3.1.5 reads the ADDS workbook.

The eight-group study entry is Windows-only in this version: archived helpers import `msvcrt` and read Windows-style paths in saved records. Linux and macOS are not supported for the complete study replay; success of an individual command does not establish full-platform support.

```sh
python -m pip install -r requirements-studies.txt
python -B smoke_submission.py
python -B build_results.py --output local_results/core72
python -B studies/replay_saved.py --group all --output local_results/studies
```

`build_results.py` rescans the saved answers with the public verifier, evaluates reference quality and reconstructs the actual verifier-gated selections. It writes `MASTER.jsonl`, CSV tables, selection records and `BUILD_RESULT.json`. Its 936 rows include labelled historical instruction conditions as well as the complete-public panel used in the current paper. The latter has 69/72 DeepSeek and 68/72 Luna reference-quality repairs; the greedy policy has 38/72 and its selections with either model have 71/72.

`studies/replay_saved.py` checks stored decisions, target witnesses, query records and derived classifications. It blocks network connections and optimizer calls, writes only to the selected output directory and ends with `local_results/studies/SUMMARY.json`. A successful run reports `PASS`, zero network calls and zero optimizer calls. A single group can be selected with `--group networks`, `sensitivity`, `core_diagnostics`, `scope`, `candidate_diagnostics`, `origin_target`, `capacity` or `adds`.

## Inputs and result locations

The study folder names retain the original experiment identifiers. References, candidate responses, unsuccessful outputs and bounded-query records are included alongside successful plans.

| Paper evidence | Inputs and saved outputs under `studies/` |
|---|---|
| Core-72 R3/R4, action restrictions, capacity and preference diagnostics | `arco_codex_research_20260925/`, `arco_codex_research_20260930/`, `arco_closing_study/core_r4/`; derived tables in `arco_stage_research_20261009/analysis/core_*` |
| 36 original network conditions | `arco_closing_study/networks/`, `online/`, `evaluation/`; five-method comparison in `arco_focused_revision_20261002/results/comparison/` |
| 24 paired conditions (first responses in the main panel; repeats also retained) | `arco_focused_revision_20261002/new_networks/`, `online/new_generation/`, `results/new_comparison/` and `results/arrival_selection/` |
| Repair-scope minima, joint witnesses and candidate/neighborhood queries | `arco_contribution_20261011/runs/e1*/`, `runs/e2*/` and corresponding `analysis/` files |
| Fixed-origin capacity interventions and fresh networks | `arco_contribution_20261011/runs/e3/`, `inputs/fresh/`, `runs/fresh/` |
| Eight-condition origin/target panel | `arco_core_revision_20261023/runs/origin_target/`, `analysis/origin_target_*` |
| Candidate and final-neighborhood classification | `arco_core_revision_20261023/analysis/candidates_*` and the linked original query records |
| Paired events and reservation-window sensitivity | `arco_stage_research_20261009/analysis/paired_*`, `arco_closing_study/window_sensitivity/` |
| ADDS | `arco_adds_external_20261024/instances/`, `source/`, `runs/` and `analysis/` |

The network checks cover 60 conditions, 300 deterministic plans and 120 initial model terminals. The origin/target panel retains 108 exact positions and 20 intervals. ADDS contains 15 conditions, 75 deterministic plans and 30 model outputs; its saved model reference-quality counts are 13/15 and 15/15, or 9/15 and 11/15 when requiring availability within 600 seconds. The two ADDS quality misses remain in the package and are diagnosed with their original scope queries.


ADDS provides operational context through a public logistics simulation dataset. Generated source demand, locker assignments and saved model geometry are distinguished from the experimental UAV assignments, deadlines, closures and reservation capacities. The source workbook, geometry and construction inputs are bundled; the [ADDS dataset DOI](https://doi.org/10.5281/zenodo.20491777) supplies the full upstream dataset. No FlexSim installation is needed for replay.

For individual records, use `admit.py` for public feasibility or `rescore.py` for reference evaluation. Each response JSONL row contains `record_id` and `raw_text`; the output contract is `schema/output.schema.json`. The `private` evaluator directory names refer to information withheld at generation time, not to a private GitHub dependency.

## Figures

`figures/published/` contains the ten figures supplied with the manuscript. `figures/index.json` maps them to data and source scripts. Run `python -B figures/redraw.py` to write regenerated figures to `figures/generated/`, or use `--only m01b` for a single saved-plan figure. Eight figures reproduce the supplied rendering. Supplementary S1 has a reconstruction from the same data with a different layout; Figure 1 is preserved as supplied because its editable composition source was not included.

## Optional recomputation and new model outputs

The original optimizer and diagnostic drivers are retained within each study. Examples are `arco_closing_study/run_network_study.py`, `arco_focused_revision_20261002/scripts/run_comparison.py`, `arco_contribution_20261011/scripts/coordination_study.py` and `arco_adds_external_20261024/scripts/run_deterministic.py`. They can invoke optimization and may write experiment outputs. Use a separate working copy for new computations; the saved replay above does not invoke these batches. A new solver run can return different time-limited bounds.

Request preparation is separate from scoring and sends nothing:

```sh
python -B prepare_requests.py --model deepseek-v4-pro --interface chat_completions --output local_results/new_requests
```

This writes 72 request bodies and `PREPARATION_ONLY.json`. Historical request bodies and model identities are retained under `provenance/` and the study `online/` directories. Provider availability and supported fields may change. Live study runners use `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` from the process environment; `credentials/provider.env.example` lists the names. A `.env` file is not loaded automatically. New calls require provider access and billing and must use a new run directory. The ADDS delivered evidence is read-only for generation. None of these credentials are needed for the documented replay commands.

See `LICENSES/README.md` for data provenance and distribution terms.
