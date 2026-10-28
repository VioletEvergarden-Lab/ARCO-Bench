"""Post-development transfer on four prespecified fresh paired network bases.
Reuses unchanged generation/solver/verifier; writes only current research folder.
Run: D:\\Code\\python.exe arco_contribution_20261011/scripts/fresh_transfer.py all --workers 2
Resume-safe: saved references and per-query terminal records are reused.
"""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from collections import Counter
from datetime import datetime,timezone
import argparse,copy,csv,json,os,sys,time,traceback
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];W=ROOT.parent
sys.path[:0]=[str(W/'arco_focused_revision_20261002/scripts'),str(ROOT/'scripts')]
from new_networks import construct,CONFIG
import continuous_engine as ce
from continuous_engine import Engine,TIERS,QUALITY_TOL,quality
from optimization_online import run_online
from coordination_solver import CoordinationProblem,canonical_plan,changes,target_met
ce.HERE=ROOT/'runs/fresh/solver_progress'
CELLS=[('ladder','M',20261012),('ladder','L',20262012),('regions','M',20263012),('regions','L',20264012)]
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,obj):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(p.name+f'.{os.getpid()}.tmp');tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');tmp.replace(p)
def rel(p):return Path(p).relative_to(W).as_posix()
def now():return datetime.now(timezone.utc).isoformat()
def csvout(path,rows):
 fields=list(dict.fromkeys(k for r in rows for k in r))
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
  writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)
def generate():
 manifest_path=ROOT/'inputs/fresh/manifest.json'
 if manifest_path.exists():return read(manifest_path)
 assert (ROOT/'notes/fresh_protocol.md').is_file()
 records=[]
 for topology,scale,seed in CELLS:
  attempts=[];filled=False
  for attempt in range(20):
   used_seed=seed+100*attempt
   try:states,meta=construct(topology,scale,used_seed,index=1,development=False)
   except ValueError as exc:
    attempts.append(dict(attempt=attempt,seed=used_seed,accepted=False,reason=str(exc)));continue
   attempts.append(dict(attempt=attempt,seed=used_seed,accepted=True,reason='pre-disruption incumbent and generator structural validity'))
   base=f'FRESH_{topology}_{scale}01';paths=[]
   for condition,task in states.items():
    task['record_id']=base+'_'+condition
    task['research_provenance']={'cohort':'post_development_transfer_20261012','base_id':base,'generation_seed':used_seed,'method_fixed_before_generation':True}
    path=ROOT/'inputs/fresh/tasks'/f"{task['record_id']}.json";save(path,task);paths.append(rel(path))
   records.append(dict(base_id=base,topology=topology,scale=scale,base_seed=seed,seed=used_seed,filled=True,attempts=attempts,task_paths=paths,generator_metadata=meta))
   filled=True;print(base,'generated',used_seed,'attempt',attempt,flush=True);break
  if not filled:records.append(dict(base_id=f'FRESH_{topology}_{scale}01',topology=topology,scale=scale,base_seed=seed,filled=False,attempts=attempts,task_paths=[]))
  save(ROOT/'inputs/fresh/generation_progress.json',records)
 manifest=dict(protocol='fresh_transfer_v1',generated_utc=now(),methods_fixed_protocol='notes/fresh_protocol.md',cells=CELLS,base_count_planned=4,conditions_planned=8,admission='original pre-disruption baseline and generator structural validity only',generator_source=rel(W/'arco_focused_revision_20261002/scripts/new_networks.py'),generator_config=copy.deepcopy(CONFIG),references_seconds=600,query_seconds=60,records=records)
 save(manifest_path,manifest);return manifest

