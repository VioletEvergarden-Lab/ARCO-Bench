"""Rebuild result tables and vector figures from archived outputs only."""
from pathlib import Path
import argparse,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def run(name,*args):
    print('Rebuilding:',name,*map(str,args),flush=True)
    subprocess.run([sys.executable,str(ROOT/'scripts'/name),*map(str,args)],check=True,cwd=ROOT.parent)
def check_dependencies():
    required={
        'arco_closing_study':['continuous_engine.py','solver_backend.py','study_common.py','provider_transport.py','run_models.py','continuous_public_instructions.md','evaluation/scores.json','evaluation/per_task.csv','coordination_bounds/results.json'],
        'arco_codex_research_20260930':['common.py','physical_model.py'],
        'arco_codex_research_20260925':['solve_public_preferences.py','score_preference_sensitivity.py','source_tables/summary.json'],
        '..':['rescore.py','event_ledger.py','results/current/MASTER.jsonl'],
    }
    missing=[f'{folder}/{name}' for folder,names in required.items() for name in names if not (ROOT.parent/folder/name).is_file()]
    if missing:raise SystemExit('Keep the supplied companion directories adjacent. Missing files: '+', '.join(missing))
def main():
    p=argparse.ArgumentParser();p.add_argument('--allow-partial',action='store_true');a=p.parse_args()
    check_dependencies()
    expected=[(ROOT/'results/comparison/runs',180),(ROOT/'results/new_comparison/runs',120)]
    complete=True
    for folder,n in expected:
        count=len(list(folder.glob('*__*.json')))
        complete=complete and count==n
        if count!=n and not a.allow_partial:raise SystemExit(f'Incomplete stored comparison {folder.name}: {count}/{n}')
    run('mechanism_metrics.py');run('preference_analyze.py')
    run('physical_sensitivity.py','replay');run('summarize_physics_core.py')
    # This also rebuilds reference, restriction, paired-event and figure outputs.
    run('new_offline_summary.py')
    run('optimization_summary.py')
    run('optimization_summary.py','--runs',ROOT/'results/new_comparison/runs','--references',ROOT/'new_networks/references','--expected','24')
    if complete:run('optimization_a5_evidence.py')
    else:print('A5 aggregate comparison skipped: stored deterministic matrix is incomplete.',flush=True)
    run('score_new_models.py');run('selection_arrival_analysis.py')
    run('analyze_generated_structure.py')
    run('summarize_final_generation.py')
    run('draw_figure3.py');run('draw_focused_results.py')
    print('Saved-result tables and figures rebuilt; optimizer calls = 0; model requests = 0.')
if __name__=='__main__':main()
