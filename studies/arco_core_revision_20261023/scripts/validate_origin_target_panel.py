"""Independent event replay and arithmetic audit of every reported lower bound."""
from collections import Counter
import math
from run_origin_target_panel import ROOT,WS,OLD,read,write,rel,digest,signature,canonical_plan,changes,distance,target_met,TIERS,QUALITY_TOL,ce,alternate_greedy
from propagate_historical_prefix_bounds import check_radius

def main():
    plan=read(ROOT/'analysis/selection_plan.json');panel=read(ROOT/'analysis/origin_target_panel.json');joints=read(ROOT/'analysis/origin_target_joint.json')
    assert len(panel)==128 and len(joints)==64
    assert len({(q['record_id'],q['origin'],q['target_prefix'],q['metric']) for q in panel})==128
    for source in plan['historical_sources']:assert digest(WS/source['path'])==source['sha256']
    history=read(OLD/'analysis/e1_results.json');proof_counts=Counter();replayed=[];case_checks=[];raw_count=0;historical_audits=[];negative_joint_audits=[]
    for selected in plan['conditions']:
        rid=selected['record_id'];folder=ROOT/'runs/origin_target'/rid;task=read(folder/'task.json');ref=read(folder/'reference.json');origins_file=read(folder/'origins.json');origins=origins_file['decisions'];engine=ce.Engine(task)
        assert digest(WS/origins_file['task_source'])==origins_file['task_sha256']
        assert digest(WS/origins_file['reference_source'])==origins_file['reference_sha256']
        assert task==read(WS/origins_file['task_source']) and ref==read(WS/origins_file['reference_source'])
        assert signature(alternate_greedy(ce.Engine(task)))==signature(origins['Gprime'])
        cache={}
        def verify(ds,source):
            ds=canonical_plan(ds,task);key=signature(ds)
            if key not in cache:
                score=engine.verify(ds);assert score['admissible'],(rid,source,score['errors']);cache[key]=score
                replayed.append(dict(record_id=rid,source=source,plan_sha256=__import__('hashlib').sha256(key.encode()).hexdigest(),admissible=True))
            return cache[key]
        refscore=verify(ref['decisions'],'reference');assert ref['optimal'] and ref['proved_prefix']==6
        assert target_met(refscore['objective'],ref['objective'],6)
        for name,ds in origins.items():assert verify(ds,name)['objective']==origins_file['verification'][name]['objective']
        def audited_radius(evidence):
            archived=read(WS/evidence['source'])
            assert archived['record_id']==rid and archived['task_sha256']==origins_file['task_sha256']
            assert archived['quality_tolerance']==list(QUALITY_TOL)
            return check_radius(folder,evidence)
        def full_scalar_raw(path):
            r=read(path);assert r['record_id']==rid and r['target_mode']=='match'
            assert r['minimize'] in ('missions','chains')
            assert set(r['allowed_uavs'])==set(engine.fleet)
            assert r['task_budget'] is None and r['chain_budget'] is None and not r['no_good_supports']
            assert target_met(r['target_objective'],ref['objective'],6)
            assert r['quality_tolerance']==list(QUALITY_TOL)
            if r.get('lower_bound') is not None:
                base=0 if target_met(verify(origins[r['origin_name']],r['origin_name'])['objective'],ref['objective'],r['target_prefix']) else 1
                dual=r.get('raw_dual_bound');supported=max(base,math.ceil(dual-1e-6)) if dual is not None else base
                assert r['lower_bound']<=supported,(str(path),r['lower_bound'],supported)
            return r
        audited={}
        def audit_historical_summary(h):
            """Audit a providing raw certificate, not just equality to e1 summary."""
            key=(h['target_prefix'],h['metric'])
            if key in audited:return audited[key]
            prefix,metric=key;provided=[]
            base=0 if target_met(verify(origins['G'],'G')['objective'],ref['objective'],prefix) else 1
            provided.append(dict(kind='origin_membership',lower=base))
            for e in h['evidence']:
                if e['kind']=='G_centered_radius_exclusion':
                    proof=audited_radius(e);assert proof['target_prefix']<=prefix
                    if metric=='missions':provided.append(dict(kind='raw_neighborhood_tier_exclusion',lower=proof['mission_lower_bound'],source=proof['source'],source_sha256=proof['source_sha256']))
            # Direct complete-domain query certificates may be an alternative
            # providing proof to an older derived chain-necessity summary.
            for dirname in ('development','e1','e1_extensions'):
                for path in (OLD/'runs'/dirname).glob(rid+'__*.json'):
                    r=read(path)
                    if r.get('origin_name')!='G' or r.get('minimize')!=metric or r.get('target_prefix',7)>prefix:continue
                    if r.get('target_mode','match')!='match' or r.get('task_budget') is not None or r.get('chain_budget') is not None or r.get('no_good_supports'):continue
                    if set(r.get('allowed_uavs',[]))!=set(engine.fleet) or r.get('lower_bound') is None:continue
                    r=full_scalar_raw(path)
                    provided.append(dict(kind='raw_unrestricted_query_bound',lower=r['lower_bound'],prefix=r['target_prefix'],source=rel(path),source_sha256=digest(path)))
            if metric=='chains':
                hm=next(x for x in history if x['record_id']==rid and x['target_prefix']==prefix and x['metric']=='missions')
                ma=audit_historical_summary(hm)
                lengths_here=sorted([len(c) for c in engine.chains.values()],reverse=True)
                cover=next(k for k in range(len(lengths_here)+1) if sum(lengths_here[:k])>=ma['verified_lower'])
                provided.append(dict(kind='chain_length_cover_of_audited_mission_bound',lower=cover,mission_lower=ma['verified_lower']))
            strongest=max(x['lower'] for x in provided)
            assert strongest>=h['lower_bound'],(rid,key,h['lower_bound'],provided)
            audit=dict(record_id=rid,target_prefix=prefix,metric=metric,reported_lower=h['lower_bound'],verified_lower=h['lower_bound'],
                       supporting_records=[x for x in provided if x['lower']>=h['lower_bound']],provenance='underlying query scope/dual bound or neighborhood tier checked; no reoptimization')
            audited[key]=audit;historical_audits.append(audit);return audit
        rows=[r for r in panel if r['record_id']==rid]
        lengths=sorted([len(c) for c in engine.chains.values()],reverse=True)
        for row in rows:
            name=row['origin'];prefix=row['target_prefix'];metric=row['metric'];origin=origins[name]
            score=verify(row['decisions'],f'{name}/T{prefix}/{metric}');assert target_met(score['objective'],ref['objective'],prefix)
            assert target_met(score['objective'],row['objective'],6)
            ms,us=changes(row['decisions'],origin)
            assert ms==row['changed_missions'] and us==row['changed_uavs']
            assert len(ms)==row['mission_changes'] and len(us)==row['chain_changes']
            assert (len(ms) if metric=='missions' else len(us))==row['upper_bound']
            assert row['status']==('closed' if row['lower_bound']==row['upper_bound'] else 'open')
            justified=[]
            for e in row['lower_evidence']:
                kind=e['kind'];proof_counts[kind]+=1
                if kind=='origin_membership':
                    expected=0 if target_met(verify(origin,name)['objective'],ref['objective'],prefix) else 1
                elif kind in ('historical_G_bound','triangle_inequality_from_G'):
                    source,sep,frag=e['source'].partition('#')
                    if sep:
                        h=next(h for h in history if h['record_id']==rid and h['target_prefix']==e['prefix'] and h['metric']==metric)
                        audit_historical_summary(h)
                        raw_lower=h['lower_bound']
                    else:
                        h=full_scalar_raw(WS/source);assert h['origin_name']=='G' and h['target_prefix']==e['prefix'] and h['minimize']==metric;raw_lower=h['lower_bound']
                    assert e['prefix']<=prefix and e['metric']==metric
                    assert raw_lower==e['historical_lower']
                    delta=distance(origin,origins['G'],metric);assert delta==e['origin_distance'];expected=max(0,raw_lower-delta)
                elif kind in ('new_bound','triangle_inequality_new_origin'):
                    h=full_scalar_raw(WS/e['source']);assert h['target_prefix']<=prefix and h['minimize']==metric
                    delta=distance(origin,origins[h['origin_name']],metric);assert delta==e['origin_distance'];expected=max(0,h['lower_bound']-delta)
                elif kind=='chain_length_cover':
                    assert metric=='chains';m=next(r for r in rows if r['origin']==name and r['target_prefix']==prefix and r['metric']=='missions')
                    assert e['mission_lower']<=m['lower_bound'];expected=next(k for k in range(len(lengths)+1) if sum(lengths[:k])>=e['mission_lower'])
                elif kind=='archived_radius_prefix_exclusion':
                    assert metric=='missions';p=audited_radius(e['proof']['original_evidence'])
                    assert p==e['proof'] and p['target_prefix']<=prefix
                    delta=distance(origin,origins['G'],'missions');assert delta==e['origin_distance'];expected=max(0,p['mission_lower_bound']-delta)
                elif kind=='target_nesting_lower':
                    assert e['source_prefix']<prefix
                    weak=next(r for r in rows if r['origin']==name and r['metric']==metric and r['target_prefix']==e['source_prefix'])
                    assert e['lower']<=weak['lower_bound'];expected=e['lower']
                else:raise ValueError(('unvalidated proof type',kind))
                assert expected==e['lower'],(rid,name,prefix,metric,e,expected)
                justified.append(expected)
            assert max(justified)==row['lower_bound']<=row['upper_bound']
        for j in [x for x in joints if x['record_id']==rid]:
            m=next(r for r in rows if (r['origin'],r['target_prefix'],r['metric'])==(j['origin'],j['target_prefix'],'missions'))
            c=next(r for r in rows if (r['origin'],r['target_prefix'],r['metric'])==(j['origin'],j['target_prefix'],'chains'))
            assert j['mission_bounds']==[m['lower_bound'],m['upper_bound']] and j['chain_bounds']==[c['lower_bound'],c['upper_bound']]
            assert j['marginals_closed']==(m['status']==c['status']=='closed')
            if j['feasible'] is True:
                s=verify(j['decisions'],f"joint/{j['origin']}/T{j['target_prefix']}")
                assert target_met(s['objective'],ref['objective'],j['target_prefix'])
                ms,us=changes(j['decisions'],origins[j['origin']]);assert len(ms)<=j['query_budget'][0] and len(us)<=j['query_budget'][1]
            elif j['feasible'] is False:
                h=read(WS/j['source']);assert h['feasible'] is False and h['status']=='infeasible'
                assert h['record_id']==rid and h['origin_name'] in origins
                assert h['task_budget']==j['query_budget'][0] and h['chain_budget']==j['query_budget'][1]
                assert h['target_prefix']==j['target_prefix'] and target_met(h['target_objective'],ref['objective'],6)
                assert signature(origins[h['origin_name']])==signature(origins[j['origin']])
                assert set(h['allowed_uavs'])==set(engine.fleet) and not h['no_good_supports']
                assert h['target_mode']=='match' and h['quality_tolerance']==list(QUALITY_TOL)
                negative_joint_audits.append(dict(record_id=rid,origin=j['origin'],target_prefix=j['target_prefix'],
                    query_budget=j['query_budget'],source=j['source'],source_sha256=digest(WS/j['source']),
                    same_task_origin_target=True,all_chains_allowed=True,no_good_supports=[],quality_tolerance=list(QUALITY_TOL),
                    provenance='archived solver infeasibility and query semantics checked; no reoptimization'))
        for kind in ('queries','joint'):
            for path in (folder/kind).glob('*.json'):
                r=read(path);raw_count+=1
                if kind=='queries':full_scalar_raw(path)
                if r.get('decisions'):
                    score=verify(r['decisions'],rel(path));assert target_met(score['objective'],ref['objective'],r['target_prefix'])
                    ms,us=changes(r['decisions'],origins[r['origin_name']]);assert ms==r['changed_missions'] and us==r['changed_uavs']
                    assert set(us)<=set(r['allowed_uavs'])
                    assert r['task_budget'] is None or len(ms)<=r['task_budget']
                    assert r['chain_budget'] is None or len(us)<=r['chain_budget']
        case_checks.append(dict(record_id=rid,unique_plans_replayed=len(cache),origin_identical=signature(origins['G'])==signature(origins['Gprime']),main_positions=len(rows),passed=True))
    result=dict(status='passed',conditions=8,scalar_positions=128,joint_positions=64,new_query_records_checked=raw_count,
                unique_plans_replayed=len(replayed),proof_counts=dict(proof_counts),cases=case_checks,plan_records=replayed,
                solver_calls_during_validation=0,historical_source_hashes_unchanged=True,task_reference_hashes_unchanged=True,
                Gprime_reproduced_without_reference=True,
                historical_summary_bound_audits=historical_audits,
                negative_joint_certificate_audits=negative_joint_audits,
                lower_bound_checks='membership; unrestricted same-target historical/new bounds; prefix nesting; triangle inequalities; chain-length covering; exact archived exclusion stages')
    write(ROOT/'analysis/origin_target_validation.json',result)
    print({k:v for k,v in result.items() if k not in ('cases','plan_records','historical_summary_bound_audits','negative_joint_certificate_audits')})
    print('Historical summary certificates checked:',len(historical_audits),'negative joint certificates checked:',len(negative_joint_audits))

if __name__=='__main__':main()