def run_record(task_path):
 task_path=Path(task_path);task=read(task_path);rid=task['record_id'];started=now()
 refpath=ROOT/'runs/fresh/references'/f'{rid}.json'
 if refpath.exists():ref=read(refpath)
 else:
  print(rid,'reference start',flush=True)
  ref=run_online(task_path,'Full-MILP',budget=600.)
  save(refpath,ref)
  print(rid,'reference',ref['global_optimal'],round(ref['total_seconds'],3),flush=True)
 engine=Engine(task);g=canonical_plan(engine.greedy(),task);gv=engine.verify(g)
 assert gv['admissible'],(rid,'G infeasible',gv['errors'])
 score=engine.verify(ref['decisions']) if ref.get('decisions') else None
 if score:assert score['admissible'] and quality(score['objective'],ref['objective'])
 proved=max((int(n.get('proved_prefix',0)) for n in ref.get('neighborhoods',[])),default=0)
 if ref['global_optimal']:assert proved==6
 save(ROOT/'runs/fresh/origins'/f'{rid}.json',dict(record_id=rid,origin='G',decisions=g,objective=gv['objective'],independent_verification=True))
 save(ROOT/'runs/fresh/reference_plans'/f'{rid}.json',dict(record_id=rid,global_optimal=ref['global_optimal'],proved_prefix=proved,objective=ref['objective'],decisions=ref.get('decisions'),independent_verification=bool(score and score['admissible']),source=rel(refpath)))
 problem=CoordinationProblem(task,g,'G');pool=[ref['decisions']] if score else [];rows=[]
 for j in (2,6):
  for mode in ('missions','chains'):
   outpath=ROOT/'runs/fresh/queries'/f'{rid}__T{j}__{mode}.json'
   if outpath.exists():result=read(outpath)
   elif proved<j or score is None:
    result=dict(record_id=rid,origin_name='G',target_prefix=j,minimize=mode,status='target_unproved',target_objective=ref.get('objective'),reference_proved_prefix=proved,lower_bound=None,upper_bound=None,feasible=None,optimal=False,decisions=None,elapsed_seconds=0.,solver_seconds=0.,reason='Reference prefix not certified within its fixed 600-second budget')
    save(outpath,result)
   else:
    result=problem.solve(ref['objective'],target_prefix=j,minimize=mode,seconds=60.,witness=pool)
    save(outpath,result)
   if result.get('decisions'):
    v=engine.verify(result['decisions']);assert v['admissible'] and target_met(v['objective'],ref['objective'],j)
    ms,us=changes(canonical_plan(result['decisions'],task),g)
    assert len(ms)==result['mission_changes'] and len(us)==result['chain_changes']
    pool.append(result['decisions'])
   rows.append(dict(record_id=rid,base_id=rid.rsplit('_',1)[0],condition=rid.rsplit('_',1)[1],topology=rid.split('_')[1],scale=rid.split('_')[2][0],missions=len(task['missions']),uavs=len(task['fleet']),target_prefix=j,minimize=mode,status=result['status'],lower_bound=result.get('lower_bound'),upper_bound=result.get('upper_bound'),optimal=result.get('optimal',False),witness_mission_changes=result.get('mission_changes'),witness_chain_changes=result.get('chain_changes'),witness_support=result.get('changed_uavs'),query_seconds=result['elapsed_seconds'],solver_seconds=result.get('solver_seconds',0),reference_global_optimal=ref['global_optimal'],reference_proved_prefix=proved,reference_seconds=ref['total_seconds'],G_target_met=bool(proved>=j and target_met(gv['objective'],ref['objective'],j)),source=rel(outpath)))
   print(rid,'T'+str(j),mode,result['status'],result.get('lower_bound'),result.get('upper_bound'),flush=True)
 save(ROOT/'runs/fresh/completed'/f'{rid}.json',dict(record_id=rid,started_utc=started,completed_utc=now(),rows=rows))
 return rows

def relation(a,b):
 if any(r is None or r['lower_bound'] is None or r['upper_bound'] is None for r in [a,b]):return 'unresolved'
 if a['upper_bound']<b['lower_bound']:return 'increase'
 if a['lower_bound']>b['upper_bound']:return 'decrease'
 if a['lower_bound']==a['upper_bound']==b['lower_bound']==b['upper_bound']:return 'equal'
 return 'unresolved'
