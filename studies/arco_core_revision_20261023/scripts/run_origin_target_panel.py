"""Frozen eight-case, two-origin panel using unchanged historical solvers.

Every expensive query is individually saved and reused on restart. Historical
minimum bounds transfer only under the identical G origin, or by the explicit
triangle inequality after recomputing the distance between origins.
"""
from pathlib import Path
from collections import Counter
import argparse, csv, hashlib, json, sys, time
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]; WS=ROOT.parent; OLD=WS/'arco_contribution_20261011'
sys.path.insert(0,str(OLD/'scripts'))
from coordination_study import load_case
from coordination_solver import CoordinationProblem,canonical_plan,changes,target_met,TIERS,QUALITY_TOL
import continuous_engine as ce
ce.HERE=ROOT/'runs'

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');tmp.replace(path)
def rel(path):return Path(path).relative_to(WS).as_posix()
def signature(plan):return json.dumps(sorted(plan,key=lambda d:d['mission_id']),sort_keys=True)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def distance(plan,origin,metric):
    ms,us=changes(plan,origin);return len(ms) if metric=='missions' else len(us)

def alternate_greedy(engine):
    """Original greedy, changing only the frozen chain-head ordering key."""
    options=engine.options();calendar=Counter();rank={u:i for i,u in enumerate(sorted(engine.fleet))}
    state={u:dict(clock=v['available_min'],soc=engine.initial[u],position=0,held=False) for u,v in engine.fleet.items()};out=[]
    while any(s['position']<len(engine.chains[u]) for u,s in state.items()):
        heads=[(engine.chains[u][s['position']],u,s) for u,s in state.items() if s['position']<len(engine.chains[u])]
        m,u,s=min(heads,key=lambda x:(-sum(mm['priority']=='urgent' for mm in engine.chains[x[1]][x[2]['position']:]),
                x[0]['release_min'],-rank[x[1]],engine.base[x[0]['mission_id']]['depart_min'],x[0]['sequence_index'],x[0]['mission_id']))
        feasible=[]
        if not s['held']:
            for o in options[m['mission_id']]:
                if o['start_min']<s['clock']-ce.EPS_TIME:continue
                after=s['soc']-o['energy_kwh']
                if after<engine.fleet[u]['reserve_kwh']-ce.SOC_TOL or after+o['charge_kwh']>engine.fleet[u]['battery_capacity_kwh']+ce.SOC_TOL:continue
                if any(calendar[key]+count>engine.capacity(key) for key,count in o['blocks'].items()):continue
                feasible.append(o)
        if feasible:
            feasible.sort(key=lambda z:(round(5*z['objectives'][2]),z['objectives'][3],z['objectives'][4],round(z['energy_kwh'],8),z['depart_min'],z['path_id'],z['charge_blocks']))
            o=feasible[0]
            if s['position']+1<len(engine.chains[u]):
                successor=engine.chains[u][s['position']+1]
                for candidate in feasible:
                    end_soc=s['soc']-candidate['energy_kwh']+candidate['charge_kwh']
                    def feasible_successor(nxt):
                        if nxt['start_min']<candidate['finish_min']-ce.EPS_TIME:return False
                        sa=end_soc-nxt['energy_kwh']
                        if sa<engine.fleet[u]['reserve_kwh']-ce.SOC_TOL or sa+nxt['charge_kwh']>engine.fleet[u]['battery_capacity_kwh']+ce.SOC_TOL:return False
                        return all(calendar[key]+candidate['blocks'][key]+num<=engine.capacity(key) for key,num in nxt['blocks'].items())
                    if any(feasible_successor(nxt) for nxt in options[successor['mission_id']]):o=candidate;break
            out.append({k:o[k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')})
            calendar.update(o['blocks']);s.update(clock=o['finish_min'],soc=s['soc']-o['energy_kwh']+o['charge_kwh'])
        else:
            s['held']=True;out.append(dict(mission_id=m['mission_id'],uav_id=u,held=True,path_id=None,depart_min=None,charge_blocks=0))
        s['position']+=1
    return sorted(out,key=lambda d:d['mission_id'])

class Panel:
    def __init__(self,rid,plan):
        self.rid=rid;self.plan=plan;self.case=load_case(rid);self.task=self.case['task'];self.target=self.case['reference']['objective']
        self.folder=ROOT/'runs/origin_target'/rid;self.folder.mkdir(parents=True,exist_ok=True)
        self.engine=ce.Engine(self.task);self.pool={};self.bounds=[];self.rows=[];self.problems={};self.new_results=[]
        write(self.folder/'task.json',self.task);write(self.folder/'reference.json',self.case['reference'])
        origin_path=self.folder/'origins.json'
        if origin_path.exists():self.origins=read(origin_path)['decisions']
        else:
            # This constructor sees only task input; never the reference or pool.
            prime=alternate_greedy(ce.Engine(self.task));self.origins={'G':canonical_plan(self.case['origins']['G'],self.task),'Gprime':prime}
            scores={name:self.engine.verify(ds) for name,ds in self.origins.items()}
            assert all(s['admissible'] for s in scores.values()),scores
            ms,us=changes(self.origins['Gprime'],self.origins['G'])
            write(origin_path,dict(record_id=rid,rule=plan['Gprime_rule'],decisions=self.origins,verification=scores,
                  origin_distance=dict(missions=len(ms),chains=len(us),changed_missions=ms,changed_uavs=us),
                  target_membership={name:{str(j):target_met(scores[name]['objective'],self.target,j) for j in (2,3,4,6)} for name in scores},
                  task_source=self.case['task_path'],task_sha256=digest(WS/self.case['task_path']),
                  reference_source=self.case['reference_path'],reference_sha256=digest(WS/self.case['reference_path'])))
        assert signature(self.origins['G'])==signature(canonical_plan(self.case['origins']['G'],self.task))
        for name,ds in self.origins.items():self.add(ds,rel(origin_path)+'#'+name)
        for name,c in self.case['candidates'].items():
            if c.get('decisions'):self.add(c['decisions'],c['source_path'])
        self.add(self.case['reference']['decisions'],self.case['reference_path'])
        self.history()
        for path in sorted((self.folder/'queries').glob('*.json')):
            r=read(path);self.new_results.append((rel(path),r))
            if r.get('decisions'):self.add(r['decisions'],rel(path))
        for path in sorted((self.folder/'joint').glob('*.json')):
            r=read(path)
            if r.get('decisions'):self.add(r['decisions'],rel(path))
        print('PREPARED',rid,'origin distance',read(origin_path)['origin_distance'],'pool',len(self.pool),flush=True)

    def add(self,ds,source):
        try:ds=canonical_plan(ds,self.task);score=self.engine.verify(ds)
        except (ValueError,KeyError,TypeError):return
        if not score['admissible']:return
        key=signature(ds)
        if key not in self.pool:self.pool[key]=dict(decisions=ds,objective=score['objective'],source=source)

    def history(self):
        for q in read(OLD/'analysis/e1_results.json'):
            if q['record_id']!=self.rid:continue
            self.bounds.append(dict(prefix=q['target_prefix'],metric=q['metric'],lower=q['lower_bound'],source=rel(OLD/'analysis/e1_results.json')+f"#{self.rid}:T{q['target_prefix']}:{q['metric']}"))
            self.add(q['decisions'],q['witness_source'])
        for dirname in ('development','e1','e1_extensions','e1_joint'):
            for path in sorted((OLD/'runs'/dirname).glob(self.rid+'__*.json')):
                r=read(path)
                if r.get('decisions'):self.add(r['decisions'],rel(path))
                if r.get('origin_name')!='G' or r.get('minimize') not in ('missions','chains'):continue
                if r.get('target_mode','match')!='match' or r.get('task_budget') is not None or r.get('chain_budget') is not None or r.get('no_good_supports'):continue
                if set(r.get('allowed_uavs',[]))!=set(self.engine.fleet):continue
                if any(abs(r['target_objective'][k]-self.target[k])>QUALITY_TOL[i]+1e-10 for i,k in enumerate(TIERS)):continue
                if r.get('lower_bound') is not None:self.bounds.append(dict(prefix=r['target_prefix'],metric=r['minimize'],lower=r['lower_bound'],source=rel(path)))
        for q in read(OLD/'analysis/e1_joint_minima.json'):
            if q['record_id']!=self.rid:continue
            if q.get('decisions'):self.add(q['decisions'],rel(OLD/'analysis/e1_joint_minima.json'))
            for witness in q.get('frontier_witnesses',[]):self.add(witness['decisions'],witness['source'])

    def make_row(self,name,prefix,metric):
        origin=self.origins[name];own=self.engine.verify(origin);at_target=target_met(own['objective'],self.target,prefix)
        lower=0 if at_target else 1;proof=[dict(kind='origin_membership',lower=lower)]
        delta=distance(origin,self.origins['G'],metric)
        for b in self.bounds:
            if b['metric']==metric and b['prefix']<=prefix:
                lb=max(0,b['lower']-delta)
                if lb>lower:lower=lb;proof.append({**b,'kind':'historical_G_bound' if delta==0 else 'triangle_inequality_from_G','historical_lower':b['lower'],'lower':lb,'origin_distance':delta})
        for source,r in self.new_results:
            if r.get('minimize')!=metric or r.get('target_prefix',7)>prefix or r.get('lower_bound') is None:continue
            delta2=distance(origin,self.origins[r['origin_name']],metric);lb=max(0,r['lower_bound']-delta2)
            if lb>lower:lower=lb;proof.append(dict(kind='new_bound' if delta2==0 else 'triangle_inequality_new_origin',lower=lb,source=source,origin_distance=delta2))
        eligible=[p for p in self.pool.values() if target_met(p['objective'],self.target,prefix)]
        best=min(eligible,key=lambda p:(distance(p['decisions'],origin,metric),distance(p['decisions'],origin,'missions' if metric=='chains' else 'chains'),p['source']))
        upper=distance(best['decisions'],origin,metric);ms,us=changes(best['decisions'],origin)
        if metric=='chains':
            mission=self.make_row(name,prefix,'missions');lens=sorted(self.case['chain_lengths'].values(),reverse=True)
            cover=next(k for k in range(len(lens)+1) if sum(lens[:k])>=mission['lower_bound'])
            if cover>lower:lower=cover;proof.append(dict(kind='chain_length_cover',lower=cover,mission_lower=mission['lower_bound']))
        assert lower<=upper,(self.rid,name,prefix,metric,lower,upper)
        path=self.folder/'queries'/f'{name}_T{prefix}_{metric}.json'
        if path.exists():resolution='new_query_record'
        elif at_target:resolution='zero_origin_membership'
        elif any(b['prefix']==prefix and b['metric']==metric for b in self.bounds) and delta==0:resolution='historical_bound_and_replayed_witness'
        else:resolution='derived_bounds_and_replayed_witness'
        return dict(record_id=self.rid,origin=name,target_prefix=prefix,metric=metric,lower_bound=lower,upper_bound=upper,
            status='closed' if lower==upper else 'open',resolution=resolution,lower_evidence=proof,witness_source=best['source'],
            decisions=best['decisions'],objective=best['objective'],changed_missions=ms,changed_uavs=us,
            mission_changes=len(ms),chain_changes=len(us),origin_objective=own['objective'])

    def problem(self,name):
        if name not in self.problems:self.problems[name]=CoordinationProblem(self.task,self.origins[name],name)
        return self.problems[name]

    def solve_position(self,name,prefix,metric):
        q=self.make_row(name,prefix,metric);path=self.folder/'queries'/f'{name}_T{prefix}_{metric}.json'
        if q['status']=='closed' or path.exists():return
        seconds=self.plan['solve_policy']['default_seconds']
        for pilot in self.plan['solve_policy']['pilot_queries']:
            if (self.rid,name,prefix,metric)==(pilot['record_id'],pilot['origin'],pilot['prefix'],pilot['metric']):seconds=pilot['seconds']
        r=self.problem(name).solve(self.target,target_prefix=prefix,minimize=metric,seconds=seconds,witness=q['decisions'])
        r.update(input_task_source=self.case['task_path'],input_reference_source=self.case['reference_path'],frozen_selection_sha256=digest(ROOT/'analysis/selection_plan.json'))
        write(path,r);self.new_results.append((rel(path),r))
        if r.get('decisions'):self.add(r['decisions'],rel(path))
        q=self.make_row(name,prefix,metric)
        print('QUERY',self.rid,name,prefix,metric,q['lower_bound'],q['upper_bound'],round(r['elapsed_seconds'],2),r['solver_status'],flush=True)

    def joint(self,name,prefix):
        m=self.make_row(name,prefix,'missions');c=self.make_row(name,prefix,'chains');k=m['upper_bound'];budget=c['upper_bound']
        origin=self.origins[name];eligible=[p for p in self.pool.values() if target_met(p['objective'],self.target,prefix)]
        valid=[p for p in eligible if distance(p['decisions'],origin,'missions')<=k and distance(p['decisions'],origin,'chains')<=budget]
        out=dict(record_id=self.rid,origin=name,target_prefix=prefix,mission_bounds=[m['lower_bound'],k],chain_bounds=[c['lower_bound'],budget],
                 query_budget=[k,budget],marginals_closed=m['status']==c['status']=='closed')
        if valid:
            p=min(valid,key=lambda p:(distance(p['decisions'],origin,'missions'),distance(p['decisions'],origin,'chains')))
            return dict(**out,status='jointly_attained' if out['marginals_closed'] else 'verified_attainable_budget',feasible=True,
                        source=p['source'],decisions=p['decisions'],objective=p['objective'])
        if not out['marginals_closed']:
            return dict(**out,status='marginal_bounds_open',feasible=None,attainable_witness_budgets=[dict(missions=r['mission_changes'],chains=r['chain_changes'],source=r['witness_source']) for r in (m,c)])
        if signature(origin)==signature(self.origins['G']):
            for h in read(OLD/'analysis/e1_joint_minima.json'):
                if h['record_id']==self.rid and h['target_prefix']==prefix and h.get('joint_feasible') is False and h['mission_bounds']==[k,k] and h['chain_bounds']==[budget,budget]:
                    return dict(**out,status='proved_tradeoff',feasible=False,source=h['joint_query_source'],frontier_witnesses=h.get('frontier_witnesses',[]))
        path=self.folder/'joint'/f'{name}_T{prefix}_k{k}_c{budget}.json'
        if path.exists():r=read(path)
        else:
            r=self.problem(name).solve(self.target,target_prefix=prefix,minimize='feasibility',task_budget=k,chain_budget=budget,seconds=15,witness=[m['decisions'],c['decisions']]);write(path,r)
        if r.get('decisions'):self.add(r['decisions'],rel(path))
        return dict(**out,status='jointly_attained' if r['feasible'] else 'proved_tradeoff' if r['feasible'] is False else 'joint_unresolved',feasible=r['feasible'],source=rel(path),decisions=r.get('decisions'),objective=r.get('objective'))

    def run(self):
        positions=[(name,j,metric) for name in ('G','Gprime') for j in (2,3,4,6) for metric in ('missions','chains')]
        for name,j,metric in positions:
            self.solve_position(name,j,metric)
            write(self.folder/'panel.json',[self.make_row(*p) for p in positions])
        extra=[]
        for name in ('G','Gprime'):
            if any(self.make_row(name,6,metric)['lower_bound']>self.make_row(name,4,metric)['upper_bound'] for metric in ('missions','chains')):
                for metric in ('missions','chains'):
                    self.solve_position(name,5,metric);extra.append((name,5,metric))
        allpos=positions+extra
        joints=[self.joint(name,j) for name in ('G','Gprime') for j in sorted({p[1] for p in allpos if p[0]==name})]
        rows=[self.make_row(*p) for p in allpos]
        write(self.folder/'panel.json',rows);write(self.folder/'joint_panel.json',joints)
        write(self.folder/'complete.json',dict(record_id=self.rid,scalar_positions=len(rows),main_positions=16,extra_T5_positions=len(extra),closed=sum(q['status']=='closed' for q in rows),open=sum(q['status']=='open' for q in rows)))
        return rows

def aggregate():
    rows=[];joint=[];origins=[];calls=[]
    for item in read(ROOT/'analysis/selection_plan.json')['conditions']:
        folder=ROOT/'runs/origin_target'/item['record_id']
        if (folder/'panel.json').exists():rows.extend(read(folder/'panel.json'))
        if (folder/'joint_panel.json').exists():joint.extend(read(folder/'joint_panel.json'))
        if (folder/'origins.json').exists():
            o=read(folder/'origins.json');origins.append({k:v for k,v in o.items() if k not in ('decisions','verification')})
        for kind in ('queries','joint'):
            for path in sorted((folder/kind).glob('*.json')):
                r=read(path);calls.append(dict(record_id=r['record_id'],kind=kind,origin=r['origin_name'],prefix=r['target_prefix'],metric=r['minimize'],source=rel(path),solver_called=r['solver_seconds']>0,solver_seconds=r['solver_seconds'],elapsed_seconds=r['elapsed_seconds'],status=r['status']))
    main=[q for q in rows if q['target_prefix']!=5];extra=[q for q in rows if q['target_prefix']==5]
    summary=dict(selected_conditions=8,completed_conditions=sum((ROOT/'runs/origin_target'/c['record_id']/'complete.json').exists() for c in read(ROOT/'analysis/selection_plan.json')['conditions']),
      planned_main_positions=128,present_main_positions=len(main),main_closed=sum(q['status']=='closed' for q in main),main_open=sum(q['status']=='open' for q in main),extra_T5_positions=len(extra),
      resolution_counts=dict(Counter(q['resolution'] for q in main)),actual_scalar_MILP_calls=sum(c['solver_called'] for c in calls if c['kind']=='queries'),
      actual_joint_MILP_calls=sum(c['solver_called'] for c in calls if c['kind']=='joint'),saved_solver_calls=len(calls),solver_seconds=sum(c['solver_seconds'] for c in calls),
      zero_positions=sum(q['upper_bound']==0 for q in main),query_accounting=calls)
    for name,value in [('origin_target_panel.json',rows),('origin_target_joint.json',joint),('origin_target_origins.json',origins),('origin_target_summary.json',summary)]:write(ROOT/'analysis'/name,value)
    fields=['record_id','origin','target_prefix','metric','lower_bound','upper_bound','status','resolution','mission_changes','chain_changes','changed_uavs','objective','witness_source']
    with (ROOT/'analysis/origin_target_panel.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(row[k],ensure_ascii=False) if isinstance(row[k],(list,dict)) else row[k] for k in fields})
    print('SUMMARY',{k:v for k,v in summary.items() if k!='query_accounting'},flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--only',nargs='*');p.add_argument('--aggregate',action='store_true');args=p.parse_args()
    plan=read(ROOT/'analysis/selection_plan.json')
    if not args.aggregate:
        for item in plan['conditions']:
            rid=item['record_id']
            if args.only and rid not in args.only:continue
            if (ROOT/'runs/origin_target'/rid/'complete.json').exists():continue
            Panel(rid,plan).run();aggregate()
    aggregate()

if __name__=='__main__':main()
