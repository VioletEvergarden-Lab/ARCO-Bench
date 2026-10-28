"""One local entry for result verification and reproducible research batches.

Default checks recorded witnesses and study coverage, without new optimization.
--rerun resumes the original prescribed batches; existing terminal records are
reused. Historical benchmark inputs must remain beside this research folder.
"""
from pathlib import Path
from collections import Counter
import argparse,json,subprocess,sys,zipfile
sys.dont_write_bytecode=True
from coordination_study import ROOT,WS,load_cases,read,write
from coordination_solver import CoordinationProblem,canonical_plan,changes,target_met
from continuous_engine import Engine,compare
from query_reuse import Query,FeasibilityCache,self_test


def source_path(s):
 p=Path(s)
 if p.is_absolute():return p
 return WS/p if str(p).startswith(ROOT.name) or str(p).startswith('arco_') else ROOT/p


def verify():
 self_test();cases={c['record_id']:c for c in load_cases()};assert len(cases)==60
 engines={rid:Engine(c['task']) for rid,c in cases.items()};cache={};count=Counter()
 def check(rid,plan,origin,target,prefix,mode='match',allowed=None,k=None):
  engine=engines[rid];plan=canonical_plan(plan,engine.task);key=(rid,json.dumps(plan,sort_keys=True))
  if key not in cache:cache[key]=engine.verify(plan)
  v=cache[key];assert v['admissible'],(rid,v['errors'])
  assert target_met(v['objective'],target,prefix,mode),(rid,'target',prefix)
  ms,us=changes(plan,canonical_plan(origin,engine.task))
  assert allowed is None or set(us)<=set(allowed),(rid,'support')
  assert k is None or len(ms)<=k,(rid,'budget')
  return ms,us,v
 e1=read(ROOT/'analysis/e1_results.json');assert len(e1)==240
 assert len({(r['record_id'],r['target_prefix'],r['metric']) for r in e1})==240
 for r in e1:
  c=cases[r['record_id']];ms,us,_=check(r['record_id'],r['decisions'],c['origins']['G'],c['reference']['objective'],r['target_prefix'])
  assert 0<=r['lower_bound']<=r['upper_bound']==len(ms if r['metric']=='missions' else us)
  count['E1_scope_quantities']+=1
 queries=read(ROOT/'analysis/e2_query_results.json');assert len(queries)==340
 result_map={}
 for q in queries:
  r=read(source_path(q['source_file']));c=cases[q['record_id']]
  assert r['feasible'] is not None
  result_map.setdefault((q['record_id'],q['key']),[]).append(r['feasible'])
  if r['feasible']:
   check(q['record_id'],r['decisions'],c['origins']['G'],c['reference']['objective'],q['prefix'],allowed=q['allowed'],k=q['mission_budget'])
  elif r['evidence']=='proved_exclusion_reuse':
   s=read(source_path(r['source']));assert s['feasible'] is False
   a=Query.make(**s['query']);b=Query.make(**r['query'])
   assert a.prefix<=b.prefix and b.allowed<=a.allowed and b.mission_budget<=a.mission_budget
  else:assert r['solver_status']=='Infeasible',(q['record_id'],q['key'],r['solver_status'])
  count['E2_variant_query_records']+=1
 assert len(result_map)==170 and all(len(v)==2 and v[0]==v[1] for v in result_map.values())
 diagnoses=read(ROOT/'analysis/e2_candidate_diagnoses.json');assert len(diagnoses)==300
 model=[r for r in diagnoses if r['source'] in ('deepseek','luna')];assert len(model)==120
 assert Counter(r.get('diagnosis','excluded') for r in model)==Counter(successful_control=97,excluded=10,support_insufficient=5,support_sufficient_budget_insufficient=2,support_and_budget_sufficient=6)
 local=read(ROOT/'analysis/e2_actual_neighborhoods.json');assert local['complete'] and len(local['rows'])==40
 assert Counter(r['classification'] for r in local['rows'])==Counter(proved_scope_excluded=36,witness_inside=4),Counter(r['classification'] for r in local['rows'])
 count['actual_neighborhoods']=40
 for r in read(ROOT/'analysis/e3_selection.json'):
  folder=ROOT/r['folder'];task=read(folder/'task.json');rid=task['record_id'];engines[rid]=Engine(task)
  origins=read(folder/'origins.json');ref=read(folder/'new_reference.json');assert ref['global_optimal']
  for path in folder.glob('*_j*_*.json'):
   q=read(path);ms,us,_=check(rid,q['decisions'],origins['G'],q['target_objective'],q['target_prefix'],q['target_mode'])
   assert q['lower_bound']==q['upper_bound']==len(ms if q['minimize']=='missions' else us)
   count['E3_aspiration_and_new_reference_queries']+=1
 lex=read(ROOT/'analysis/e3_fixed_lex_bounds.json');assert len(lex['rows'])==28
 for r in lex['rows']:
  assert r['lower_bound']<=r['upper_bound'] and r['lex_comparison']<=0 and r['service_prefix_forced']
  if r['origin']=='G':assert r['lower_bound']==r['upper_bound']
 assert sum(r['origin']=='G' for r in lex['rows'])==14
 count['E3_fixed_lex_quantities']=14
 fresh=read(ROOT/'analysis/fresh_summary.json');assert fresh['conditions_generated']==8 and fresh['references_completed']==8
 fq=read(ROOT/'analysis/fresh_e1_results.json');assert len(fq)==32
 for row in fq:
  rid=row['record_id'];task=read(ROOT/'inputs/fresh/tasks'/f'{rid}.json');engines.setdefault(rid,Engine(task))
  q=read(source_path(row['source']));origin=read(ROOT/'runs/fresh/origins'/f'{rid}.json')['decisions']
  if q.get('decisions'):
   ms,us,_=check(rid,q['decisions'],origin,q['target_objective'],q['target_prefix'])
   assert q['lower_bound']<=q['upper_bound']==len(ms if q['minimize']=='missions' else us)
  count['fresh_scope_quantities']+=1
 core=read(ROOT/'analysis/core_e2_summary.json');assert len(read(ROOT/'analysis/core_e2_queries.json'))==48
 count['Core_candidate_queries']=48
 joint=read(ROOT/'analysis/e1_joint_minima.json');assert len(joint)==120
 assert Counter(r['status'] for r in joint)==Counter(jointly_attained=114,proved_tradeoff=1,marginal_minimum_unresolved=5)
 for r in joint:
  if r['status']=='jointly_attained':
   c=cases[r['record_id']];ms,us,_=check(r['record_id'],r['decisions'],c['origins']['G'],c['reference']['objective'],r['target_prefix'])
   assert len(ms)==r['mission_bounds'][0]==r['mission_bounds'][1] and len(us)==r['chain_bounds'][0]==r['chain_bounds'][1]
 tradeoff=read(ROOT/'analysis/e1_joint_tradeoff.json');c=cases[tradeoff['record_id']]
 proof=read(source_path(tradeoff['query_source']))
 assert tradeoff['status']=='proved_tradeoff' and proof['feasible'] is False and proof['solver_status']=='Infeasible'
 assert proof['task_budget']==2 and proof['chain_budget']==1 and proof['target_prefix']==2
 points=set()
 for w in tradeoff['witnesses']:
  ms,us,_=check(c['record_id'],w['decisions'],c['origins']['G'],c['reference']['objective'],tradeoff['target_prefix'])
  points.add((len(ms),len(us)))
 assert points=={(2,2),(3,1)} and tradeoff['marginal_minima']==[2,1]
 assert {(r['metric'],r['lower_bound'],r['upper_bound']) for r in e1 if r['record_id']==c['record_id'] and r['target_prefix']==2}=={('missions',2,2),('chains',1,1)}
 count['joint_budget_tradeoff_proofs']=1
 assert (ROOT/'notes/literature_sources.json').exists()
 count['unique_network_witnesses_replayed']=len(cache)
 summary=dict(status='passed',coverage=dict(count),E1_unclosed_intervals=sum(r['lower_bound']!=r['upper_bound'] for r in e1),explanation='Open scope intervals are retained outcomes under the prescribed budgets; all required query populations are present. Check replays witnesses and validates recorded coverage and reuse implications, without rerunning proofs.')
 write(ROOT/'analysis/reproduction_check.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
 return summary


def run_script(name,*args):
 subprocess.run([sys.executable,str(ROOT/'scripts'/name),*args],check=True,cwd=WS)


def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--rerun',action='store_true');a=p.parse_args()
 if a.rerun:
  run_script('coordination_study.py','--run-e1','--seconds','30','--round','initial')
  run_script('coordination_study.py','--run-e1','--seconds','120','--round','targeted','--queries','NET_L02_C:T2:chains','NEW_regions_L01_long:T6:missions')
  run_script('coordination_study.py','--extensions','--seconds','30')
  run_script('joint_tradeoff.py')
  run_script('coordination_study.py','--joint')
  run_script('coordination_study.py','--findings')
  run_script('candidate_scope.py','run','--seconds','30')
  run_script('local_neighborhood_diagnostics.py','--solve','--seconds','60')
  run_script('resource_interventions.py','run','--seconds','45','--reference-seconds','600')
  run_script('derive_e3_fixed_lex.py')
  run_script('analyze_core_e2.py')
  run_script('fresh_transfer.py','all','--workers','2')
 verify()

if __name__=='__main__':main()
