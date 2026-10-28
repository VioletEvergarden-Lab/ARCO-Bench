"""Public-domain adapters shared by this research companion."""
import contextlib
import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
P = ROOT.parent
R = ROOT / 'arco_codex_research_20260925'
sys.dont_write_bytecode = True
sys.path[:0] = [str(P), str(R)]
import rescore
import event_ledger
from solve_public_preferences import exact_energy, solve_built
from score_preference_sensitivity import objective, quality, compare, TIERS, SETTINGS


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def jl(path): return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
def jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
def csvout(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        w.writerows({k:json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else v for k,v in r.items()} for r in rows)
def decisions(path): return {r['record_id']: json.loads(r['raw_text'])['decisions'] for r in jl(path)}
def signature(d): return tuple(d[k] for k in ('held','path_id','depart_slot','charge_blocks'))
def path_energy(path,payload,uav,corridors):
    if 'physical_parameters' in uav:
        from physical_model import energy
        return energy(path,payload,uav,corridors)
    return exact_energy(path,payload,uav,corridors)
def diff(a,b):
    aa={d['mission_id']:d for d in a}; bb={d['mission_id']:d for d in b}
    return [m for m in aa if signature(aa[m]) != signature(bb[m])]


class Runtime:
    def __init__(self):
        self.sc, self.bridge, self.mods = rescore.runtime()
        self.core, self.formal = self.mods['core'], self.mods['formal']
        self.selector = rescore.load('research30_selector', P/'vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py')
        self.policy = rescore.load('research30_greedy', P/'vendor/scripts/run_candidate_a_v12p1_resource_aware_greedy_baseline_v1.py')

    def evaluate(self,task,ds):
        raw=json.dumps({'record_id':task['record_id'],'decisions':ds})
        parsed, errors=self.selector.parse_public(raw,task)
        return self.selector.public_evaluate(parsed,errors,task,self.formal)

    @contextlib.contextmanager
    def options(self,task):
        inst=task['instance']; H=inst['horizon_slots']; original=self.core.candidate_options
        longest=max(p['travel_slots'] for m in inst['missions'] for p in m['path_options'])
        extended=dict(inst,horizon_slots=H+longest+inst['turnaround_slots']+2*inst['max_charge_blocks']+1)
        cs={c['corridor_id']:c for c in inst['topology']['corridors']}; fleet={u['uav_id']:u for u in inst['fleet']}
        cache={}
        def options(i,v,m,*args,**kwargs):
            key=(m['mission_id'],bool(kwargs.get('ignore_intervention',False)))
            if key not in cache:
                opts=[o for o in original(extended,v,m,*args,**kwargs) if o['depart_slot']<H]
                paths={p['path_id']:p for p in m['path_options']}; u=fleet[m['uav_id']]
                dh=path_energy(m['incoming_deadhead'],0,u,cs) if m.get('incoming_deadhead') else 0
                for o in opts:
                    o['energy_kwh_stored']=o['energy_kwh']
                    o['energy_kwh']=path_energy(paths[o['path_id']],m['payload_kg'],u,cs)+dh
                cache[key]=opts
            return cache[key]
        self.core.candidate_options=options
        try: yield extended
        finally: self.core.candidate_options=original

    def build(self,task):
        with self.options(task) as ext:
            built=self.core.build_model(ext,task['intervention'],task['baseline'])
        built['ub'][-2*len(task['instance']['missions']):]+=1e-6
        return built

    def greedy(self,task):
        policy=self.policy; original_f=policy.feasible_option; original_p=policy.local_priority
        def feasible(inst,mission,o,state,cal,maps):
            s=state[mission['uav_id']]; u=maps['fleet'][mission['uav_id']]
            if o['deadhead_start_slot']<s['clock']: return False
            events=policy.option_events(mission,o); resources=inst['resources']
            for kind,ev,key in zip(('corridor','pad','charger'),events,('corridor_capacity_by_slot_default','pad_capacity_by_slot_default','charger_capacity_by_slot_default')):
                if not policy.capacity_ok(cal[kind],ev,resources[key],maps[kind+'_override']): return False
            after=s['soc']-o['energy_kwh']
            return after>=u['reserve_kwh']-1e-6 and after+o['charge_energy_kwh']<=u['battery_capacity_kwh']+1e-6
        def priority(o,b,m,slot): return original_p(dict(o,energy_kwh=o['energy_kwh_stored']),b,m,slot)
        policy.feasible_option=feasible; policy.local_priority=priority
        try:
            with self.options(task):
                ds,_=policy.construct(task['instance'],task['intervention'],task['baseline'],self.core)
            return ds
        finally: policy.feasible_option=original_f; policy.local_priority=original_p


def add_row(built,vec,lower=-np.inf,upper=np.inf):
    built['A']=vstack([built['A'],csr_matrix(np.asarray(vec).reshape(1,-1))],format='csr')
    built['lb']=np.append(built['lb'],lower); built['ub']=np.append(built['ub'],upper)


def match_vector(built,seed):
    vec=np.zeros(len(built['var_meta']))
    for d in seed:
        mid=d['mission_id']
        inds=[built['hold_idx'][mid]] if d['held'] else [i for i in built['option_indices'][mid] if all(built['var_meta'][i][k]==d[k] for k in ('path_id','depart_slot','charge_blocks'))]
        if len(inds)!=1: raise RuntimeError(('seed option',mid,inds))
        vec[inds[0]]=1
    return vec


def extract(built,x):
    ds=[]
    for mid,h in built['hold_idx'].items():
        if x[h]>.5: d={'mission_id':mid,'uav_id':built['var_meta'][h]['uav_id'],'held':True,'path_id':None,'depart_slot':None,'charge_blocks':0}
        else:
            chosen=[i for i in built['option_indices'][mid] if x[i]>.5]
            if len(chosen)!=1: raise RuntimeError(('extract',mid,chosen))
            m=built['var_meta'][chosen[0]]
            d={k:m[k] for k in ('mission_id','uav_id','path_id','depart_slot','charge_blocks')}; d['held']=False
        ds.append(d)
    return ds


def optimize(built,c):
    result=milp(c,integrality=np.ones(len(c)),bounds=Bounds(np.zeros(len(c)),np.ones(len(c))),
        constraints=LinearConstraint(built['A'],built['lb'],built['ub']),options={'time_limit':60.,'mip_rel_gap':0.,'presolve':True})
    if result.status!=0 or not result.success: raise RuntimeError(result.message)
    return result


def local_repair(rt,task,seed,k=3):
    start=time.perf_counter(); built=rt.build(task); build_sec=time.perf_counter()-start
    add_row(built,match_vector(built,seed),len(seed)-k,np.inf)
    solution=solve_built(built,'base',task['baseline'])
    return solution,build_sec


def occupancy(task,ds,source):
    missions={m['mission_id']:m for m in task['instance']['missions']}; out=[]
    for d in ds:
        if d['held']: continue
        m=missions[d['mission_id']]; p=next(p for p in m['path_options'] if p['path_id']==d['path_id']); dep=d['depart_slot']
        for segment in p['edge_segments']:
            for t in range(dep+segment['offset_slot'],dep+segment['offset_slot']+segment['duration_slots']):
                out.append({'record_id':task['record_id'],'source':source,'mission_id':m['mission_id'],'uav_id':m['uav_id'],'kind':'corridor','resource':segment['corridor_id'],'slot':t})
        arr=dep+p['travel_slots']; turn=task['instance']['turnaround_slots']
        for node,t in ((m['origin_vertiport'],dep),(m['destination_vertiport'],arr)):
            out.append({'record_id':task['record_id'],'source':source,'mission_id':m['mission_id'],'uav_id':m['uav_id'],'kind':'pad','resource':node,'slot':t})
        for t in range(arr+turn,arr+turn+d['charge_blocks']):
            out.append({'record_id':task['record_id'],'source':source,'mission_id':m['mission_id'],'uav_id':m['uav_id'],'kind':'charger','resource':m['destination_vertiport'],'slot':t})
        inc=m.get('incoming_deadhead')
        if inc:
            start=dep-inc['travel_slots']-turn
            for seg in inc['edge_segments']:
                for t in range(start+seg['offset_slot'],start+seg['offset_slot']+seg['duration_slots']): out.append({'record_id':task['record_id'],'source':source,'mission_id':m['mission_id'],'uav_id':m['uav_id'],'kind':'corridor','resource':seg['corridor_id'],'slot':t})
            for node,t in ((inc['node_sequence'][0],start),(m['origin_vertiport'],dep-turn)):
                out.append({'record_id':task['record_id'],'source':source,'mission_id':m['mission_id'],'uav_id':m['uav_id'],'kind':'pad','resource':node,'slot':t})
    return out
