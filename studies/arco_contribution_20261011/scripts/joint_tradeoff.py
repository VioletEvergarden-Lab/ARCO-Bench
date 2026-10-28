"""Resolve the only joint-budget gap found by complete marginal-witness scan."""
from pathlib import Path
import sys,time
sys.dont_write_bytecode=True
from coordination_study import ROOT,load_case,read,write
from coordination_solver import CoordinationProblem,changes

def main():
 case=load_case('NET_S02_C');rid=case['record_id'];rows=read(ROOT/'analysis/e1_results.json')
 qs={r['metric']:r for r in rows if r['record_id']==rid and r['target_prefix']==2}
 assert qs['missions']['lower_bound']==qs['missions']['upper_bound']==2
 assert qs['chains']['lower_bound']==qs['chains']['upper_bound']==1
 p=CoordinationProblem(case['task'],case['origins']['G'],'G')
 out=ROOT/'runs/e1_joint/NET_S02_C__T2__k2_c1.json'
 if out.exists():r=read(out)
 else:
  r=p.solve(case['reference']['objective'],target_prefix=2,minimize='feasibility',task_budget=2,chain_budget=1,seconds=30)
  write(out,r)
 witnesses=[]
 for label,q in qs.items():
  ms,us=changes(q['decisions'],case['origins']['G']);v=p.engine.verify(q['decisions'])
  assert v['admissible'];witnesses.append(dict(label=label,missions=len(ms),chains=len(us),changed_missions=ms,changed_uavs=us,decisions=q['decisions'],objective=v['objective'],source=q['witness_source']))
 result=dict(record_id=rid,target_prefix=2,origin='G',marginal_minima=[2,1],joint_feasible=r['feasible'],query_source=str(out.relative_to(ROOT)),seconds=r['elapsed_seconds'],witnesses=witnesses)
 if r['feasible'] is False:
  assert {(w['missions'],w['chains']) for w in witnesses}=={(2,2),(3,1)}
  result.update(status='proved_tradeoff',complete_nondominated_budget_frontier=[[2,2],[3,1]],proof='Integer lower bounds k>=2,c>=1; exclusion of (2,1); verified points (2,2),(3,1) dominate every remaining feasible integer budget.')
 elif r['feasible']:result['status']='joint_minima_attained'
 else:result['status']='joint_unknown'
 write(ROOT/'analysis/e1_joint_tradeoff.json',result)
 print({k:v for k,v in result.items() if k!='witnesses'})

if __name__=='__main__':main()
