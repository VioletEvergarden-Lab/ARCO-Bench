"""Derive fixed lexicographic-threshold coordination bounds from E3 evidence.

No optimization is called. Each stored plan is independently re-evaluated in the
intervened domain. A T2 lower bound is used only when every old-threshold plan
must have that same service prefix; all present cases have old L1=L2=0.
"""
from pathlib import Path
import csv,json,time
from coordination_solver import Engine,TIERS,QUALITY_TOL,changes,canonical_plan
from continuous_engine import compare
BASE=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 started=time.perf_counter();rows=[];origins_rows=[];details=[]
 for entry in read(BASE/'analysis/e3_selection.json'):
  folder=BASE/entry['folder'];task=read(folder/'task.json');eng=Engine(task)
  old=read(folder/'original_reference.json');new=read(folder/'new_reference.json')
  origins=read(folder/'origins.json');target=old['objective']
  plans=[('origin_G',origins['G']),('origin_incumbent',origins['incumbent'])]
  sources=[folder/'original_reference.json',folder/'new_reference.json']+sorted(folder.glob('*_j*_*.json'))
  for path in sources:
   r=read(path)
   if r.get('decisions'):plans.append((str(path.relative_to(BASE)),r['decisions']))
  pool=[];seen=set()
  for source,ds in plans:
   ds=canonical_plan(ds,task);key=json.dumps(ds,sort_keys=True)
   if key in seen:continue
   seen.add(key);score=eng.verify(ds)
   if not score['admissible']:continue
   for name,b in origins.items():
    ms,us=changes(ds,canonical_plan(b,task))
    origins_rows.append(dict(record_id=entry['record_id'],intervention_id=entry['intervention_id'],
     origin=name,source=source,mission_changes=len(ms),chain_changes=len(us),changed_uavs=us,
     lex_vs_original=compare(score['objective'],target),objective=score['objective']))
   if compare(score['objective'],target)<=0:
    pool.append(dict(source=source,decisions=ds,objective=score['objective']))
  assert pool
  same_service=all(abs(new['objective'][t]-target[t])<=QUALITY_TOL[i]+1e-10 for i,t in enumerate(TIERS[:2]))
  service_forced=(target[TIERS[0]]==0 and target[TIERS[1]]==0) or (same_service and new['global_optimal'])
  for name,origin in origins.items():
   origin=canonical_plan(origin,task);origin_score=eng.verify(origin)
   origin_ok=origin_score['admissible'] and compare(origin_score['objective'],target)<=0
   for metric in ('missions','chains'):
    def distance(p):
     ms,us=changes(p['decisions'],origin)
     return len(ms) if metric=='missions' else len(us)
    best=min(pool,key=distance);upper=distance(best)
    lower=0 if origin_ok else 1
    lower_sources=['zero_distance_origin_membership']
    if name=='G' and service_forced:
     for label in ('fixed_aspirations','new_reference'):
      path=folder/f'{label}_j2_{metric}.json'
      if not path.exists():continue
      if label=='new_reference' and not same_service:continue
      r=read(path)
      if r.get('lower_bound') is not None:
       lower=max(lower,int(r['lower_bound']));lower_sources.append(str(path.relative_to(BASE)))
    assert lower<=upper,(entry['record_id'],name,metric,lower,upper)
    ms,us=changes(best['decisions'],origin)
    row=dict(record_id=entry['record_id'],intervention_id=entry['intervention_id'],group=entry['group'],
     origin=name,metric=metric,target_mode='fixed_original_lexicographic_no_worse',lower_bound=lower,
     upper_bound=upper,status='exact_by_bounds' if lower==upper else 'bounded',
     lower_sources=lower_sources,upper_source=best['source'],changed_missions=ms,changed_uavs=us,
     witness_objective=best['objective'],target_objective=target,lex_comparison=compare(best['objective'],target),
     service_prefix_forced=service_forced,independent_verification=True,new_solves=0)
    rows.append(row);details.append(dict(**row,decisions=best['decisions']))
 elapsed=time.perf_counter()-started
 write(BASE/'analysis/e3_fixed_lex_bounds.json',dict(rows=rows,elapsed_seconds=elapsed,new_solves=0,
  reasoning='A lexicographically no-worse plan must attain the original zero-hold service prefix; minimize-distance T2 bounds apply. Verified stored witnesses provide upper bounds. Incumbent-origin bounds use only zero-distance uniqueness unless zero closes.',
  witness_records=details))
 write(BASE/'analysis/e3_origin_witness_comparison.json',origins_rows)
 for name,data in [('e3_fixed_lex_bounds.csv',rows),('e3_origin_witness_comparison.csv',origins_rows)]:
  with (BASE/'analysis'/name).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader()
   w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in data)
 print('fixed lex G bounds',[(r['record_id'],r['metric'],r['lower_bound'],r['upper_bound']) for r in rows if r['origin']=='G'])
 print('new solves 0; independent replay seconds',round(elapsed,3))
if __name__=='__main__':main()
