"""Three restricted target queries for every complete original candidate miss.

The origin is the saved formal G. Allowed chains and task-change cardinality
come from the original submitted plan, including complete infeasible plans.
The optimized alternatives are witnesses only; candidate scores never change.
"""
from pathlib import Path
from collections import Counter
import json,sys
sys.dont_write_bytecode=True
import run_adds_candidates as runner
from adds_runtime import load_runtime
ROOT=runner.ROOT
ce,CoordinationProblem,changes,target_met,MODEL=load_runtime()

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def check(q,task,origin,ref,allowed,budget):
    if q['decisions'] is None:
        assert q['feasible'] is not True
        return
    score=ce.Engine(task).verify(q['decisions'])
    assert score['admissible'] and target_met(score['objective'],ref['objective'],6)
    mids,uids=changes(q['decisions'],origin)
    assert len(mids)==q['mission_changes'] and len(uids)==q['chain_changes']
    assert allowed is None or set(uids)<=set(allowed)
    assert budget is None or len(mids)<=budget

def main():
    rows=runner.read(ROOT/'analysis/candidate_evaluation/scores.json')
    manifest=runner.read(ROOT/'instances/FROZEN.json')
    tasks={t['record_id']:t for t in manifest['tasks']};out=[]
    for row in rows:
        if not row['scope_diagnosis_eligible']:continue
        rid=row['record_id'];item=tasks[rid];p=ROOT/item['task_path']
        assert runner.sha(p.read_bytes())==item['sha256']
        task=runner.read(p);origin=runner.read(ROOT/'runs/deterministic'/f'{rid}__G.json')['decisions']
        ref=runner.read(ROOT/'runs/deterministic'/f'{rid}__Full-MILP.json')
        assert ref['global_optimal'] and ce.Engine(task).verify(origin)['admissible']
        original=row['decisions'];mids,uids=changes(original,origin);k=len(mids)
        cp=CoordinationProblem(task,origin,origin_name='formal_G')
        queries={};paths={}
        for name,allowed,budget in [('all_chains_candidate_budget',None,k),
            ('candidate_chains_unlimited_budget',uids,None),('candidate_chains_candidate_budget',uids,k)]:
            path=ROOT/'runs/candidate_diagnostics'/f"{row['attempt_id']}__{name}.json"
            if path.exists():
                q=runner.read(path)
                assert q['task_budget']==budget and (allowed is None or q['allowed_uavs']==sorted(allowed))
            else:
                q=cp.solve(ref['objective'],target_prefix=6,minimize='feasibility',allowed_uavs=allowed,
                    task_budget=budget,seconds=60.,witness=ref['decisions'])
                check(q,task,origin,ref,allowed,budget);write(path,q)
            check(q,task,origin,ref,allowed,budget)
            queries[name]=q;paths[name]=path.relative_to(ROOT).as_posix()
        unlimited=queries['candidate_chains_unlimited_budget'];same=queries['candidate_chains_candidate_budget']
        if unlimited['feasible'] is False:category='chain_set_excludes_target'
        elif same['feasible'] is True:category='same_scope_attainable'
        elif unlimited['feasible'] is True and same['feasible'] is False:category='task_budget_insufficient_within_chainset'
        else:category='unresolved'
        if category=='chain_set_excludes_target':assert same['feasible'] is not True
        origin_quality=ce.quality(ce.Engine(task).verify(origin)['objective'],ref['objective'])
        result=dict(record_id=rid,provider=row['provider'],attempt_id=row['attempt_id'],
            original_admissible=row['admissible'],original_first_miss=row['first_miss'],
            origin='formal_G',target='T6',candidate_changed_missions=mids,candidate_changed_chains=uids,
            candidate_task_budget=k,candidate_chain_count=len(uids),category=category,
            G_already_attains_target=origin_quality,trivial_G_witness=category=='same_scope_attainable' and origin_quality,
            queries={name:{k:q[k] for k in ('status','feasible','optimal','elapsed_seconds','mission_changes','chain_changes','witness_source')} for name,q in queries.items()},
            query_paths=paths)
        result['candidate_objective']=row['objective'];result['reference_objective']=ref['objective']
        # A saved all-chain minimum also proves the minimum within a candidate's
        # scope when its allowed chain set is the entire fleet.
        global_min=ROOT/'runs/coordination'/f'{rid}__T6__missions.json'
        if set(uids)==set(cp.uavs) and global_min.exists():
            minimum=runner.read(global_min)
            check(minimum,task,origin,ref,uids,None)
            if minimum['status']=='optimal' and minimum['lower_bound']==minimum['upper_bound']:
                result['minimum_task_budget_within_candidate_chains']=minimum['upper_bound']
                result['minimum_budget_evidence_path']=global_min.relative_to(ROOT).as_posix()
                result['minimum_budget_witness_changed_chains']=minimum['changed_uavs']
                by={x['mission_id']:x for x in original}
                result['minimum_budget_witness_differences_from_candidate']=[
                    dict(mission_id=x['mission_id'],candidate=by[x['mission_id']],witness=x)
                    for x in minimum['decisions'] if x!=by[x['mission_id']]]
        out.append(result);print(row['attempt_id'],category,flush=True)
    summary=dict(origin='formal_G',target='T6',complete_miss_denominator=len(out),
        evaluation_complete=all(r['terminal_record_saved'] for r in rows),
        planned_first_generation_requests=len(rows),terminal_records=sum(r['terminal_record_saved'] for r in rows),
        schema_complete=sum(r['complete_decisions'] for r in rows),quality=sum(r['reference_quality'] is True for r in rows),
        category_counts=dict(Counter(r['category'] for r in out)),
        trivial_G_witnesses=sum(r['trivial_G_witness'] for r in out),
        providers={p:dict(denominator=sum(r['provider']==p for r in out),
            categories=dict(Counter(r['category'] for r in out if r['provider']==p))) for p in ('deepseek','luna')},
        candidates=out,
        meaning='The same scope permits different missions and values within the same allowed chain set and task budget. Witnesses do not replace submitted decisions.')
    write(ROOT/'analysis/candidate_diagnostics.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('candidates','meaning')},indent=2))
    return summary

if __name__=='__main__':main()
