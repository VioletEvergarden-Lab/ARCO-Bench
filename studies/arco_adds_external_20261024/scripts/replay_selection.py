"""Apply the manuscript's pairwise verified selector to saved candidates."""
from collections import Counter
from run_deterministic import ROOT,read,write,ce
import hashlib,json
def plan_hash(plan):return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main():
 scores=read(ROOT/'analysis/candidate_evaluation/scores.json')
 if not all(x['terminal_record_saved'] for x in scores):raise RuntimeError('Wait for the full formal evaluation')
 manifest=read(ROOT/'instances/FROZEN.json');tasks={x['record_id']:read(ROOT/x['task_path']) for x in manifest['tasks']}
 rows=[]
 for row in scores:
  rid=row['record_id'];engine=ce.Engine(tasks[rid])
  lm=engine.verify(row['decisions']) if row['decisions'] is not None and row['complete_decisions'] else None
  for method in ['G','R4','R_frac','Iter-R4','Full-MILP']:
   deterministic=read(ROOT/'runs/deterministic'/f'{rid}__{method}.json');ds=engine.verify(deterministic['decisions']);assert ds['admissible']
   for mode in ['final_output','within_600s']:
    eligible=lm is not None and lm['admissible'] and (mode=='final_output' or row['available_seconds'] is not None and row['available_seconds']<=600.)
    selected_lm=eligible and ce.compare(lm['objective'],ds['objective'])<0
    plan=row['decisions'] if selected_lm else deterministic['decisions']
    selected_score=engine.verify(plan);assert selected_score['admissible']
    # The quality reference is read only after the unchanged plan is selected.
    ref=read(ROOT/'runs/deterministic'/f'{rid}__Full-MILP.json')
    rows.append(dict(record_id=rid,provider=row['provider'],deterministic_method=method,mode=mode,
      eligible_generated=eligible,selected_source=row['provider'] if selected_lm else method,
      deterministic_tie_break=True,selected_plan_sha256=plan_hash(plan),admissible=True,
      reference_quality=ce.quality(selected_score['objective'],ref['objective']),objective=selected_score['objective'],
      plan_source=(row['original_raw_path'] if selected_lm else f'runs/deterministic/{rid}__{method}.json')))
 summary=[]
 for method in ['G','R4','R_frac','Iter-R4','Full-MILP']:
  for provider in ['deepseek','luna']:
   for mode in ['final_output','within_600s']:
    sub=[r for r in rows if r['deterministic_method']==method and r['provider']==provider and r['mode']==mode]
    summary.append(dict(method=method,provider=provider,mode=mode,N=len(sub),admissible=sum(x['admissible'] for x in sub),reference_quality=sum(x['reference_quality'] for x in sub),selected_sources=dict(Counter(x['selected_source'] for x in sub))))
 write(ROOT/'analysis/selection_replay.json',dict(protocol='Existing pairwise selector: sole admissible, otherwise tolerance-aware lexicographic comparison; deterministic wins ties; unchanged output',reference_used_for_selection=False,posthoc_replay_of_recorded_candidates=True,rows=rows,summary=summary))
 print(json.dumps(dict(rows=len(rows),summary=summary),indent=2))
if __name__=='__main__':main()
