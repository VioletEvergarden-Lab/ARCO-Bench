"""Rebuild compact physical and legacy-table evidence from stored decisions."""
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'arco_closing_study'
sys.path.insert(0,str(OLD))
from continuous_engine import Engine
from study_common import read,write,csvout

def actions(task,plan):
    base={d['mission_id']:d for d in task['baseline']['decisions']}
    return {d['mission_id']:d for d in plan}

def main():
    out=ROOT/'results/physics'; rows=[]
    for p in sorted((out/'reoptimized').glob('*.json')):
        rid=p.stem; new=read(p); old=read(OLD/'networks/references'/p.name)
        task=read(out/'reoptimized_tasks'/p.name)
        before=actions(task,old['decisions']); after=actions(task,new['decisions'])
        metrics={}
        for label,ds,t in [('old',old['decisions'],read(OLD/'networks/tasks'/p.name)),('new',new['decisions'],task)]:
            s=Engine(t).verify(ds); ev=[e for e in s['events'] if not e['held']]
            metrics.update({label+'_served':len(ev),label+'_charge_blocks':sum(e['charge_blocks'] for e in ev),label+'_energy_wh':sum(e['flight_energy_kwh']*1000 for e in ev),label+'_reserve_margin_wh':min(e['reserve_margin_kwh']*1000 for e in ev),label+'_objective':s['objective']})
        rows.append(dict(record_id=rid,power_increase=.05,optimal=new['optimal'],proved_prefix=new['proved_prefix'],routes_changed_from_old_reference=sum(a['path_id']!=before[mid]['path_id'] for mid,a in after.items() if not a['held'] and not before[mid]['held']),charges_changed_from_old_reference=sum(a['charge_blocks']!=before[mid]['charge_blocks'] for mid,a in after.items()),changed_decisions=[mid for mid in after if after[mid]!=before[mid]],**metrics))
    csvout(out/'repair_comparison.csv',rows);write(out/'repair_comparison.json',rows)
    pkg=ROOT.parent.parent
    master=[json.loads(l) for l in (pkg/'results/current/MASTER.jsonl').read_text(encoding='utf-8').splitlines()]
    a=[r for r in master if r['source']=='policy']; public=read(ROOT.parent/'arco_codex_research_20260925/source_tables/summary.json')['policy_public']
    groups={}
    for group in sorted({r['mechanism'] for r in a}):
        sub=[r for r in a if r['mechanism']==group]
        groups[group]=dict(admissible=sum(r['formal'] and r['schema'] for r in sub),reference_quality=sum(r['reference_quality'] for r in sub))
    archived=dict(admissible=sum(r['formal'] and r['schema'] for r in a),reference_quality=sum(r['reference_quality'] for r in a),construct_fidelity=sum(r['construct_fidelity'] for r in a),groups=groups)
    result=dict(archived=archived,public_G=public,S4_S5_aggregates_equal=archived==public,note='Counts agree in S4/S5, but the plans differ on Core-051 and total served missions differ (426 versus 427). The shared row describes these aggregates only.')
    write(ROOT/'results/core_table_check.json',result)
    print(json.dumps(dict(physics_repairs=rows,core_table_check=result),indent=2))

if __name__=='__main__': main()
