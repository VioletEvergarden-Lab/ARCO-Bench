"""Offline evaluation of saved online traces; never feeds reference to solver."""
from pathlib import Path
import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from optimization_online import ROOT, TIERS, QUALITY_TOL, compare, quality, METHODS


def csvout(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)


def first(events, test):
    return next((e['available_seconds'] for e in events if e['admissible'] and e['within_budget'] and test(e['objective'])), None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=Path, default=Path(__file__).resolve().parents[1]/'results/comparison/runs')
    p.add_argument('--references', type=Path, default=ROOT/'arco_closing_study/networks/references')
    p.add_argument('--expected', type=int, default=36)
    args = p.parse_args()
    out = args.runs.parent if args.runs.name == 'runs' else args.runs
    rows, slices, events, indexed = [], [], [], {}
    for path in sorted(args.runs.glob('*__*.json')):
        run = json.loads(path.read_text(encoding='utf-8'))
        rid, method = run['record_id'], run['method']
        refpath = args.references/f'{rid}.json'
        ref = json.loads(refpath.read_text(encoding='utf-8')) if refpath.exists() else {}
        # Some downstream reference files wrap the solve result.
        if 'reference' in ref:
            ref = ref['reference']
        reference = ref.get('objective')
        certified = bool(ref.get('optimal') or ref.get('global_optimal'))
        ref_prefix = 6 if certified else int(ref.get('proved_prefix', 0))
        service_certified = ref_prefix >= 2
        service = lambda v: bool(service_certified and all(abs(v[k]-reference[k])<=1e-9 for k in TIERS[:2]))
        match = lambda v: bool(certified and quality(v, reference))
        first_feasible = first(run['events'], lambda v: True)
        first_service = first(run['events'], service)
        first_quality = first(run['events'], match)
        first_global_proof = next((e['available_seconds'] for e in run['proof_events'] if e['proved_prefix']==6 and e['scope']=='global'), None)
        objective = run['objective']
        miss = next((k for k,t in zip(TIERS,QUALITY_TOL) if abs(objective[k]-reference[k])>t+1e-10), None) if objective and certified else None
        row = {'record_id':rid, 'method':method, 'budget_seconds':run['budget_seconds'],
               'admissible':run['admissible'], 'reference_certified':certified,
               'reference_service_certified':service_certified,
               'service_target':service(objective) if objective else False,
               'reference_quality':match(objective) if objective else False,
               'first_feasible_seconds':first_feasible, 'first_service_seconds':first_service,
               'first_reference_quality_seconds':first_quality,
               'full_proof_seconds':first_global_proof,
               'total_seconds':run['total_seconds'], 'global_optimal':run['global_optimal'],
               'first_miss':miss, 'first_gap':objective[miss]-reference[miss] if miss else None,
               'objective':objective, **(run.get('metrics') or {}),
               'callback_count':run['callback_count'], 'validation_seconds':run['validation_seconds'],
               'callback_seconds':run.get('callback_seconds'),
               'neighborhoods':len(run['neighborhoods']), 'reused_from':run.get('reused_from')}
        rows.append(row)
        indexed[rid,method] = (row,run)
        for e in run['events']:
            events.append({'record_id':rid,'method':method,**e})
        for budget in (30,60,180,300,600):
            if budget > run['budget_seconds']:
                continue
            arrived = [e for e in run['improvements'] if e['available_seconds']<=budget]
            best = arrived[-1] if arrived else None
            slices.append({'record_id':rid,'method':method,'seconds':budget,
                           'admissible':best is not None,
                           'reference_certified':certified,
                           'service_target':service(best['objective']) if best else False,
                           'reference_quality':match(best['objective']) if best else False,
                           'urgent_served':best.get('urgent_served') if best else None,
                           'total_served':best.get('total_served') if best else None,
                           'urgent_on_time':best.get('urgent_on_time') if best else None,
                           'objective':best['objective'] if best else None})
    csvout(out/'per_task.csv', rows)
    csvout(out/'budget_slices.csv', slices)
    csvout(out/'quality_time_events.csv', events)
    summary = {'expected_tasks':args.expected, 'completed_runs':len(rows), 'methods':{}}
    for method in METHODS:
        sub = [r for r in rows if r['method']==method]
        item = {'completed':len(sub), 'expected':args.expected,
                'admissible':sum(r['admissible'] for r in sub),
                'certified_references':sum(r['reference_certified'] for r in sub),
                'service_target':sum(r['service_target'] for r in sub),
                'reference_quality':sum(r['reference_quality'] for r in sub),
                'first_miss_counts':dict(Counter(r['first_miss'] for r in sub if r['first_miss'])),
                'global_optimal':sum(r['global_optimal'] for r in sub)}
        for label in ('first_feasible_seconds','first_service_seconds','first_reference_quality_seconds','total_seconds'):
            values=[r[label] for r in sub if r[label] is not None]
            item[label]={'hits':len(values),'denominator':len(sub),'median_among_hits':statistics.median(values) if values else None,
                         'maximum_among_hits':max(values) if values else None}
        summary['methods'][method]=item
    pairs=[]
    oldpath=ROOT/'arco_closing_study/evaluation/per_task.csv'
    if oldpath.exists():
        with oldpath.open(encoding='utf-8-sig',newline='') as f:
            historical=list(csv.DictReader(f))
        for old in historical:
            rid,model=old['record_id'],old['source']
            if old['layer']!='network' or model not in ('deepseek','luna'):
                continue
            latency=float(old['latency_seconds']) if old.get('latency_seconds') else None
            for method in ('Full-MILP','Iter-R4'):
                if (rid,method) not in indexed:
                    continue
                row,run=indexed[rid,method]
                feasible_model=old['admissible']=='True'
                vector=json.loads(old['objective']) if feasible_model else None
                before=[e for e in run['improvements'] if latency is not None and e['available_seconds']<=latency]
                best=before[-1] if before else None
                pairs.append({'record_id':rid,'model':model,'deterministic':method,
                              'model_admissible':feasible_model,'model_reference_quality':old['reference_quality']=='True',
                              'recorded_response_seconds':latency,'model_online_verified_time_recorded':False,
                              'det_service_before_response':row['first_service_seconds'] is not None and latency is not None and row['first_service_seconds']<=latency,
                              'det_quality_before_response':row['first_reference_quality_seconds'] is not None and latency is not None and row['first_reference_quality_seconds']<=latency,
                              'det_at_least_model_quality_before_response':bool(best and vector and compare(best['objective'],vector)<=0),
                              'det_first_quality_seconds':row['first_reference_quality_seconds'],
                              'model_objective':vector,'det_at_response_objective':best['objective'] if best else None})
        csvout(out/'historical_model_response_screen.csv',pairs)
    summary['historical_response_screen']={}
    for method in ('Full-MILP','Iter-R4'):
        for model in ('deepseek','luna'):
            sub=[r for r in pairs if r['deterministic']==method and r['model']==model]
            summary['historical_response_screen'][method+'+'+model]={
                'tasks':len(sub),'model_admissible':sum(r['model_admissible'] for r in sub),
                'det_service_before_response':sum(r['det_service_before_response'] for r in sub),
                'det_quality_before_response':sum(r['det_quality_before_response'] for r in sub),
                'det_at_least_model_quality_before_response':sum(r['det_at_least_model_quality_before_response'] for r in sub)}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