def summarize(manifest):
 rows=[]
 for base in manifest['records']:
  for path in base['task_paths']:
   done=ROOT/'runs/fresh/completed'/f'{Path(path).stem}.json'
   if done.exists():rows.extend(read(done)['rows'])
 save(ROOT/'analysis/fresh_e1_results.json',rows);csvout(ROOT/'analysis/fresh_e1_results.csv',rows)
 lookup={(r['record_id'],r['target_prefix'],r['minimize']):r for r in rows}
 target_pairs=[];closure_pairs=[]
 for base in manifest['records']:
  if not base['filled']:continue
  for path in base['task_paths']:
   rid=Path(path).stem
   for mode in ('missions','chains'):
    a=lookup.get((rid,2,mode));b=lookup.get((rid,6,mode))
    target_pairs.append(dict(record_id=rid,dimension=mode,T2_bounds=[a.get('lower_bound'),a.get('upper_bound')] if a else None,T6_bounds=[b.get('lower_bound'),b.get('upper_bound')] if b else None,service_to_quality=relation(a,b)))
  for j in (2,6):
   for mode in ('missions','chains'):
    a=lookup.get((base['base_id']+'_short',j,mode));b=lookup.get((base['base_id']+'_long',j,mode))
    closure_pairs.append(dict(base_id=base['base_id'],target_prefix=j,dimension=mode,short_bounds=[a.get('lower_bound'),a.get('upper_bound')] if a else None,long_bounds=[b.get('lower_bound'),b.get('upper_bound')] if b else None,short_to_long=relation(a,b)))
 save(ROOT/'analysis/fresh_target_pairs.json',target_pairs);save(ROOT/'analysis/fresh_closure_pairs.json',closure_pairs)
 refs=[read(ROOT/'runs/fresh/references'/f"{Path(p).stem}.json") for b in manifest['records'] for p in b['task_paths'] if (ROOT/'runs/fresh/references'/f"{Path(p).stem}.json").exists()]
 operating=[];joint=[]
 for ref in refs:
  rid=ref['record_id'];origin_path=ROOT/'runs/fresh/origins'/f'{rid}.json'
  if not origin_path.exists():continue
  origin=read(origin_path);loss=next((i+1 for i,t in enumerate(TIERS) if abs(origin['objective'][t]-ref['objective'][t])>QUALITY_TOL[i]),None)
  operating.append(dict(record_id=rid,G_objective=origin['objective'],reference_objective=ref['objective'],G_first_loss=('L'+str(loss)) if loss else None,reference_urgent_holds=ref['objective'][TIERS[0]],reference_total_holds=ref['objective'][TIERS[1]],reference_source=rel(ROOT/'runs/fresh/reference_plans'/f'{rid}.json'),G_source=rel(origin_path)))
  for j in [2,6]:
   a=lookup.get((rid,j,'missions'));b=lookup.get((rid,j,'chains'))
   if a is None or b is None:continue
   exact=bool(a['optimal'] and b['optimal'])
   both=exact and any(r.get('witness_mission_changes')==a['lower_bound'] and r.get('witness_chain_changes')==b['lower_bound'] for r in [a,b])
   joint.append(dict(record_id=rid,target_prefix=j,mission_minimum=a['lower_bound'] if a['optimal'] else None,chain_minimum=b['lower_bound'] if b['optimal'] else None,joint_corner_status='verified_stored_witness' if both else 'not_determined_by_stored_witnesses',new_solver_calls=0,witness_sources=[r['source'] for r in [a,b] if both and r.get('witness_mission_changes')==a['lower_bound'] and r.get('witness_chain_changes')==b['lower_bound']]))
 save(ROOT/'analysis/fresh_operating_summary.json',operating)
 save(ROOT/'analysis/fresh_joint_witnesses.json',joint)
 summary=dict(protocol='fresh_transfer_v1',summarized_utc=now(),bases_filled=sum(b['filled'] for b in manifest['records']),bases_planned=4,conditions_generated=sum(len(b['task_paths']) for b in manifest['records']),generation_rejections=sum(sum(not a['accepted'] for a in b['attempts']) for b in manifest['records']),references_completed=len(refs),references_global_optimal=sum(r['global_optimal'] for r in refs),queries_completed=len(rows),query_statuses=dict(Counter(r['status'] for r in rows)),service_to_quality={m:dict(Counter(r['service_to_quality'] for r in target_pairs if r['dimension']==m)) for m in ['missions','chains']},short_to_long={f'T{j}_{m}':dict(Counter(r['short_to_long'] for r in closure_pairs if r['target_prefix']==j and r['dimension']==m)) for j in [2,6] for m in ['missions','chains']},reference_seconds_total=sum(r['total_seconds'] for r in refs),query_seconds_total=sum(r['query_seconds'] for r in rows),new_model_calls=0,interpretation='Four post-development bases from the same generator; no model-performance filter or new model generations')
 save(ROOT/'analysis/fresh_summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
 return summary

def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['generate','run','summarize','all']);p.add_argument('--workers',type=int,default=2);args=p.parse_args()
 assert 1<=args.workers<=2
 manifest=generate()
 if args.mode in ['run','all']:
  paths=[str(W/path) for b in manifest['records'] for path in b['task_paths']]
  with ProcessPoolExecutor(max_workers=args.workers) as executor:
   futures={executor.submit(run_record,path):path for path in paths}
   for future in as_completed(futures):
    path=futures[future]
    try:future.result()
    except Exception as exc:
     save(ROOT/'runs/fresh/errors'/f'{Path(path).stem}.json',dict(record_id=Path(path).stem,error=repr(exc),traceback=traceback.format_exc(),at_utc=now()))
     print(Path(path).stem,'ERROR',repr(exc),flush=True)
    summarize(manifest)
 if args.mode!='generate':summarize(manifest)
if __name__=='__main__':main()
