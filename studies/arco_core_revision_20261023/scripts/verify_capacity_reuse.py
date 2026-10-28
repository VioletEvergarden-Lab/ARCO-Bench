"""Replay seven existing capacity cases under their actual fixed lexicographic gate.

No solves and no writes to historical directories. This checks joint witnesses,
resource definitions, target semantics and provenance of the reused bounds.
"""
from pathlib import Path
import sys,json,hashlib,copy
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent
OLD=WS/'arco_contribution_20261011'
sys.path.insert(0,str(OLD/'scripts'))
from coordination_solver import Engine,changes,target_met
from continuous_engine import compare
import continuous_engine as ce
ce.HERE=ROOT/'runs/capacity_reuse'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
fixed=read(OLD/'analysis/e3_fixed_lex_bounds.json')
e1=read(OLD/'analysis/e1_results.json')
joint=read(OLD/'analysis/e1_joint_minima.json')
manifest={x['record_id']:x for x in read(OLD/'analysis/task_manifest.json')}
rows=[];source_paths=set()
for selection in read(OLD/'analysis/e3_selection.json'):
    rid=selection['record_id'];folder=OLD/selection['folder']
    source_task=WS/selection['source_task'];original=read(source_task);task=read(folder/'task.json')
    source_paths.update([source_task,folder/'task.json',folder/'origins.json',folder/'original_reference.json',folder/'new_reference.json'])
    oldref=read(folder/'original_reference.json');newref=read(folder/'new_reference.json')
    assert oldref['optimal'] and oldref['proved_prefix']==6
    assert newref['global_optimal'] or newref.get('optimal')
    origin=read(folder/'origins.json')['G'];eng=Engine(task)
    assert eng.verify(origin)['admissible']
    assert Engine(original).verify(origin)['admissible']
    # Only the charger capacity and descriptive record metadata may change.
    expected=copy.deepcopy(original)
    expected['resources']['charger'][selection['facility']]+=1
    assert original['intervention']==task['intervention'],(rid,'disruption changed')
    expected['record_id']=task['record_id']
    assert expected==task,rid
    old_rows={r['metric']:r for r in e1 if r['record_id']==rid and r['target_prefix']==6 and r['origin']=='G'}
    original_budget=[old_rows[m]['lower_bound'] for m in ('missions','chains')]
    assert all(old_rows[m]['lower_bound']==old_rows[m]['upper_bound'] for m in old_rows)
    original_joint=next(r for r in joint if r['record_id']==rid and r['target_prefix']==6)
    ds=original_joint['decisions'];sc=Engine(original).verify(ds)
    assert sc['admissible'] and target_met(sc['objective'],oldref['objective'],6)
    changed=changes(ds,origin);assert [len(x) for x in changed]==original_budget
    fixed_rows={r['metric']:r for r in fixed['witness_records'] if r['record_id']==rid and r['origin']=='G'}
    fixed_budget=[fixed_rows[m]['lower_bound'] for m in ('missions','chains')]
    fixed_plans=[]
    for metric,record in fixed_rows.items():
        assert record['lower_bound']==record['upper_bound']
        score=eng.verify(record['decisions']);assert score['admissible']
        assert compare(score['objective'],oldref['objective'])<=0
        # With zero holds at the original threshold, reaching that threshold
        # forces the same T2 service prefix used by the recorded lower bounds.
        assert oldref['objective']['urgent_holds']==oldref['objective']['total_holds']==0
        for src in record['lower_sources']:
            if src=='zero_distance_origin_membership':continue
            p=OLD/src;source_paths.add(p);q=read(p)
            assert q['target_prefix']==2 and q['minimize']==metric
            assert q['lower_bound']<=record['lower_bound']
            assert q['target_objective']['urgent_holds']==q['target_objective']['total_holds']==0
        c=changes(record['decisions'],origin)
        if [len(x) for x in c]==fixed_budget:fixed_plans.append((record,score,c))
    assert fixed_plans,rid
    new_queries={}
    for metric in ('missions','chains'):
        p=folder/f'new_reference_j6_{metric}.json';source_paths.add(p);q=read(p)
        assert q['lower_bound']==q['upper_bound'] and q['optimal']
        new_queries[metric]=q
    new_budget=[new_queries[m]['lower_bound'] for m in ('missions','chains')]
    possible=[newref]+list(new_queries.values());new_plans=[]
    for q in possible:
        score=eng.verify(q['decisions']);assert score['admissible']
        assert target_met(score['objective'],newref['objective'],6)
        c=changes(q['decisions'],origin)
        if [len(x) for x in c]==new_budget:new_plans.append((q,score,c))
    assert new_plans,(rid,'joint new budget missing')
    fp,fs,fc=fixed_plans[0];np,ns,nc=new_plans[0]
    rows.append(dict(record_id=rid,facility=selection['facility'],capacity_before=selection['old_capacity'],capacity_after=selection['new_capacity'],
        original_quality_joint_budget=original_budget,expanded_old_lex_threshold_joint_budget=fixed_budget,expanded_new_quality_joint_budget=new_budget,
        original_objective=oldref['objective'],old_threshold_witness_objective=fs['objective'],new_reference_objective=newref['objective'],
        old_threshold_changed_missions=fc[0],old_threshold_changed_uavs=fc[1],new_quality_changed_missions=nc[0],new_quality_changed_uavs=nc[1],
        old_threshold_at_original_capacity=Engine(original).verify(fp['decisions'])['errors'],
        new_quality_at_original_capacity=Engine(original).verify(np['decisions'])['errors'],
        old_threshold_charger_events=[x for x in fs['resource_intervals'] if x['kind']=='charger'],
        new_quality_charger_events=[x for x in ns['resource_intervals'] if x['kind']=='charger'],
        old_threshold_mode='lexicographically no worse under unchanged priority',joint_witnesses_replayed=True,capacity_is_only_domain_change=True,
        source_folder=str(folder.relative_to(WS))))
out=dict(status='PASS',cases=len(rows),new_solves=0,rows=rows,
         sources=[dict(path=str(p.relative_to(WS)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(source_paths)],
         interpretation='Expanded capacity changes the feasible domain; the old lexicographic threshold and the new optimal target answer separate questions. Marginal counts here each have a verified joint witness.')
(ROOT/'analysis/capacity_reuse_verified.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'status':out['status'],'cases':len(rows),'new_solves':0,'budgets':[{k:r[k] for k in ('record_id','original_quality_joint_budget','expanded_old_lex_threshold_joint_budget','expanded_new_quality_joint_budget')} for r in rows]},indent=2))
