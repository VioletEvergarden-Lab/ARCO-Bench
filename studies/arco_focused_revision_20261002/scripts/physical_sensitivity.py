"""Fixed-decision phase-power replay and three prespecified repairs; no API calls."""
from pathlib import Path
import argparse, copy, csv, json, sys
ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'arco_closing_study'
sys.path.insert(0, str(OLD))
import continuous_engine as ce
from study_common import read, write, csvout
ce.HERE = ROOT / 'results' / 'physics'
OUT = ce.HERE

def stressed_task(task, fraction):
    t = copy.deepcopy(task)
    t['model']['power_coefficients'] = {k: [v*(1+fraction) for v in pair] for k,pair in t['model']['power_coefficients'].items()}
    for m in t['missions']:
        for p in m['paths'] + ([m['incoming']] if m.get('incoming') else []):
            p.pop('energy_kwh', None)
    return t

def candidates():
    rows = [r for r in read(OLD/'evaluation/scores.json') if r['layer']=='network']
    for path in sorted((OLD/'networks/references').glob('NET_*.json')):
        ref = read(path)
        rows.append(dict(record_id=path.stem, source='Reference', admissible=True, decisions=ref['decisions']))
    return rows

def replay():
    rows=[]; exclusions=[]; chosen={}
    for r in candidates():
        if not r['admissible']:
            exclusions.append(dict(record_id=r['record_id'],source=r['source'],status=r['status']))
            continue
        task=read(OLD/'networks/tasks'/f"{r['record_id']}.json")
        baseline=ce.Engine(task).verify(r['decisions'])
        assert baseline['admissible'], (r['record_id'],r['source'])
        for delta in [0.,.02,.05,.10]:
            t=stressed_task(task,delta); score=ce.Engine(t).verify(r['decisions'])
            ev=[x for x in score['events'] if not x['held']]
            row=dict(record_id=r['record_id'],network_id=r['record_id'][:-2],scale=r['record_id'].split('_')[1][0],source=r['source'],power_increase=delta,admissible=score['admissible'],errors=';'.join(score['errors']),served=len(ev),served_mission_ids=';'.join(x['mission_id'] for x in ev),flight_energy_wh=sum(x['flight_energy_kwh']*1000 for x in ev),minimum_reserve_margin_wh=min(x['reserve_margin_kwh']*1000 for x in ev),minimum_soc_wh=min(x['soc_arrival_kwh']*1000 for x in ev))
            rows.append(row)
            if delta==.05 and 'SOC_RESERVE_BEFORE_CHARGE' in score['errors']:
                scale=row['scale']; chosen[scale]=min(chosen.get(scale,r['record_id']),r['record_id'])
    csvout(OUT/'fixed_plan_stress.csv',rows); write(OUT/'baseline_exclusions.json',exclusions)
    write(OUT/'repair_selection.json',dict(rule='First task ID within each scale with any originally admissible source violating reserve at +5%; sources are Reference, G, R4, DeepSeek, Luna',tasks=chosen))
    summary=[]
    for source in ['Reference','G','R4','deepseek','luna']:
        for delta in [0.,.02,.05,.10]:
            group=[r for r in rows if r['source']==source and r['power_increase']==delta]
            summary.append(dict(source=source,power_increase=delta,available_plans=len(group),admissible=sum(r['admissible'] for r in group),minimum_reserve_margin_wh=min(r['minimum_reserve_margin_wh'] for r in group)))
    csvout(OUT/'stress_summary.csv',summary); print(json.dumps(summary,indent=2))

def repairs():
    for scale,rid in read(OUT/'repair_selection.json')['tasks'].items():
        dest=OUT/'reoptimized'/f'{rid}.json'
        if dest.exists(): continue
        task=read(OLD/'networks/tasks'/f'{rid}.json'); task=stressed_task(task,.05)
        result=ce.Engine(task).solve(budget=1800)
        write(OUT/'reoptimized_tasks'/f'{rid}.json',task); write(dest,result)
        print('REPAIR',rid,result['optimal'],result['proved_prefix'],flush=True)

def window():
    rid='NET_L04_A'; target=OUT/'window_L04_A.json'
    if target.exists(): return
    task=read(OLD/'networks/tasks'/f'{rid}.json'); task['timing']['pad_window_min']=1.; task['timing']['resource_window_min']=.5
    eng=ce.Engine(task); ref=eng.solve(budget=1800)
    rows=[]
    for r in candidates():
        if r['record_id']!=rid or not r.get('decisions'): continue
        s=eng.verify(r['decisions'])
        rows.append(dict(source=r['source'],originally_admissible=r['admissible'],admissible=s['admissible'],errors=s['errors'],objective=s['objective'],quality=bool(s['admissible'] and ref['optimal'] and ce.quality(s['objective'],ref['objective'])),events=s['events']))
    write(OUT/'window_L04_A_task.json',task); write(target,dict(record_id=rid,reference=ref,candidates=rows,pad_window_min=1,departure_grid_min=task['timing']['departure_grid_min'],interval_window_min=.5))
    print('WINDOW',ref['optimal'],[(r['source'],r['admissible'],r['quality']) for r in rows],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['replay','repairs','window']); a=p.parse_args()
    dict(replay=replay,repairs=repairs,window=window)[a.mode]()
