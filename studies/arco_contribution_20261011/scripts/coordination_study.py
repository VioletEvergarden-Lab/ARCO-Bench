"""Common archived network inputs and target-conditioned E1 orchestration.

Historical files are read-only. Model candidates mean first formal attempts;
invalid and unavailable outcomes retain their recorded status. This is research
orchestration, not an online method, and all target origins are explicitly G.
"""
from pathlib import Path
from functools import lru_cache
from collections import Counter
import argparse, csv, json, math, sys, time
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT.parent
OLD = WS / 'arco_closing_study'
FOCUS = WS / 'arco_focused_revision_20261002'
sys.path.insert(0, str(OLD))
from continuous_engine import TIERS, QUALITY_TOL
METHODS = ('G', 'R4', 'Iter-R4', 'R_frac', 'Full-MILP')
FIELDS = ('held', 'path_id', 'depart_min', 'charge_blocks')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)

def rel(path):
    return str(Path(path).relative_to(WS)).replace('\\', '/')

def canonical(plan):
    if not plan: return ()
    return tuple(sorted((d['mission_id'], d.get('uav_id'), *(d.get(k) for k in FIELDS)) for d in plan))

def changes(plan, origin):
    if not plan: return None, None
    before = {d['mission_id']:d for d in origin}
    if {d['mission_id'] for d in plan} != set(before): return None, None
    mids = sorted(d['mission_id'] for d in plan if any(d.get(k) != before[d['mission_id']].get(k) for k in FIELDS))
    return mids, sorted({d['uav_id'] for d in plan if d['mission_id'] in mids})

def meets(objective, target, prefix):
    return bool(objective) and all(abs(objective[t]-target[t]) <= QUALITY_TOL[i]+1e-10 for i,t in enumerate(TIERS[:prefix]))

@lru_cache(None)
def old_models():
    return {(r['record_id'],r['source']):r for r in read(OLD/'evaluation/scores.json') if r['source'] in ('deepseek','luna')}

@lru_cache(None)
def new_attempts():
    with (FOCUS/'results/generated_structure/per_attempt.csv').open(encoding='utf-8-sig',newline='') as f:
        return {r['attempt_id']:r for r in csv.DictReader(f)}

@lru_cache(None)
def prior_proofs():
    rows = {r['record_id']:r for r in read(OLD/'coordination_bounds/results.json')}
    chains = {r['record_id']:r for r in read(FOCUS/'results/mechanism/cross_chain_necessity.json')}
    staged = read(WS/'arco_stage_research_20261009/analysis/network_event_checks.json')
    return rows, chains, {r['record_id']:r for r in staged['strengthened_distance_bounds']}

def record_ids(group=None):
    paths = []
    if group in (None,'original'): paths.extend((OLD/'networks/tasks').glob('*.json'))
    if group in (None,'paired'): paths.extend((FOCUS/'new_networks/tasks').glob('*.json'))
    return sorted(p.stem for p in paths)

def load_case(record_id):
    original = record_id.startswith('NET_')
    group = 'original' if original else 'paired'
    base = OLD/'networks' if original else FOCUS/'new_networks'
    task_path = base/'tasks'/f'{record_id}.json'
    ref_path = base/'references'/f'{record_id}.json'
    task, reference = read(task_path), read(ref_path)
    assert reference['optimal'] and reference['proved_prefix']==6, record_id
    runbase = FOCUS/'results'/('comparison' if original else 'new_comparison')/'runs'
    runs = {s:read(runbase/f'{record_id}__{s}.json') for s in METHODS}
    origin = read(base/'candidates'/f'{record_id}.json')['G']['decisions'] if original else runs['G']['decisions']
    assert canonical(origin)==canonical(runs['G']['decisions']), (record_id,'G changed')
    candidates = {'reference':dict(source='reference',decisions=reference['decisions'],objective=reference['objective'],admissible=True,status='optimal',source_path=rel(ref_path))}
    for s,run in runs.items():
        candidates[s] = {k:run.get(k) for k in ('decisions','objective','admissible')}
        candidates[s].update(source=s,status=run['stop_reason'],source_path=rel(runbase/f'{record_id}__{s}.json'),run=run)
    for s in ('deepseek','luna'):
        if original:
            raw = old_models().get((record_id,s),{})
            path = OLD/'evaluation/scores.json'
            outcome = 'valid_plan' if raw.get('admissible') else raw.get('status','missing')
        else:
            aid = f'{record_id}__{s}__r1'
            path = FOCUS/'online/new_generation/attempts'/aid/'TERMINAL.json'
            raw = read(path) if path.exists() else {}
            outcome = new_attempts().get(aid,{}).get('outcome_class','missing')
        candidates[s] = dict(source=s,decisions=raw.get('decisions'),objective=raw.get('objective'),admissible=bool(raw.get('admissible')),status=raw.get('status','missing'),outcome_class=outcome,source_path=rel(path),repeat=1)
    for c in candidates.values():
        ms,us = changes(c['decisions'],origin)
        c.update(changed_missions_vs_G=ms,changed_uavs_vs_G=us,dM_vs_G=None if ms is None else len(ms),dU_vs_G=None if us is None else len(us),record_path=c['source_path'])
        for j in (2,3,6): c[f'target{j}'] = bool(c['admissible'] and meets(c['objective'],reference['objective'],j))
        c['reference_quality']=c['target6']
    tokens=record_id.split('_')
    network_id='_'.join(tokens[:-1])
    scale=tokens[1][0] if original else tokens[2][0]
    return dict(record_id=record_id,group=group,network_id=network_id,condition=tokens[-1],scale=scale,
        topology='original' if original else tokens[1],task=task,reference=reference,
        origins={'G':origin,'incumbent':task['baseline']['decisions']},candidates=candidates,
        task_path=rel(task_path),reference_path=rel(ref_path),mission_count=len(task['missions']),uav_count=len(task['fleet']),
        chain_lengths=dict(Counter(m['uav_id'] for m in task['missions'])))

