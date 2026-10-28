"""Add fixed R3 candidates to the six existing preference reference sets."""
from collections import Counter
from common import *

def charge_components(task,base,alternative):
    a,_,_=event_ledger.ledger(task,base); b,_,_=event_ledger.ledger(task,alternative)
    names=('route_changes','departure_shift_slots','charge_activation_changes','charge_block_change_abs','urgent_tardiness_min','routine_tardiness_min','departure_after_release_min','charge_duration_min','flight_energy_kwh')
    delta={k:b.get(k,0)-a.get(k,0) for k in names}
    delta['L3_constant']=20*delta['route_changes']+delta['departure_shift_slots']+2*delta['charge_block_change_abs']
    delta['L3_charge_coefficient']=delta['charge_activation_changes']
    delta['L5_delta']=delta['departure_after_release_min']+delta['charge_duration_min']
    return delta

def main():
    scored=read(R/'public_preferences/scored_candidates.json'); r3=decisions(R/'local_repair/responses.jsonl'); tasks={p.stem:read(p) for p in (P/'data/public/records').glob('CA12_CORE_*.json')}
    detail=[]; counts={s:Counter() for s in SETTINGS}
    for row in scored['tasks']:
        setting=row['setting']; rid=row['record_id']; c=counts[setting]; ref=row['reference']; objs=dict(row['candidate_objectives']); qs=dict(row['candidate_quality'])
        objs['R3']=objective(tasks[rid],r3[rid],setting); qs['R3']=quality(objs['R3'],ref); c['R3_quality']+=qs['R3']; selected={}
        for model in ('deepseek_complete','luna_complete'):
            source='R3' if objs[model] is None or compare(objs['R3'],objs[model],setting)<=0 else model
            selected[model]=source; c[model+'_R3_selected_quality']+=qs[source]; c[model+'_R3_selected_model']+=source==model
        c['four_source_any_quality']+=any(qs[s] for s in ('policy_public','R3','deepseek_complete','luna_complete'))
        detail.append({'record_id':rid,'setting':setting,'R3_objective':objs['R3'],'R3_quality':qs['R3'],'selected':selected,'four_source_any_quality':any(qs[s] for s in ('policy_public','R3','deepseek_complete','luna_complete'))})
    summary=[dict(setting=s,**counts[s]) for s in SETTINGS]
    out=HERE/'preferences'; write(out/'fixed_pool.json',{'summary':summary,'tasks':detail}); csvout(out/'fixed_pool.csv',summary)
    solves={(r['record_id'],r['setting']):r['decisions'] for r in read(R/'public_preferences/solves.json')['rows']}; delta=[]
    for rid,task in sorted(tasks.items()):
        if diff(solves[rid,'base'],solves[rid,'charge_on_12']):
            delta.append(dict(record_id=rid,**charge_components(task,solves[rid,'base'],solves[rid,'charge_on_12'])))
    csvout(out/'charge_switch_components.csv',delta); write(out/'charge_switch_components.json',delta)
    print(json.dumps(summary,indent=2)); print('Charge switch component rows:',len(delta))

if __name__=='__main__': main()
