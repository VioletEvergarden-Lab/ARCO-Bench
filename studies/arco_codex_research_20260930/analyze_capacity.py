"""Use complete archived public-domain optima for the original capacity change."""
import copy
from collections import Counter
from common import *

def main():
    rt=Runtime(); inputs=read(HERE/'capacity/inputs.json')['rows']; refs={r['record_id']:r for r in jl(P/'references/public_domain.jsonl')}
    rows=[]; plans=[]; events=[]; resources=[]
    for item in inputs:
        rid=item['record_id']; task=read(P/'data/public/records'/f'{rid}.json'); relaxed=copy.deepcopy(task); relaxed['intervention']=item['relaxed_intervention']
        optimum=item['existing_public_relaxed_optimum']; ds=optimum['decisions']; score=rt.evaluate(relaxed,ds)
        if not score['formal_feasible']: raise RuntimeError((rid,score))
        vector=score['objective_vector']; exact=optimum['solver_objective']; base=refs[rid]['objective']
        if any(abs(vector[k]-exact[k])>(1e-6 if k==TIERS[-1] else 1e-6) for k in TIERS): raise RuntimeError(('stored objective differs',rid,vector,exact))
        if not quality(item['existing_public_base_objective'],base): raise RuntimeError(('base mismatch',rid))
        rebound=rt.evaluate(task,ds); witness=[]
        for w in item['original_witnesses']:
            # Original construction witnesses remain separate from the public optimum.
            restored=rt.evaluate(task,w['decisions']); relaxed_check=rt.evaluate(relaxed,w['decisions'])
            witness.append({'source':w['source'],'relaxed_valid':relaxed_check['formal_feasible'],'restored_valid':restored['formal_feasible'],'restored_errors':restored['formal_error_codes']})
        first=next((i+1 for i,n in enumerate(TIERS) if abs(vector[n]-base[n])>(1e-4 if i==5 else 0)),None)
        changes=diff(refs[rid]['decisions'],ds)
        rows.append({'task':rid,'resource':item['resource'],'base_objective':base,'relaxed_objective':vector,'first_changed_layer':first,'selected_optimum_decisions_changed':bool(changes),'changed_missions':changes,'relaxed_optimum_valid_under_original_capacity':bool(rebound['formal_feasible']),'restored_optimum_errors':rebound['formal_error_codes'],'original_witness_restoration':witness,'designated_gap_changed':abs(item['coupled_gap']-item['relaxed_gap'])>=(1e-3 if item['gap_tier']==TIERS[-1] else 1),'coupled_gap':item['coupled_gap'],'relaxed_gap':item['relaxed_gap'],'gap_tier':item['gap_tier']})
        plans.append({'record_id':rid,'decisions':ds,'objective':vector,'intervention':relaxed['intervention']})
        for name,t,d in [('base',task,refs[rid]['decisions']),('relaxed_optimum',relaxed,ds)]:
            _,_,ev=event_ledger.ledger(t,d); events.extend(dict(e,source=name) for e in ev); resources.extend(occupancy(t,d,name))
    out=HERE/'capacity'; csvout(out/'capacity_optimum_effects.csv',rows); write(out/'results.json',rows); jsonl(out/'relaxed_optima.jsonl',plans)
    csvout(out/'mission_events.csv',events); csvout(out/'resource_events.csv',resources)
    summary={'tasks':len(rows),'optimum_changed':sum(r['first_changed_layer'] is not None for r in rows),'first_change_distribution':dict(Counter(r['first_changed_layer'] for r in rows)),'selected_optimum_changed':sum(r['selected_optimum_decisions_changed'] for r in rows),'relaxed_optimum_valid_under_original':sum(r['relaxed_optimum_valid_under_original_capacity'] for r in rows),'designated_gap_changed':sum(r['designated_gap_changed'] for r in rows),'original_witness_rejected_on_restoration':sum(any(w['relaxed_valid'] and not w['restored_valid'] for w in r['original_witness_restoration']) for r in rows),'reference_solves_reused':72}
    write(out/'summary.json',summary); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