def load_cases(group=None):
    return [load_case(rid) for rid in record_ids(group)]

def initial_bounds(case,prefix,metric):
    good=[c for c in case['candidates'].values() if c[f'target{prefix}']]
    field='dM_vs_G' if metric=='missions' else 'dU_vs_G'
    witness=min(good,key=lambda c:(c[field],c['dM_vs_G'],c['source']))
    upper=witness[field]
    mission_lower=0 if case['candidates']['G'][f'target{prefix}'] else 1
    evidence=[dict(kind='G_target_membership',lower_bound=mission_lower)]
    for source in ('R4','R_frac'):
        c=case['candidates'][source];run=c['run']
        nh=run.get('neighborhoods',[])
        if not nh or canonical(nh[0]['center_decisions'])!=canonical(case['origins']['G']): continue
        phases={p['tier']:p for p in run.get('phases',[]) if p.get('neighborhood')==1 and p.get('proved')}
        # Through L4 only: later historical lexicographic solves may anchor an
        # approximate L4 interval differently from the archived reference.
        for i,t in enumerate(TIERS[:min(prefix,4)]):
            p=phases.get(t)
            if not p or p.get('lower_bound') is None: break
            delta=p['lower_bound']-case['reference']['objective'][t]
            if delta>QUALITY_TOL[i]+1e-10:
                bound=int(nh[0]['radius'])+1
                mission_lower=max(mission_lower,bound)
                evidence.append(dict(kind='G_centered_radius_exclusion',source=c['source_path'],tier=t,tier_index_zero_based=i,phase_indices=[pi for pi,pp in enumerate(run['phases']) if pp.get('neighborhood')==1 and pp['tier'] in TIERS[:i+1]],radius=nh[0]['radius'],lower_bound=bound))
                break
            if abs(delta)>QUALITY_TOL[i]+1e-10: break
    if prefix==6:
        old,chains,new=prior_proofs()
        for source,row,key in [('arco_closing_study/coordination_bounds/results.json',old.get(case['record_id'],{}),'distance_lower_bound'),('arco_stage_research_20261009/analysis/network_event_checks.json',new.get(case['record_id'],{}),'quality_distance_lower_bound')]:
            bound=row.get(key)
            if bound:
                mission_lower=max(mission_lower,bound)
                evidence.append(dict(kind='stored_target6_distance_bound',source=source,lower_bound=bound))
    lower=mission_lower
    if metric=='chains':
        lengths=sorted(case['chain_lengths'].values(),reverse=True)
        lower=next(k for k in range(len(lengths)+1) if sum(lengths[:k])>=mission_lower)
        evidence.append(dict(kind='chain_length_cover_of_task_bound',mission_lower_bound=mission_lower,lower_bound=lower))
        if prefix==6:
            chain=prior_proofs()[1].get(case['record_id'],{})
            lb=chain.get('necessary_minimum_changed_chains') or 0
            lower=max(lower,lb)
            if lb:evidence.append(dict(kind='stored_chain_necessity',source='arco_focused_revision_20261002/results/mechanism/cross_chain_necessity.json',lower_bound=lb))
    assert lower<=upper,(case['record_id'],prefix,metric,lower,upper)
    return dict(record_id=case['record_id'],group=case['group'],network_id=case['network_id'],condition=case['condition'],target_prefix=prefix,origin='G',metric=metric,lower_bound=lower,upper_bound=upper,status='closed' if lower==upper else 'open',witness_source=witness['source'],decisions=witness['decisions'],changed_missions=witness['changed_missions_vs_G'],changed_uavs=witness['changed_uavs_vs_G'],evidence=evidence,new_queries=[])

