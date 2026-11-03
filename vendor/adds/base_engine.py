"""Finite public options with continuous flight events and conservative windows."""
import copy
import json
import math
import os
import time
import warnings
from collections import Counter,defaultdict
from types import SimpleNamespace
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix,csr_matrix,vstack
from study_common import TIERS,HERE,write
from solver_backend import solve as solve_sparse_mip,VERSION as SOLVER_VERSION

EPS_TIME=1e-7
QUALITY_TOL=(0.,0.,1e-7,1e-5,1e-5,1e-4)
SOC_TOL=1e-6

def overlap(a,b,c,d): return min(b,d)-max(a,c)>1e-9
def buckets(start,end,width):
    return range(math.floor((start+1e-9)/width),math.ceil((end-1e-9)/width)) if end-start>1e-9 else ()
def point_bucket(t,width): return math.floor((t+1e-9)/width)
def quality(a,b): return all(abs(a[k]-b[k])<=tol+1e-10 for k,tol in zip(TIERS,QUALITY_TOL))
def compare(a,b):
    for k,tol in zip(TIERS,QUALITY_TOL):
        if a[k]<b[k]-tol: return -1
        if a[k]>b[k]+tol: return 1
    return 0

def flight(task,path,payload):
    """Reconstruct distance, phases and energy directly from public geometry."""
    model=task['model']; cs={c['corridor_id']:c for c in task['corridors']}
    area=model['rotors']*math.pi*(model['rotor_diameter_m']/2)**2
    induced=((model['airframe_instrumented_mass_kg']+payload)*model['g_m_s2'])**1.5/math.sqrt(2*model['air_density_kg_m3']*area)
    powers={r:c[0]*induced+c[1] for r,c in model['power_coefficients'].items()}
    up=model['cruise_altitude_m']/model['takeoff_speed_m_s']/60
    down=model['cruise_altitude_m']/model['landing_speed_m_s']/60
    offset=0.; intervals=[]; distance=0.
    current=path['origin']; ids=path['corridor_ids']
    if not ids: raise ValueError('empty flight path')
    for i,cid in enumerate(ids):
        c=cs[cid]; points=c['geometry_xy_km']
        length=sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:]))
        if abs(length-c['distance_km'])>1e-9 or c['origin']!=current: raise ValueError('geometry or path continuity')
        duration=length*1000/model['cruise_speed_m_s']/60+(up if i==0 else 0)+(down if i==len(ids)-1 else 0)
        intervals.append((cid,offset,offset+duration)); offset+=duration; distance+=length; current=c['destination']
    if current!=path['destination']: raise ValueError('path endpoint')
    cruise=distance*1000/model['cruise_speed_m_s']/60
    energy=(powers['takeoff']*up+powers['cruise']*cruise+powers['landing']*down)/60000
    if 'flight_min' in path and abs(path['flight_min']-offset)>1e-9: raise ValueError('public flight coefficient')
    if 'energy_kwh' in path and abs(path['energy_kwh']-energy)>1e-9: raise ValueError('public energy coefficient')
    return {'flight_min':offset,'energy_kwh':energy,'intervals':intervals,'distance_km':distance}

def cap_at(task,kind,resource,t):
    cap=task['resources'][kind].get(resource,0)
    for r in task['intervention']['resource_intervals']:
        if r['kind']==kind and r['resource']==resource and r['start_min']-1e-9<=t<r['end_min']-1e-9: cap=min(cap,r['capacity'])
    return cap

def window_cap(task,kind,resource,bucket,width):
    cap=task['resources'][kind].get(resource,0); s=bucket*width; e=s+width
    for r in task['intervention']['resource_intervals']:
        if r['kind']==kind and r['resource']==resource and overlap(s,e,r['start_min'],r['end_min']): cap=min(cap,r['capacity'])
    return cap

