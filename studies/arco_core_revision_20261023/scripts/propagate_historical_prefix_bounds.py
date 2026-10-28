"""No solves: recover the exact tier of archived radius exclusions."""
import math
from run_origin_target_panel import ROOT,WS,OLD,read,write,rel,digest,signature,canonical_plan,changes,TIERS,QUALITY_TOL,aggregate

def check_radius(case_folder,evidence):
    task=read(case_folder/'task.json');target=read(case_folder/'reference.json')['objective'];origin=read(case_folder/'origins.json')['decisions']['G']
    path=WS/evidence['source'];run=read(path);nh=run['neighborhoods'][0]
    assert signature(canonical_plan(nh['center_decisions'],task))==signature(canonical_plan(origin,task))
    assert nh['index']==1 and int(nh['radius'])==evidence['radius']
    index=evidence['tier_index_zero_based'];assert 0<=index<=3
    phases={p['tier']:p for p in run['phases'] if p.get('neighborhood')==1}
    checked=[]
    for i,tier in enumerate(TIERS[:index+1]):
        p=phases[tier];assert p['proved'] and p.get('lower_bound') is not None
        if i<index:
            assert abs(p['lower_bound']-target[tier])<=QUALITY_TOL[i]+1e-10
            assert abs(p['upper_bound']-target[tier])<=QUALITY_TOL[i]+1e-10
        else:assert p['lower_bound']>target[tier]+QUALITY_TOL[i]+1e-10
        checked.append(dict(tier=tier,lower=p['lower_bound'],upper=p.get('upper_bound'),target=target[tier]))
    return dict(record_id=task['record_id'],target_prefix=index+1,mission_lower_bound=int(nh['radius'])+1,
                source=evidence['source'],source_sha256=digest(path),radius=int(nh['radius']),phase_checks=checked,
                original_evidence=evidence)

def main():
    historical=read(OLD/'analysis/e1_results.json');all_proofs=[];changes_log=[]
    for item in read(ROOT/'analysis/selection_plan.json')['conditions']:
        folder=ROOT/'runs/origin_target'/item['record_id']
        if not (folder/'complete.json').exists():continue
        proofs=[];seen=set()
        for q in historical:
            if q['record_id']!=item['record_id']:continue
            for e in q['evidence']:
                if e.get('kind')!='G_centered_radius_exclusion':continue
                key=(e['source'],e['tier_index_zero_based'],e['radius'])
                if key in seen:continue
                seen.add(key);proofs.append(check_radius(folder,e))
        all_proofs.extend(proofs)
        panel=read(folder/'panel.json');origins=read(folder/'origins.json')['decisions'];task=read(folder/'task.json')
        lengths=sorted([sum(m['uav_id']==u['uav_id'] for m in task['missions']) for u in task['fleet']],reverse=True)
        for row in panel:
            if row['metric']!='missions':continue
            delta=len(changes(origins[row['origin']],origins['G'])[0])
            for proof in proofs:
                if proof['target_prefix']>row['target_prefix']:continue
                lower=max(0,proof['mission_lower_bound']-delta)
                if lower>row['lower_bound']:
                    changes_log.append(dict(record_id=row['record_id'],origin=row['origin'],target_prefix=row['target_prefix'],metric='missions',old_lower=row['lower_bound'],new_lower=lower,source=proof['source']))
                    row['lower_bound']=lower;row['lower_evidence'].append(dict(kind='archived_radius_prefix_exclusion',lower=lower,origin_distance=delta,proof=proof))
        for name in ('G','Gprime'):
            for metric in ('missions','chains'):
                previous=None
                for row in sorted([r for r in panel if r['origin']==name and r['metric']==metric],key=lambda r:r['target_prefix']):
                    if metric=='chains':
                        mission=next(r for r in panel if r['origin']==name and r['metric']=='missions' and r['target_prefix']==row['target_prefix'])
                        cover=next(k for k in range(len(lengths)+1) if sum(lengths[:k])>=mission['lower_bound'])
                        if cover>row['lower_bound']:
                            row['lower_bound']=cover;row['lower_evidence'].append(dict(kind='chain_length_cover',lower=cover,mission_lower=mission['lower_bound']))
                    if previous and previous['lower_bound']>row['lower_bound']:
                        row['lower_bound']=previous['lower_bound'];row['lower_evidence'].append(dict(kind='target_nesting_lower',lower=row['lower_bound'],source_prefix=previous['target_prefix']))
                    assert row['lower_bound']<=row['upper_bound']
                    row['status']='closed' if row['lower_bound']==row['upper_bound'] else 'open';previous=row
        write(folder/'panel.json',panel)
        complete=read(folder/'complete.json');complete.update(closed=sum(r['status']=='closed' for r in panel),open=sum(r['status']=='open' for r in panel),offline_prefix_propagation=True);write(folder/'complete.json',complete)
        joints=read(folder/'joint_panel.json')
        for j in joints:
            m=next(r for r in panel if r['origin']==j['origin'] and r['target_prefix']==j['target_prefix'] and r['metric']=='missions')
            c=next(r for r in panel if r['origin']==j['origin'] and r['target_prefix']==j['target_prefix'] and r['metric']=='chains')
            j.update(mission_bounds=[m['lower_bound'],m['upper_bound']],chain_bounds=[c['lower_bound'],c['upper_bound']],marginals_closed=m['status']==c['status']=='closed')
            if j['marginals_closed'] and j['feasible'] is True:j['status']='jointly_attained'
            elif j['marginals_closed'] and j['status']=='marginal_bounds_open':j['status']='joint_unresolved_after_offline_bound_tightening'
        write(folder/'joint_panel.json',joints)
    write(ROOT/'analysis/historical_prefix_exclusions.json',dict(new_solves=0,proofs=all_proofs,tightenings=changes_log));aggregate()
    print('Historical prefix exclusions',len(all_proofs),'task-bound tightenings',len(changes_log),'new solves 0')

if __name__=='__main__':main()