def inventory():
    cases=load_cases();assert len(cases)==60
    manifest=[{k:c[k] for k in ('record_id','group','network_id','condition','scale','topology','task_path','reference_path','mission_count','uav_count','chain_lengths')} for c in cases]
    candidates=[dict(record_id=c['record_id'],group=c['group'],**{k:v for k,v in x.items() if k not in ('decisions','run')}) for c in cases for x in c['candidates'].values()]
    queries=[initial_bounds(c,j,m) for c in cases for j in (2,6) for m in ('missions','chains')]
    write(ROOT/'analysis/task_manifest.json',manifest)
    write(ROOT/'analysis/candidate_index.json',candidates)
    write(ROOT/'analysis/e1_initial_bounds.json',queries)
    summary=dict(conditions=len(cases),candidates=len(candidates),queries=len(queries),closed=sum(q['status']=='closed' for q in queries),closed_zero=sum(q['upper_bound']==0 for q in queries),open=sum(q['status']=='open' for q in queries),by_group_metric={f'{g}_T{j}_{m}':dict(Counter(q['status'] for q in queries if q['group']==g and q['target_prefix']==j and q['metric']==m)) for g in ('original','paired') for j in (2,6) for m in ('missions','chains')})
    write(ROOT/'analysis/e1_inventory_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return queries

def refresh_bounds(case, queries, solved):
    """Monotone target membership, witness reuse, and distance lower bounds."""
    pool=[]
    for path,result in solved:
        if result.get('feasible') and result.get('decisions'):
            pool.append((path,result))
    for q in queries:
        for path,result in solved:
            if result['target_prefix']==q['target_prefix'] and result['minimize']==q['metric'] and '/runs/e1/' in path and path not in q['new_queries']:
                q['new_queries'].append(path)
            if result['target_prefix']<=q['target_prefix'] and result['minimize']==q['metric']:
                lower=result.get('lower_bound')
                if lower is not None and lower>q['lower_bound']:
                    q['lower_bound']=lower
                    q['evidence'].append(dict(kind='new_target_minimization_lower_bound',source=path,target_prefix=result['target_prefix'],lower_bound=lower))
        for path,result in pool:
            if not meets(result['objective'],case['reference']['objective'],q['target_prefix']):continue
            upper=result['mission_changes'] if q['metric']=='missions' else result['chain_changes']
            if upper<q['upper_bound']:
                q.update(upper_bound=upper,witness_source=path,decisions=result['decisions'],changed_missions=result['changed_missions'],changed_uavs=result['changed_uavs'])
        if q['metric']=='chains':
            m=next(x for x in queries if x['target_prefix']==q['target_prefix'] and x['metric']=='missions')
            lens=sorted(case['chain_lengths'].values(),reverse=True)
            lb=next(k for k in range(len(lens)+1) if sum(lens[:k])>=m['lower_bound'])
            if lb>q['lower_bound']:
                q['lower_bound']=lb
                q['evidence'].append(dict(kind='chain_length_cover_of_updated_task_bound',mission_lower_bound=m['lower_bound'],lower_bound=lb))
        assert q['lower_bound']<=q['upper_bound'],q
        q['status']='closed' if q['lower_bound']==q['upper_bound'] else 'open'
    return queries

def e1_summary(queries):
    summary=dict(conditions=len({q['record_id'] for q in queries}),queries=len(queries),closed=sum(q['status']=='closed' for q in queries),open=sum(q['status']=='open' for q in queries))
    summary['by_group_target_metric']={f'{g}_T{j}_{m}':dict(closed=sum(q['status']=='closed' for q in queries if (q['group'],q['target_prefix'],q['metric'])==(g,j,m)),total=sum((q['group'],q['target_prefix'],q['metric'])==(g,j,m) for q in queries),nonzero_lower=sum(q['lower_bound']>0 for q in queries if (q['group'],q['target_prefix'],q['metric'])==(g,j,m)),lower_bound_above_one=sum(q['lower_bound']>1 for q in queries if (q['group'],q['target_prefix'],q['metric'])==(g,j,m))) for g in ('original','paired') for j in (2,6) for m in ('missions','chains')}
    return summary

def export_e1(queries):
    write(ROOT/'analysis/e1_results.json',queries)
    write(ROOT/'analysis/e1_summary.json',e1_summary(queries))
    fields=['record_id','group','network_id','condition','target_prefix','origin','metric','lower_bound','upper_bound','status','witness_source','changed_missions','changed_uavs']
    with (ROOT/'analysis/e1_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.DictWriter(f,fieldnames=fields);out.writeheader()
        for q in queries:out.writerow({k:json.dumps(q[k]) if isinstance(q[k],list) else q[k] for k in fields})
    pairs=[]
    for nid in sorted({q['network_id'] for q in queries if q['group']=='paired'}):
        for prefix in (2,6):
            for metric in ('missions','chains'):
                a=next(q for q in queries if (q['network_id'],q['condition'],q['target_prefix'],q['metric'])==(nid,'short',prefix,metric))
                b=next(q for q in queries if (q['network_id'],q['condition'],q['target_prefix'],q['metric'])==(nid,'long',prefix,metric))
                row=dict(network_id=nid,target_prefix=prefix,metric=metric,short_lower=a['lower_bound'],short_upper=a['upper_bound'],long_lower=b['lower_bound'],long_upper=b['upper_bound'])
                row['relation']='increase' if b['lower_bound']>a['upper_bound'] else 'decrease' if b['upper_bound']<a['lower_bound'] else 'equal' if a['lower_bound']==a['upper_bound']==b['lower_bound']==b['upper_bound'] else 'unresolved'
                pairs.append(row)
    write(ROOT/'analysis/e1_paired_comparison.json',pairs)

def run_e1(seconds=30, round_name='initial', only=None, only_queries=None):
    from coordination_solver import CoordinationProblem
    cases=load_cases(); queries=[initial_bounds(c,j,m) for c in cases for j in (2,6) for m in ('missions','chains')]
    start=time.perf_counter();new_count=0
    solved_by_id={}
    for case in cases:
        solved=[]
        for directory in (ROOT/'runs/e1',ROOT/'runs/development'):
            for path in sorted(directory.glob(case['record_id']+'__*.json')):
                r=read(path)
                if r.get('minimize') in ('missions','chains') and r.get('origin_name')=='G' and r.get('target_mode','match')=='match' and r.get('task_budget') is None and r.get('chain_budget') is None and not r.get('no_good_supports') and set(r.get('allowed_uavs',[]))=={f['uav_id'] for f in case['task']['fleet']}:
                    solved.append((rel(path),r))
        solved_by_id[case['record_id']]=solved
        refresh_bounds(case,[q for q in queries if q['record_id']==case['record_id']],solved)
    for case in cases:
        own=[q for q in queries if q['record_id']==case['record_id']]
        solved=solved_by_id[case['record_id']]
        if only and case['record_id'] not in only:continue
        problem=None
        # T2 first learns cheap service witnesses; T6 witnesses still transfer
        # to T2 on reruns. Metric optima retain their own witness plans.
        for q in own:
            path=ROOT/'runs/e1'/f"{case['record_id']}__T{q['target_prefix']}__{q['metric']}__{round_name}.json"
            qid=f"{case['record_id']}:T{q['target_prefix']}:{q['metric']}"
            if only_queries and qid not in only_queries:continue
            if q['status']=='closed' or path.exists():continue
            if problem is None:problem=CoordinationProblem(case['task'],case['origins']['G'],origin_name='G')
            r=problem.solve(case['reference']['objective'],target_prefix=q['target_prefix'],minimize=q['metric'],seconds=seconds,witness=q['decisions'])
            r['research_round']=round_name;r['input_task_path']=case['task_path'];r['input_reference_path']=case['reference_path']
            write(path,r);new_count+=1;solved.append((rel(path),r));q['new_queries'].append(rel(path))
            refresh_bounds(case,own,solved);export_e1(queries)
            print(json.dumps(dict(record_id=case['record_id'],prefix=q['target_prefix'],metric=q['metric'],status=q['status'],bounds=[q['lower_bound'],q['upper_bound']],elapsed=r['elapsed_seconds'],solver_status=r['solver_status'])),flush=True)
        export_e1(queries)
    summary=e1_summary(queries);summary.update(round_name=round_name,new_queries=new_count,elapsed_seconds=time.perf_counter()-start)
    write(ROOT/'analysis'/f'e1_round_{round_name}.json',summary)
    print(json.dumps(summary),flush=True)
    return queries

def stored_plans(case):
    plans=[dict(source=c['source_path'],decisions=c['decisions'],objective=c['objective']) for c in case['candidates'].values() if c['admissible']]
    for directory in (ROOT/'runs/e1',ROOT/'runs/development',ROOT/'runs/e1_extensions'):
        for path in sorted(directory.glob(case['record_id']+'__*.json')):
            r=read(path)
            if r.get('feasible') and r.get('independent_verification') and r.get('decisions'):
                plans.append(dict(source=rel(path),decisions=r['decisions'],objective=r['objective']))
    return plans

def joint_minima():
    queries=read(ROOT/'analysis/e1_results.json');rows=[]
    tradeoff_path=ROOT/'analysis/e1_joint_tradeoff.json'
    tradeoff=read(tradeoff_path) if tradeoff_path.exists() else None
    for case in load_cases():
        plans=stored_plans(case)
        for j in (2,6):
            a=next(q for q in queries if (q['record_id'],q['target_prefix'],q['metric'])==(case['record_id'],j,'missions'))
            b=next(q for q in queries if (q['record_id'],q['target_prefix'],q['metric'])==(case['record_id'],j,'chains'))
            row=dict(record_id=case['record_id'],group=case['group'],target_prefix=j,mission_bounds=[a['lower_bound'],a['upper_bound']],chain_bounds=[b['lower_bound'],b['upper_bound']])
            if a['status']!=b['status'] or a['status']!='closed':row['status']='marginal_minimum_unresolved'
            else:
                matches=[]
                for p in plans:
                    ms,us=changes(p['decisions'],case['origins']['G'])
                    if meets(p['objective'],case['reference']['objective'],j) and len(ms)==a['lower_bound'] and len(us)==b['lower_bound']:matches.append(p)
                row.update(status='jointly_attained' if matches else 'joint_feasibility_unresolved',witness_source=matches[0]['source'] if matches else None,decisions=matches[0]['decisions'] if matches else None)
                joint_path=ROOT/'runs/e1_extensions'/f"{case['record_id']}__T{j}__G_joint_k{a['lower_bound']}_c{b['lower_bound']}.json"
                if not matches and joint_path.exists():
                    result=read(joint_path);row['joint_query_source']=rel(joint_path)
                    if result['feasible'] is False:row['status']='jointly_incompatible'
                    elif result['feasible'] is True:row.update(status='jointly_attained',witness_source=rel(joint_path),decisions=result['decisions'])
                if tradeoff and (tradeoff['record_id'],tradeoff['target_prefix'])==(case['record_id'],j) and tradeoff.get('status')=='proved_tradeoff':
                    assert tradeoff['origin']=='G' and tradeoff['joint_feasible'] is False
                    assert tradeoff['marginal_minima']==[a['lower_bound'],b['lower_bound']]==[2,1]
                    proof_path=ROOT/tradeoff['query_source'];proof=read(proof_path)
                    assert proof['record_id']==case['record_id'] and proof['origin_name']=='G'
                    assert proof['target_prefix']==j and proof.get('target_mode','match')=='match'
                    assert proof['status']=='infeasible' and proof['feasible'] is False
                    assert proof['task_budget']==2 and proof['chain_budget']==1
                    assert set(proof['allowed_uavs'])==set(case['chain_lengths']) and not proof.get('no_good_supports')
                    assert meets(proof['target_objective'],case['reference']['objective'],j)
                    points=[]
                    for w in tradeoff['witnesses']:
                        assert meets(w['objective'],case['reference']['objective'],j)
                        ms,us=changes(w['decisions'],case['origins']['G'])
                        assert [len(ms),len(us)]==[w['missions'],w['chains']]
                        points.append([len(ms),len(us)])
                    assert sorted(points)==tradeoff['complete_nondominated_budget_frontier']==[[2,2],[3,1]]
                    assert not matches, 'Joint witness contradicts the recorded budget infeasibility'
                    row.update(status='proved_tradeoff',joint_feasible=False,tradeoff_source=rel(tradeoff_path),joint_query_source=rel(proof_path),
                        complete_nondominated_budget_frontier=tradeoff['complete_nondominated_budget_frontier'],frontier_witnesses=tradeoff['witnesses'],
                        frontier_proof=tradeoff['proof'])
            rows.append(row)
    write(ROOT/'analysis/e1_joint_minima.json',rows)
    return rows

def query_joint_gaps(seconds=30):
    from coordination_solver import CoordinationProblem
    gaps=[r for r in joint_minima() if r['status']=='joint_feasibility_unresolved']
    for row in gaps:
        rid=row['record_id'];j=row['target_prefix'];k=row['mission_bounds'][0];c=row['chain_bounds'][0]
        path=ROOT/'runs/e1_extensions'/f'{rid}__T{j}__G_joint_k{k}_c{c}.json'
        if path.exists():continue
        case=load_case(rid);problem=CoordinationProblem(case['task'],case['origins']['G'],origin_name='G')
        result=problem.solve(case['reference']['objective'],target_prefix=j,minimize='feasibility',task_budget=k,chain_budget=c,seconds=seconds)
        result['selection_reason']='Only a fully enumerated condition/target with both marginal minima exact and no archived joint witness.'
        write(path,result);print(json.dumps(dict(record_id=rid,target_prefix=j,task_budget=k,chain_budget=c,status=result['status'])),flush=True)
    return joint_minima()

def run_extensions(seconds=30):
    from coordination_solver import CoordinationProblem
    paired=[f'NEW_{top}_{scale}01_{condition}' for top in ('ladder','regions') for scale in 'SML' for condition in ('short','long')]
    selected=['NET_M01_B']+paired
    origin_selected=['NET_M01_B']+[r for r in paired if r.endswith('_long')]+['NEW_regions_S01_short']
    manifest=dict(selection='All paired index01 networks (two topologies by three scales), both closure conditions; M01B is the separately labelled developer case.',support_records=selected,incumbent_origin_records=origin_selected,additional_origin_rationale='Regions S01 short is the single explanatory matched-origin addition requested after observing the G-relative decrease; this diagnoses that pair and is not a new representative sample.',targets=[2,6],seconds_per_unresolved_query=seconds,support_semantics='Cardinality-minimum G-relative chain support; exclusion of each witness chain is tested without a chain budget to distinguish necessary identity from minimum size.')
    write(ROOT/'analysis/e1_extension_manifest.json',manifest)
    queries=read(ROOT/'analysis/e1_results.json');support_rows=[];origin_rows=[]
    for rid in selected:
        case=load_case(rid);plans=stored_plans(case);problem=CoordinationProblem(case['task'],case['origins']['G'],origin_name='G')
        for j in (2,6):
            q=next(x for x in queries if (x['record_id'],x['target_prefix'],x['metric'])==(rid,j,'chains'))
            row=dict(record_id=rid,target_prefix=j,chain_bounds=[q['lower_bound'],q['upper_bound']],witness_support=q['changed_uavs'],checks=[])
            if q['upper_bound']==0:row.update(status='empty_support_exact',alternative_minimum_support=False,necessary_chains=[])
            elif q['status']!='closed':row['status']='minimum_size_unresolved'
            else:
                S=q['changed_uavs'];uavs=sorted(case['chain_lengths']);specs=[('alternative',dict(chain_budget=q['upper_bound'],no_good_supports=[S]))]+[(f'exclude_{u}',dict(allowed_uavs=[x for x in uavs if x!=u])) for u in S]
                for label,kwargs in specs:
                    path=ROOT/'runs/e1_extensions'/f'{rid}__T{j}__G_support_{label}.json'
                    if path.exists():r=read(path)
                    else:
                        reused=None
                        for oldpath in sorted((ROOT/'runs/development').glob(rid+'__*.json')):
                            old=read(oldpath)
                            if old.get('origin_name')=='G' and old.get('minimize')=='feasibility' and old.get('target_prefix')==j and old.get('target_mode','match')=='match' and old.get('task_budget') is None and old.get('chain_budget')==kwargs.get('chain_budget') and old.get('allowed_uavs')==kwargs.get('allowed_uavs',uavs) and old.get('no_good_supports',[])==kwargs.get('no_good_supports',[]) and old.get('feasible') is not None:
                                reused=dict(old,reused_source=rel(oldpath));break
                        compatible=[]
                        for p in plans:
                            ms,us=changes(p['decisions'],case['origins']['G'])
                            if meets(p['objective'],case['reference']['objective'],j) and set(us)<=set(kwargs.get('allowed_uavs',uavs)) and len(us)<=kwargs.get('chain_budget',len(uavs)) and all(set(us)!=set(x) for x in kwargs.get('no_good_supports',[])):compatible.append(p['decisions'])
                        r=reused if reused is not None else problem.solve(case['reference']['objective'],target_prefix=j,minimize='feasibility',seconds=seconds,witness=compatible or None,**kwargs)
                        write(path,r)
                    row['checks'].append(dict(label=label,source=rel(path),feasible=r['feasible'],status=r['status'],changed_uavs=r.get('changed_uavs')))
                    print(json.dumps(dict(record_id=rid,target=j,query=label,status=r['status'])),flush=True)
                row['status']='support_queries_recorded';row['alternative_minimum_support']=row['checks'][0]['feasible']
                row['necessary_chains']=[c['label'].removeprefix('exclude_') for c in row['checks'][1:] if c['feasible'] is False]
                row['necessity_unresolved']=[c['label'].removeprefix('exclude_') for c in row['checks'][1:] if c['feasible'] is None]
            support_rows.append(row);write(ROOT/'analysis/e1_support_identity.json',support_rows)
        if rid not in origin_selected:continue
        origin=case['origins']['incumbent'];ip=CoordinationProblem(case['task'],origin,origin_name='incumbent')
        for j in (2,6):
            for metric in ('missions','chains'):
                path=ROOT/'runs/e1_extensions'/f'{rid}__T{j}__incumbent_{metric}.json'
                if path.exists():r=read(path)
                else:
                    good=[p for p in plans if meets(p['objective'],case['reference']['objective'],j)]
                    witness=min(good,key=lambda p:len(changes(p['decisions'],origin)[0 if metric=='missions' else 1]))
                    r=ip.solve(case['reference']['objective'],target_prefix=j,minimize=metric,seconds=seconds,witness=witness['decisions']);write(path,r)
                    if r['feasible']:plans.append(dict(source=rel(path),decisions=r['decisions'],objective=r['objective']))
                g=next(x for x in queries if (x['record_id'],x['target_prefix'],x['metric'])==(rid,j,metric))
                inherited=[x for x in origin_rows if x['record_id']==rid and x['metric']==metric and x['target_prefix']<j]
                lower=max([r['lower_bound']]+[x['incumbent_bounds'][0] for x in inherited])
                origin_rows.append(dict(record_id=rid,target_prefix=j,metric=metric,G_bounds=[g['lower_bound'],g['upper_bound']],incumbent_solver_bounds=[r['lower_bound'],r['upper_bound']],incumbent_bounds=[lower,r['upper_bound']],incumbent_status='optimal' if lower==r['upper_bound'] else r['status'],source=rel(path),inherited_lower_sources=[x['source'] for x in inherited if x['incumbent_bounds'][0]>r['lower_bound']]))
                write(ROOT/'analysis/e1_origin_comparison.json',origin_rows)
                print(json.dumps(origin_rows[-1]),flush=True)
    joint_minima()
    return support_rows,origin_rows

def write_findings():
    qs=read(ROOT/'analysis/e1_results.json');pairs=read(ROOT/'analysis/e1_paired_comparison.json')
    joint=joint_minima();supports=read(ROOT/'analysis/e1_support_identity.json');origins=read(ROOT/'analysis/e1_origin_comparison.json')
    assert len(qs)==240 and len(supports)==26 and len(origins)==32
    def bounds(v):return str(v[0]) if v[0]==v[1] else f'[{v[0]},{v[1]}]'
    def qget(rid,j,m):return next(q for q in qs if (q['record_id'],q['target_prefix'],q['metric'])==(rid,j,m))
    def original(rid,j,m):return next(q for q in origins if (q['record_id'],q['target_prefix'],q['metric'])==(rid,j,m))
    def pair_label(rid,j,kind):
        if kind=='G':return '('+','.join(bounds([qget(rid,j,m)['lower_bound'],qget(rid,j,m)['upper_bound']]) for m in ('missions','chains'))+')'
        return '('+','.join(bounds(original(rid,j,m)['incumbent_bounds']) for m in ('missions','chains'))+')'
    closed=sum(q['status']=='closed' for q in qs);jc=Counter(q['status'] for q in joint)
    strict_chains=sum(qget(rid,6,'chains')['lower_bound']>qget(rid,2,'chains')['upper_bound'] for rid in record_ids())
    stats=dict(conditions=60,base_networks=24,closed_scalar_queries=closed,total_scalar_queries=240,joint_status=dict(jc),strict_chain_increase_T2_to_T6=strict_chains,
        G_service_target=sum(q['upper_bound']==0 for q in qs if q['target_prefix']==2 and q['metric']=='chains'),G_quality_target=sum(q['upper_bound']==0 for q in qs if q['target_prefix']==6 and q['metric']=='chains'),
        quality_multichain_necessary=sum(q['lower_bound']>=2 for q in qs if q['target_prefix']==6 and q['metric']=='chains'),
        service_multichain_necessary_lower=sum(q['lower_bound']>=2 for q in qs if q['target_prefix']==2 and q['metric']=='chains'),service_multichain_necessary_upper=sum(q['upper_bound']>=2 for q in qs if q['target_prefix']==2 and q['metric']=='chains'),
        paired_relations={f'T{j}_{m}':dict(Counter(p['relation'] for p in pairs if p['target_prefix']==j and p['metric']==m)) for j in (2,6) for m in ('missions','chains')})
    write(ROOT/'analysis/e1_findings_summary.json',stats)
    lines=['# E1：目标条件下的修复范围与支持身份','',
        '本节覆盖原网络36条件与配对网络24条件，共24个基础网络、60个条件。主分析的原点是各条件归档的G；T2/T6使用已证全局参考的前2/6层以及原评分容差。dM计完整动作元组发生变化的任务，dU计至少一个任务变化的UAV链。原计划（incumbent）仅在明确标记的对照中作为原点。',
        '',f'240个标量最小化查询中，{closed}个已有相等上下界，7个保留区间。G已达到T2的条件为48/60，达到T6为30/60。相同G原点下，{strict_chains}/60条件从T2提升至T6时最小链数严格增加，其余33相等；T6要求至少两链变化的条件为24/60，T2则为1个已证、另1个未决。T6已证最小任务数最大为12，最小链数最大为7。这个结果将“服务恢复”与“恢复全部偏好质量”需要的自由度分开，并不把多链动作变化等同于通信量或不可分解的计算难度。',
        '',f'任务数与链数分别求最小，保留各自见证。120个“条件×目标”组合中，{jc.get("jointly_attained",0)}个有同一可行计划同时达到两个边际最小值，{jc.get("proved_tradeoff",0)+jc.get("jointly_incompatible",0)}个已证无法同时达到，{jc.get("joint_feasibility_unresolved",0)}个联合可行性未决，{jc.get("marginal_minimum_unresolved",0)}个仍有边际最小值未决。NET_S02_C在G原点、T2目标下的边际最小值为dM*=2、dU*=1，但(k≤2,c≤1)已证不可行。两个独立验证的见证分别达到(2,2)与(3,1)，它们构成完整的非支配预算前沿：整数下界k≥2、c≥1及对(2,1)的排除，使其余任何可行整数点均被这两点之一支配。因此“少改任务”和“少涉及链”在这一条件下确有权衡，不能把边际值拼成可行计划；该结论限于此条件、G原点和T2目标。证明与见证见`analysis/e1_joint_tradeoff.json`及其指向的原始查询。',
        '', '## 全部12配对', '',
        '每行是(dM*,dU*)，均相对该条件自己的G并匹配该条件自己的参考。长关闭的T2范围在3/12配对增加、9/12相等；T6任务数4增7平1降，链数3增8平1降。这里不是固定原点、固定目标下的扰动单调性检验。', '',
        '| 基础网络 | T2 short | T2 long | T6 short | T6 long |','|---|---:|---:|---:|---:|']
    for nid in sorted({q['network_id'] for q in qs if q['group']=='paired'}):
        vals=[pair_label(nid+'_'+condition,j,'G') for j in (2,6) for condition in ('short','long')]
        lines.append('| '+nid.replace('NEW_','')+' | '+' | '.join(vals)+' |')
    lines+=['','## 原点对照','',
        '输入结构选取的六个index01长关闭条件与开发例M01-B先固定；Regions S01 short是解释唯一下降配对所追加的四个查询。它是针对该观察的诊断，不进入新的代表性样本声明。所有对照仍用原条件参考，未改变公共规则。', '',
        '| 条件 | G→T2 | incumbent→T2 | G→T6 | incumbent→T6 |','|---|---:|---:|---:|---:|']
    for rid in sorted({r['record_id'] for r in origins}):
        lines.append('| '+rid+' | '+' | '.join(pair_label(rid,j,kind) for j in (2,6) for kind in ('G','incumbent'))+' |')
    lines+=['',
        'M01-B的最小链数在G原点为T2=1、T6=2，在incumbent原点为T2=2、T6=3。G已经完成的修复不能被当成零系统修复负担。Regions S01的T2在incumbent原点下short/long均为(2,2)，T6却由(4,3)降至(2,2)；因此T6范围下降不只是G原点效应，两个条件的参考质量与策略也不同。不能写成较长关闭更容易或扰动更轻。32个incumbent标量对照中30个已闭合，Regions L01 long的T6仍为任务[10,17]、链[3,5]；这里的下界已继承同原点T2的已证下界，原始MIP界另存。',
        '', '## 支持身份','',
        '支持检验取两个拓扑×三个规模的全部index01基础网络，保留short/long，共12条件，再加单列的开发例M01-B。26个“条件×目标”中20个具有精确空支持；下面列出其余6个。替代支持查询在c*预算下排除已有支持；逐链排除查询不限制总链数，所以“必改链”指任意目标可行计划中均必须变化的链，而不只是某个最小支持的成员。', '',
        '| 条件/目标 | c* | 一个最小支持 | 另一最小支持 | 全域必改链 | 未决排除 |','|---|---:|---|---|---|---|']
    for s in supports:
        if not s['chain_bounds'][1]:continue
        alt={True:'有见证',False:'已排除',None:'未决'}[s.get('alternative_minimum_support')]
        lines.append('| '+s['record_id']+f' / T{s["target_prefix"]} | '+bounds(s['chain_bounds'])+' | '+','.join(s['witness_support'])+' | '+alt+' | '+','.join(s.get('necessary_chains',[]))+' | '+(','.join(s.get('necessity_unresolved',[])) or '—')+' |')
    lines+=['',
        '五个非空支持已证唯一，且其各链均为全域必改；Regions L01 long的T6已证c*=3和U07必改，但替代三链支持及排除U05/U08仍未决，不作唯一性主张。支持身份与数量应分别报告，也不从不同目标的最小数量推断支持包含关系。',
        '', '## 保留的区间与研究判断', '', '| 条件 | 目标 | 度量 | 区间 |','|---|---:|---|---:|']
    for q in qs:
        if q['status']=='open':lines.append(f'| {q["record_id"]} | T{q["target_prefix"]} | {q["metric"]} | [{q["lower_bound"]},{q["upper_bound"]}] |')
    lines+=['',
        '未决主要涉及四个原网络的T2任务距离，以及L01-C的T6范围；它们不改变全部配对结果或T6多链必要性的24/60计数。L02-C的T2链数已用120秒追加查询但仍为[1,2]，保留即可。初轮56个新查询，定向轮仅2个实际新查询：Regions L01 long的dM闭合为12后，链长覆盖下界自动将dU闭合为3，无需再解一次链最小化。并行研究期间的耗时不用于算法速度比较。',
        '',
        '本轮新增知识是目标、修复原点、最小支持数量和链身份的可分辨关系；它支持对既有60条件的诊断，不单独支持新的普适网络规律。没有发现需要用新网络或预算变体填补的E1判断缺口。资源是否造成这些必改关系，交由独立的E3固定目标与新参考对照回答。最小化指示变量和历史界复用均不作为算法新颖性。',
        '', '## 可复用产物', '',
        '- `scripts/coordination_study.py`：loader、库存、E1查询、配对、联合最小值、支持与原点对照。',
        '- `analysis/e1_results.json` / `.csv`：完整240行，包含上下界、独立见证与证据路径；`e1_paired_comparison.json`覆盖全部12配对。',
        '- `analysis/e1_joint_minima.json`、`e1_support_identity.json`、`e1_origin_comparison.json`：分别保存联合见证、支持判定和32个原点对照。',
        '- `analysis/task_manifest.json` / `candidate_index.json`：60条件、480候选，保留首个模型尝试的不可行与缺失状态。',
        '- `runs/e1/` 与 `runs/e1_extensions/`：可恢复的逐查询记录；`e1_extension_manifest.json`记录固定选择与唯一追加对照的理由。','']
    (ROOT/'notes/e1_findings.md').write_text('\n'.join(lines),encoding='utf-8')
    return stats

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--inventory',action='store_true');parser.add_argument('--run-e1',action='store_true');parser.add_argument('--extensions',action='store_true');parser.add_argument('--joint',action='store_true');parser.add_argument('--joint-query',action='store_true');parser.add_argument('--findings',action='store_true');parser.add_argument('--seconds',type=float,default=30);parser.add_argument('--round',default='initial');parser.add_argument('--only',nargs='*');parser.add_argument('--queries',nargs='*');args=parser.parse_args()
    if args.run_e1:run_e1(args.seconds,args.round,args.only,args.queries)
    elif args.extensions:run_extensions(args.seconds)
    elif args.joint:joint_minima()
    elif args.joint_query:query_joint_gaps(args.seconds)
    elif args.findings:print(json.dumps(write_findings(),ensure_ascii=False))
    else:inventory()