class Engine:
    def __init__(self,task,window=None):
        self.task=task; self.timing=task['timing']; self.width=window or self.timing['resource_window_min']
        self.pad_width=self.timing.get('pad_window_min',self.width)
        self.fleet={u['uav_id']:u for u in task['fleet']}; self.missions={m['mission_id']:m for m in task['missions']}
        self.base={d['mission_id']:d for d in task['baseline']['decisions']}
        self.paths={m['mission_id']:{p['path_id']:p for p in m['paths']} for m in task['missions']}
        self.info={(m['mission_id'],p['path_id']):flight(task,p,m['payload_kg']) for m in task['missions'] for p in m['paths']}
        self.deadhead={m['mission_id']:flight(task,m['incoming'],0.) if m.get('incoming') else None for m in task['missions']}
        self.initial={u:uav['initial_soc_kwh'] for u,uav in self.fleet.items()}; self.initial.update(task['intervention']['initial_soc_overrides'])
        self.chains={u:sorted([m for m in task['missions'] if m['uav_id']==u],key=lambda m:m['sequence_index']) for u in self.fleet}
        self.option_cache=None
        self.capacity_cache={}

    def capacity(self,key):
        if key not in self.capacity_cache: self.capacity_cache[key]=window_cap(self.task,*key,self.pad_width if key[0]=='pad' else self.width)
        return self.capacity_cache[key]

    def service_lower_bounds(self):
        groups=defaultdict(list); bounds=[0,0]; proof=[]
        for chain in self.chains.values():
            if chain: groups[chain[-1]['origin']].append(chain[-1])
        grid=self.timing['departure_grid_min']; H=self.timing['horizon_departure_min']
        for node,finals in groups.items():
            release=min(m['release_min'] for m in finals)
            windows={point_bucket(rank*grid,self.pad_width) for rank in range(math.ceil((release-1e-9)/grid),math.ceil((H-1e-9)/grid))}
            quota=sum(self.capacity(('pad',node,b)) for b in windows)
            urgent=sum(m['priority']=='urgent' for m in finals)
            bounds[0]+=max(0,urgent-quota); bounds[1]+=max(0,len(finals)-quota)
            proof.append({'origin':node,'final_missions':[m['mission_id'] for m in finals],'movement_quota':quota})
        return bounds,proof

    def option(self,m,path_id,departure,charge):
        timing=self.timing; mid=m['mission_id']; path=self.paths[mid][path_id]; f=self.info[mid,path_id]; inc=self.deadhead[mid]
        arrival=departure+f['flight_min']; start=departure-(inc['flight_min']+timing['turnaround_min'] if inc else 0.)
        charge_start=arrival+timing['turnaround_min']; finish=charge_start+charge*timing['charge_block_min']
        blocks=Counter(); intervals=[]; movements=[]
        for cid,s,e in f['intervals']: intervals.append(('corridor',cid,departure+s,departure+e))
        movements.extend([(m['origin'],departure),(m['destination'],arrival)])
        if inc:
            for cid,s,e in inc['intervals']: intervals.append(('corridor',cid,start+s,start+e))
            movements.extend([(m['incoming']['origin'],start),(m['origin'],departure-timing['turnaround_min'])])
        if charge: intervals.append(('charger',m['destination'],charge_start,finish))
        for kind,node,s,e in intervals:
            for b in buckets(s,e,self.width): blocks[kind,node,b]+=1
        for node,t in movements: blocks['pad',node,point_bucket(t,self.pad_width)]+=1
        prior=self.base[mid]; delta=20*(path_id!=prior['path_id'])+.2*abs(departure-prior['depart_min'])+10*((charge>0)!=(prior['charge_blocks']>0))+2*abs(charge-prior['charge_blocks'])
        charge_energy=self.task['model']['charger_input_power_w']*self.task['model']['charging_efficiency']*timing['charge_block_min']/60/1000*charge
        energy=f['energy_kwh']+(inc['energy_kwh'] if inc else 0.)
        objectives=[0,0,delta,(10 if m['priority']=='urgent' else 1)*max(0,arrival-m['due_min']),departure-m['release_min']+charge*timing['charge_block_min'],energy]
        return {'kind':'option','mission_id':mid,'uav_id':m['uav_id'],'path_id':path_id,'depart_min':departure,'charge_blocks':charge,'held':False,'start_min':start,'arrival_min':arrival,'charge_start_min':charge_start,'finish_min':finish,'energy_kwh':energy,'service_energy_kwh':f['energy_kwh'],'incoming_energy_kwh':inc['energy_kwh'] if inc else 0.,'charge_kwh':charge_energy,'blocks':blocks,'intervals':intervals,'movements':movements,'objectives':objectives}

    def options(self):
        if self.option_cache is not None: return self.option_cache
        out={}; grid=self.timing['departure_grid_min']; H=self.timing['horizon_departure_min']
        for mid,m in self.missions.items():
            u=self.fleet[m['uav_id']]; opts=[]
            for pid in self.paths[mid]:
                f=self.info[mid,pid]; inc=self.deadhead[mid]; e=f['energy_kwh']+(inc['energy_kwh'] if inc else 0.)
                if e>u['battery_capacity_kwh']-u['reserve_kwh']+SOC_TOL: continue
                for rank in range(math.ceil((m['release_min']-1e-9)/grid),math.ceil((H-1e-9)/grid)):
                    d=rank*grid
                    if d>=H-1e-9: continue
                    for charge in range(self.timing['max_charge_blocks']+1):
                        o=self.option(m,pid,d,charge)
                        if o['start_min']<u['available_min']-EPS_TIME: continue
                        if any(n>self.capacity(key) for key,n in o['blocks'].items()): continue
                        opts.append(o)
            out[mid]=opts
        self.option_cache=out; return out

    def build(self,seed=None,k=None,all_served=False,allowed=None):
        options=self.options(); meta=[]; indices={}; holds={}
        for mid,m in self.missions.items():
            indices[mid]=[]
            for o in options[mid]: indices[mid].append(len(meta)); meta.append(o)
            holds[mid]=len(meta); meta.append({'kind':'hold','mission_id':mid,'uav_id':m['uav_id'],'held':True,'path_id':None,'depart_min':None,'charge_blocks':0,'objectives':[int(m['priority']=='urgent'),1,1000,0,0,0]})
        n=len(meta); rr=[]; cc=[]; vv=[]; lo=[]; hi=[]
        def row(items,lower=-np.inf,upper=np.inf):
            r=len(lo)
            for i,value in items:
                if value: rr.append(r); cc.append(i); vv.append(value)
            lo.append(lower); hi.append(upper)
        for mid in self.missions:
            row([(i,1) for i in indices[mid]]+[(holds[mid],1)],1,1)
            if all_served: row([(holds[mid],1)],0,0)
        if allowed is not None: row([(i,1) for i,o in enumerate(meta) if o['kind']=='option' and not allowed(o)],0,0)
        resources=defaultdict(list)
        for i,o in enumerate(meta):
            if o['kind']=='option':
                for key,value in o['blocks'].items(): resources[key].append((i,value))
        for key,items in resources.items(): row(items,upper=self.capacity(key))
        big=max([o.get('finish_min',0) for o in meta])+self.timing['horizon_departure_min']+1
        for uid,chain in self.chains.items():
            energy=[]; charging=[]; u=self.fleet[uid]; initial=self.initial[uid]
            for pos,m in enumerate(chain):
                mid=m['mission_id']
                if pos:
                    prev=chain[pos-1]['mission_id']; row([(holds[prev],1),(holds[mid],-1)],upper=0)
                    row([(i,meta[i]['finish_min']) for i in indices[prev]]+[(i,-meta[i]['start_min']) for i in indices[mid]]+[(holds[mid],-big)],upper=0)
                    # Cumulative precedence inequalities strengthen the relaxation
                    # without changing any legal finite-option decisions.
                    for threshold in sorted({meta[i]['start_min'] for i in indices[mid]}):
                        before=[(i,1) for i in indices[prev] if meta[i]['finish_min']>threshold+EPS_TIME]
                        after=[(i,-1) for i in indices[mid] if meta[i]['start_min']>threshold+EPS_TIME]
                        if before: row(before+after+[(holds[mid],-1)],upper=0)
                energy.extend((i,1000*meta[i]['energy_kwh']) for i in indices[mid])
                row(energy+[(i,-value) for i,value in charging],upper=1000*(initial-u['reserve_kwh']+SOC_TOL))
                charging.extend((i,1000*meta[i]['charge_kwh']) for i in indices[mid])
                row(charging+[(i,-value) for i,value in energy],upper=1000*(u['battery_capacity_kwh']-initial+SOC_TOL))
        if seed is not None:
            matches=[]
            for d in seed:
                mid=d['mission_id']
                candidates=[holds[mid]] if d['held'] else [i for i in indices[mid] if all(meta[i][key]==d[key] for key in ('path_id','depart_min','charge_blocks'))]
                if len(candidates)!=1: raise ValueError(('seed outside public options',mid,len(candidates)))
                matches.append((candidates[0],1))
            row(matches,len(seed)-k,np.inf)
        A=coo_matrix((vv,(rr,cc)),shape=(len(lo),n)).tocsr(); costs=np.array([o['objectives'] for o in meta],dtype=float).T
        scales=np.array([1,1,5,1,1,1000]); scaled=costs*scales[:,None]
        return {'A':A,'lb':np.array(lo),'ub':np.array(hi),'meta':meta,'costs':scaled,'scales':scales,'indices':indices,'holds':holds,'base_rows':len(lo),'variables':n}

    def solve(self,seed=None,k=None,all_served=False,budget=600,allowed=None,stages=6):
        start=time.perf_counter(); built=self.build(seed,k,all_served,allowed); built_at=time.perf_counter()
        A=built['A']; lb=built['lb']; ub=built['ub']; phases=[]; last=None; fixed_holds=0; best_x=None; best_vector=None
        progress_path=HERE/'solver_progress'/f"{self.task['record_id']}_{'_'.join(self.fleet)}_{k}_{all_served}_{os.getpid()}.json"
        start_plan=seed if seed is not None else self.greedy(); start_score=self.verify(start_plan)
        if not start_score['admissible']: raise RuntimeError('initial public candidate failed '+str(start_score['errors']))
        if not all_served or not any(d['held'] for d in start_plan):
            start_x=np.zeros(len(built['meta']))
            for d in start_plan:
                mid=d['mission_id']
                pick=built['holds'][mid] if d['held'] else next(i for i in built['indices'][mid] if all(built['meta'][i][key]==d[key] for key in ('path_id','depart_min','charge_blocks')))
                start_x[pick]=1
            last=SimpleNamespace(x=start_x)
            best_x=start_x; best_vector=dict(zip(TIERS,built['costs']@start_x/built['scales']))
        service_bounds,service_proof=self.service_lower_bounds()
        for stage,name in enumerate(TIERS):
            if stage>=stages: break
            remaining=budget-(time.perf_counter()-start)
            if remaining<=0: break
            clock=time.perf_counter(); c=built['costs'][stage].copy(); constant=0.
            nearest=np.rint(c); c[np.abs(c-nearest)<1e-9]=nearest[np.abs(c-nearest)<1e-9]
            if stage==2:
                # L2 has fixed the number of holds. Remove its constant L3
                # contribution from the optimization coefficients.
                c-=1000*built['scales'][2]*built['costs'][1]
                constant=1000*fixed_holds
            write(progress_path,{'record_id':self.task['record_id'],'stage':name,'state':'solving','elapsed_seconds':time.perf_counter()-start,'phases':phases,'variables':built['variables'],'constraints':built['base_rows']})
            analytic=False
            if stage<2 and last is not None:
                current=float(np.dot(c,np.rint(last.x)))
                lower_bound=0 if all_served else service_bounds[stage]
                if abs(current-lower_bound)<1e-8:
                    result=SimpleNamespace(status=0,x=last.x,mip_dual_bound=float(lower_bound),mip_gap=0.); analytic=True
            if not analytic: result=solve_sparse_mip(c,A,lb,ub,remaining,last.x if last is not None else None)
            integer_x=np.rint(result.x) if result.x is not None else None
            record={'tier':name,'status':int(result.status),'seconds':time.perf_counter()-clock,'upper_bound':float(np.dot(c,integer_x)/built['scales'][stage]+constant) if integer_x is not None else None,'lower_bound':float(result.mip_dual_bound/built['scales'][stage]+constant) if getattr(result,'mip_dual_bound',None) is not None else None,'mip_gap':float(result.mip_gap) if getattr(result,'mip_gap',None) is not None else None}
            if analytic: record['proof']='all-service nonnegativity' if all_served else 'final-departure pad quota'; record['public_bound_rows']=service_proof
            phases.append(record)
            if integer_x is not None:
                vector=dict(zip(TIERS,built['costs']@integer_x/built['scales']))
                if best_vector is None or compare(vector,best_vector)<0: best_x=integer_x; best_vector=vector
            write(progress_path,{'record_id':self.task['record_id'],'stage':name,'state':'stage_finished','elapsed_seconds':time.perf_counter()-start,'phases':phases,'best_decisions':self.extract(built,best_x) if best_x is not None else None,'best_objective':best_vector})
            if os.environ.get('ARCO_PHASE_PROGRESS')=='1': print(self.task['record_id'],name,'status',result.status,'elapsed',round(time.perf_counter()-start,1),'bounds',record['lower_bound'],record['upper_bound'],flush=True)
            if result.x is not None: last=result
            if result.status!=0: break
            # Prefixes use the extracted finite-option plan, not nearly binary
            # floating MIP values that can understate a continuous objective.
            value=float(np.dot(c,integer_x))
            if stage<3: value=float(round(value))
            if stage==1: fixed_holds=round(value)
            prefix_tol=0. if stage<2 else 1e-5 if stage in (3,4) else EPS_TIME
            A=vstack([A,csr_matrix(c.reshape(1,-1))],format='csr'); lb=np.append(lb,value-prefix_tol); ub=np.append(ub,value+prefix_tol)
        complete=len(phases)==6 and all(r['status']==0 for r in phases)
        returned_x=last.x if complete and last is not None else best_x
        ds=self.extract(built,returned_x) if returned_x is not None else None
        score=self.verify(ds) if ds else None
        if score is not None and not score['admissible']: raise RuntimeError(('solver produced invalid plan',self.task['record_id'],score['errors']))
        return {'record_id':self.task['record_id'],'optimal':len(phases)==6 and all(r['status']==0 for r in phases),'proved_prefix':sum(r['status']==0 for r in phases),'decisions':ds,'objective':score['objective'] if score else None,'phases':phases,'build_seconds':built_at-start,'total_seconds':time.perf_counter()-start,'variables':built['variables'],'constraints':built['base_rows'],'prefix_values':'extracted finite-option plan','solver_threads':1,'solver':'HiGHS '+SOLVER_VERSION,'warm_start':'preceding tier integer plan','continuous_prefix_tol':1e-5,'anytime_preserves_seed':True,'service_bound_proofs':True}

    @staticmethod
    def extract(built,x):
        out=[]
        for mid,h in built['holds'].items():
            if x[h]>.5: d={k:built['meta'][h][k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')}
            else:
                picks=[i for i in built['indices'][mid] if x[i]>.5]
                if len(picks)!=1: raise RuntimeError(('integer extraction',mid,picks))
                d={k:built['meta'][picks[0]][k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')}
            out.append(d)
        return out

    def greedy(self):
        options=self.options(); calendar=Counter(); state={u:{'clock':v['available_min'],'soc':self.initial[u],'position':0,'held':False} for u,v in self.fleet.items()}; out=[]
        while any(s['position']<len(self.chains[u]) for u,s in state.items()):
            heads=[(self.chains[u][s['position']],u,s) for u,s in state.items() if s['position']<len(self.chains[u])]
            m,u,s=min(heads,key=lambda x:(-sum(mm['priority']=='urgent' for mm in self.chains[x[1]][x[2]['position']:]),x[0]['release_min'],self.base[x[0]['mission_id']]['depart_min'],x[1],x[0]['sequence_index'],x[0]['mission_id']))
            feasible=[]
            if not s['held']:
                for o in options[m['mission_id']]:
                    if o['start_min']<s['clock']-EPS_TIME: continue
                    after=s['soc']-o['energy_kwh']
                    if after<self.fleet[u]['reserve_kwh']-SOC_TOL or after+o['charge_kwh']>self.fleet[u]['battery_capacity_kwh']+SOC_TOL: continue
                    if any(calendar[key]+count>self.capacity(key) for key,count in o['blocks'].items()): continue
                    feasible.append(o)
            if feasible:
                feasible.sort(key=lambda z:(round(5*z['objectives'][2]),z['objectives'][3],z['objectives'][4],round(z['energy_kwh'],8),z['depart_min'],z['path_id'],z['charge_blocks']))
                o=feasible[0]
                if s['position']+1<len(self.chains[u]):
                    successor=self.chains[u][s['position']+1]
                    for candidate in feasible:
                        end_soc=s['soc']-candidate['energy_kwh']+candidate['charge_kwh']
                        def feasible_successor(nxt):
                            if nxt['start_min']<candidate['finish_min']-EPS_TIME: return False
                            sa=end_soc-nxt['energy_kwh']
                            if sa<self.fleet[u]['reserve_kwh']-SOC_TOL or sa+nxt['charge_kwh']>self.fleet[u]['battery_capacity_kwh']+SOC_TOL: return False
                            return all(calendar[key]+candidate['blocks'][key]+num<=self.capacity(key) for key,num in nxt['blocks'].items())
                        if any(feasible_successor(nxt) for nxt in options[successor['mission_id']]): o=candidate; break
                out.append({k:o[k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')}); calendar.update(o['blocks']); s.update(clock=o['finish_min'],soc=s['soc']-o['energy_kwh']+o['charge_kwh'])
            else:
                s['held']=True; out.append({'mission_id':m['mission_id'],'uav_id':u,'held':True,'path_id':None,'depart_min':None,'charge_blocks':0})
            s['position']+=1
        return sorted(out,key=lambda d:d['mission_id'])

    def verify(self,ds):
        errors=[]; events=[]; intervals=[]; calendar=Counter(); totals=np.zeros(6)
        if not isinstance(ds,list) or len(ds)!=len(self.missions): return {'admissible':False,'errors':['SCHEMA_MISSION_COUNT'],'objective':None,'events':[]}
        if any(not isinstance(d,dict) or not isinstance(d.get('mission_id'),str) or not isinstance(d.get('uav_id'),str) or (d.get('path_id') is not None and not isinstance(d['path_id'],str)) for d in ds):
            return {'admissible':False,'errors':['SCHEMA_DECISION_TYPES'],'objective':None,'events':[]}
        by={d.get('mission_id'):d for d in ds if isinstance(d,dict)}
        if len(by)!=len(ds) or set(by)!=set(self.missions): return {'admissible':False,'errors':['SCHEMA_MISSION_IDS'],'objective':None,'events':[]}
        for uid,chain in self.chains.items():
            clock=self.fleet[uid]['available_min']; soc=self.initial[uid]; held=False
            location=self.fleet[uid]['initial_vertiport']
            for m in chain:
                mid=m['mission_id']; d=by[mid]
                if set(d)!={'mission_id','uav_id','held','path_id','depart_min','charge_blocks'} or d['uav_id']!=uid or type(d['held']) is not bool: errors.append('SCHEMA_DECISION'); continue
                if d['held']:
                    if d['path_id'] is not None or d['depart_min'] is not None or type(d['charge_blocks']) is not int or d['charge_blocks']!=0: errors.append('SCHEMA_HOLD')
                    held=True; totals[0]+=m['priority']=='urgent'; totals[1]+=1; totals[2]+=1000; events.append({'record_id':self.task['record_id'],'mission_id':mid,'uav_id':uid,'held':True}); continue
                if held: errors.append('SUFFIX_HOLD')
                dep=d['depart_min']; c=d['charge_blocks']
                if type(dep) not in (int,float) or not math.isfinite(dep) or type(c) is not int or not 0<=c<=self.timing['max_charge_blocks'] or d['path_id'] not in self.paths[mid]: errors.append('SCHEMA_PATH_TIME_CHARGE'); continue
                if dep<m['release_min']-EPS_TIME or dep>=self.timing['horizon_departure_min']-1e-9 or abs(dep/self.timing['departure_grid_min']-round(dep/self.timing['departure_grid_min']))>EPS_TIME: errors.append('DEPARTURE_DOMAIN')
                path=self.paths[mid][d['path_id']]; service=flight(self.task,path,m['payload_kg']); incoming=flight(self.task,m['incoming'],0.) if m.get('incoming') else None
                if path['origin']!=m['origin'] or path['destination']!=m['destination']: errors.append('SERVICE_PATH_ENDPOINT')
                begin=dep-(incoming['flight_min']+self.timing['turnaround_min'] if incoming else 0.)
                if begin<clock-EPS_TIME: errors.append('CHAIN_TIME')
                if (m['incoming']['origin'] if incoming else m['origin'])!=location: errors.append('CHAIN_LOCATION')
                if incoming and m['incoming']['destination']!=m['origin']: errors.append('INCOMING_ENDPOINT')
                arrival=dep+service['flight_min']; charge_start=arrival+self.timing['turnaround_min']; finish=charge_start+c*self.timing['charge_block_min']
                s0=soc; incoming_e=incoming['energy_kwh'] if incoming else 0.; sd=soc-incoming_e; sa=sd-service['energy_kwh']
                q=self.task['model']['charger_input_power_w']*self.task['model']['charging_efficiency']*c*self.timing['charge_block_min']/60000; se=sa+q
                if min(sd,sa)<self.fleet[uid]['reserve_kwh']-SOC_TOL: errors.append('SOC_RESERVE_BEFORE_CHARGE')
                if se>self.fleet[uid]['battery_capacity_kwh']+SOC_TOL: errors.append('SOC_CAPACITY')
                pieces=[('corridor',cid,dep+s,dep+e) for cid,s,e in service['intervals']]; moves=[(m['origin'],dep),(m['destination'],arrival)]
                if incoming:
                    pieces.extend(('corridor',cid,begin+s,begin+e) for cid,s,e in incoming['intervals']); moves.extend([(m['incoming']['origin'],begin),(m['origin'],dep-self.timing['turnaround_min'])])
                if c: pieces.append(('charger',m['destination'],charge_start,finish))
                for kind,node,s,e in pieces:
                    intervals.append({'record_id':self.task['record_id'],'mission_id':mid,'uav_id':uid,'kind':kind,'resource':node,'start_min':s,'end_min':e})
                    for b in buckets(s,e,self.width): calendar[kind,node,b]+=1
                for node,t in moves: calendar['pad',node,point_bucket(t,self.pad_width)]+=1
                prior=self.base[mid]; rho=20*(d['path_id']!=prior['path_id'])+.2*abs(dep-prior['depart_min'])+10*((c>0)!=(prior['charge_blocks']>0))+2*abs(c-prior['charge_blocks'])
                tard=max(0,arrival-m['due_min']); delay=dep-m['release_min']; totals+=np.array([0,0,rho,(10 if m['priority']=='urgent' else 1)*tard,delay+c*self.timing['charge_block_min'],incoming_e+service['energy_kwh']])
                events.append({'record_id':self.task['record_id'],'mission_id':mid,'uav_id':uid,'held':False,'priority':m['priority'],'path_id':d['path_id'],'depart_min':dep,'arrival_min':arrival,'incoming_start_min':begin if incoming else None,'incoming_arrival_min':dep-self.timing['turnaround_min'] if incoming else None,'charge_start_min':charge_start,'finish_min':finish,'charge_blocks':c,'continuous_flight_min':service['flight_min']+(incoming['flight_min'] if incoming else 0.),'soc_before_kwh':s0,'soc_service_departure_kwh':sd,'soc_arrival_kwh':sa,'soc_after_charge_kwh':se,'reserve_margin_kwh':sa-self.fleet[uid]['reserve_kwh'],'flight_energy_kwh':service['energy_kwh']+incoming_e,'charge_kwh':q,'release_wait_min':delay,'tardiness_min':tard,'route_changed':d['path_id']!=prior['path_id'],'departure_shift_min':abs(dep-prior['depart_min'])})
                soc=se; clock=finish; location=m['destination']
        for key,count in calendar.items():
            if count>window_cap(self.task,*key,self.pad_width if key[0]=='pad' else self.width): errors.append(key[0].upper()+'_WINDOW_CAPACITY')
        # Direct continuous sweep is independent of the option-incidence matrix.
        groups=defaultdict(list)
        for r in intervals: groups[r['kind'],r['resource']].append(r)
        for (kind,node),rs in groups.items():
            endpoints={x for r in rs for x in (r['start_min'],r['end_min'])}
            endpoints.update(x for r in self.task['intervention']['resource_intervals'] if r['kind']==kind and r['resource']==node for x in (r['start_min'],r['end_min']))
            endpoints=sorted(endpoints)
            for a,b in zip(endpoints,endpoints[1:]):
                t=(a+b)/2
                if sum(r['start_min']-1e-9<=t<r['end_min']-1e-9 for r in rs)>cap_at(self.task,kind,node,t): errors.append(kind.upper()+'_ACTUAL_CAPACITY'); break
        return {'admissible':not errors,'errors':sorted(set(errors)),'objective':dict(zip(TIERS,map(float,totals))) if not errors else None,'events':events,'resource_intervals':intervals,'window_loads':[{'kind':k,'resource':r,'bucket':b,'width_min':self.pad_width if k=='pad' else self.width,'count':v,'capacity':window_cap(self.task,k,r,b,self.pad_width if k=='pad' else self.width)} for (k,r,b),v in sorted(calendar.items())]}

def parse(raw,task):
    try:
        obj=json.loads(raw)
        if not isinstance(obj,dict) or set(obj)!={'record_id','decisions'} or obj['record_id']!=task['record_id']: raise ValueError('record or wrapper')
        return obj['decisions'],[]
    except (ValueError,TypeError,KeyError): return None,['SCHEMA_JSON_OR_RECORD']
