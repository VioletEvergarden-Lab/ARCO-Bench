"""Copy the exact original counterfactual definition and existing public solves."""
import argparse
from common import *

def remap(value,mapping):
    if isinstance(value,str): return mapping.get(value,value)
    if isinstance(value,list): return [remap(v,mapping) for v in value]
    if isinstance(value,dict): return {mapping.get(k,k):remap(v,mapping) for k,v in value.items()}
    return value

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-repo',type=Path,required=True); ap.add_argument('--public-solves',type=Path,required=True); args=ap.parse_args()
    prior={r['record_id']:r for r in jl(args.public_solves)}; rows=[]
    for path in sorted((P/'data/private/evaluator_records').glob('CA12_CORE_*.json')):
        p=read(path); rid=p['record_id']; cpath=args.source_repo/'analysis/integrated_repair_candidate_a_v12_multitemplate_structural_successor_v1/prospective_population_v1/private'/f"{p['source_cell_id']}.json"
        c=read(cpath); mapping={v:k for k,v in p['public_to_internal_id'].items()}; old=prior[rid]
        resource=remap(c['coupling_trace']['resource'],mapping)
        task=read(P/'data/public/records'/f'{rid}.json'); relaxed=rt_intervention(task,resource)
        pair=c['decoupling_counterfactual'].get('pair',{})
        witnesses=[{'source':name,'decisions':remap(pair[key]['decisions'],mapping)} for name,key in (('original_relaxed_target','target_plan'),('original_relaxed_competitor','alternative_plan')) if key in pair]
        dec=old['decoupled_check']
        rows.append({'record_id':rid,'resource':resource,'relaxed_intervention':relaxed,'original_witnesses':witnesses,'existing_public_relaxed_optimum':{'decisions':remap(dec['target_decisions'],mapping),'solver_objective':dec['target_vector'],'status':dec['status'],'mip_gap':dec['mip_gap']},'existing_public_base_objective':old['new_verifier_vector'],'coupled_gap':old['competitor_check']['gap'],'relaxed_gap':dec['gap'],'gap_tier':c['coupled_pair_certificate']['target_layer_name'],'competitor_definition':{'mission_id':remap(c['coupled_pair_certificate']['semantic_distinction_mission_id'],mapping),'target_tier':c['coupled_pair_certificate']['target_layer_name']},'metadata':p['metadata'],'selected_pair':remap(p['selected_pair'],mapping),'source_cell_id':p['source_cell_id']})
    write(HERE/'capacity/inputs.json',{'source':'Original coupling_trace and decoupled_intervention; public-domain reference_recomputation from 2026-09-18','rows':rows})
    print('Saved exact definitions and existing public optima for',len(rows),'tasks')

def rt_intervention(task,resource):
    import copy
    value=copy.deepcopy(task['intervention']); kind=resource['kind']; node=resource['node']
    key=kind+'_capacity_overrides'; id_key='corridor_id' if kind=='corridor' else 'vertiport_id'
    # This is the original bridge rule: remove overrides on this resource.
    value[key]=[r for r in value[key] if r[id_key]!=node]
    value['operations']=[r for r in value.get('operations',[]) if r.get('type')!='mixed_fleet_coupling_capacity']
    value.pop('intervention_sha256',None)
    return value

if __name__=='__main__': main()
