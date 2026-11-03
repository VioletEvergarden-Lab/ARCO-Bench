"""ARCO finite options with optional complete locker delivery sorties.

The archived engine is preserved in base_engine.py. New ADDS tasks provide a
return_path on every mission and use load_min/unload_min, zero charging and no
incoming leg. A sortie loads at its origin, flies to the recipient, unloads and
returns immediately to its origin. Delivery arrival remains the due-time event.
All return energy and resource use are in optimization and independent replay.
Legacy tasks retain their original event rules. Grid-aware L3 scaling applies
to both representations; all historical one-minute computations are unchanged.
"""
from base_engine import *
import base_engine as _base
ADDS_RUNTIME_VERSION='adds_complete_sortie_v1'

class Engine(_base.Engine):
    def __init__(self,task,window=None):
        super().__init__(task,window)
        grid=self.timing['departure_grid_min']
        if grid not in (1,0.5,0.25):
            raise ValueError('Supported exact departure grids are 1, 0.5 and 0.25 minutes')
        self.l3_scale=5/grid
        self.complete_sortie=any(m.get('return_path') is not None for m in task['missions'])
        self.returns={}
        if self.complete_sortie:
            if self.timing['max_charge_blocks']!=0:
                raise ValueError('Complete short delivery sorties use no charging')
            for key in ('load_min','unload_min'):
                if key not in self.timing or not math.isfinite(self.timing[key]) or self.timing[key]<0:
                    raise ValueError(('Invalid handling duration',key))
            for m in self.missions.values():
                if not m.get('return_path') or m.get('incoming'):
                    raise ValueError('Every complete sortie needs a return_path and no incoming leg')
                r=m['return_path']
                if r['origin']!=m['destination'] or r['destination']!=m['origin']:
                    raise ValueError(('Return endpoint mismatch',m['mission_id']))
                self.returns[m['mission_id']]=flight(task,r,0.)
                prior=self.base[m['mission_id']]
                if prior['held'] or abs(prior['depart_min']/grid-round(prior['depart_min']/grid))>EPS_TIME:
                    raise ValueError('The complete served incumbent must lie on the chosen departure grid')

    def option(self,m,path_id,departure,charge):
        if not self.complete_sortie:return super().option(m,path_id,departure,charge)
        if charge!=0:raise ValueError('Charging is outside the short-sortie domain')
        mid=m['mission_id'];f=self.info[mid,path_id];ret=self.returns[mid]
        start=departure-self.timing['load_min']
        arrival=departure+f['flight_min']
        return_start=arrival+self.timing['unload_min']
        return_arrival=return_start+ret['flight_min']
        pieces=[('corridor',cid,departure+s,departure+e) for cid,s,e in f['intervals']]
        pieces.extend(('corridor',cid,return_start+s,return_start+e) for cid,s,e in ret['intervals'])
        moves=[(m['origin'],departure),(m['destination'],arrival),
               (m['destination'],return_start),(m['return_path']['destination'],return_arrival)]
        blocks=Counter()
        for kind,node,s,e in pieces:
            for b in buckets(s,e,self.width):blocks[kind,node,b]+=1
        for node,t in moves:blocks['pad',node,point_bucket(t,self.pad_width)]+=1
        prior=self.base[mid]
        delta=20*(path_id!=prior['path_id'])+.2*abs(departure-prior['depart_min'])
        energy=f['energy_kwh']+ret['energy_kwh']
        costs=[0,0,delta,(10 if m['priority']=='urgent' else 1)*max(0,arrival-m['due_min']),departure-m['release_min'],energy]
        return dict(kind='option',mission_id=mid,uav_id=m['uav_id'],path_id=path_id,depart_min=departure,
                    charge_blocks=0,held=False,start_min=start,loading_start_min=start,arrival_min=arrival,
                    charge_start_min=return_start,return_start_min=return_start,return_arrival_min=return_arrival,
                    finish_min=return_arrival,complete_cycle_duration_min=return_arrival-start,
                    energy_kwh=energy,service_energy_kwh=f['energy_kwh'],incoming_energy_kwh=0.,
                    return_energy_kwh=ret['energy_kwh'],charge_kwh=0.,blocks=blocks,intervals=pieces,
                    movements=moves,objectives=costs)

    def options(self):
        was_cached=self.option_cache is not None
        out=super().options()
        if self.complete_sortie and not was_cached:
            out={mid:[o for o in opts if o['energy_kwh']<=self.fleet[o['uav_id']]['battery_capacity_kwh']-
                           self.fleet[o['uav_id']]['reserve_kwh']+SOC_TOL] for mid,opts in out.items()}
            self.option_cache=out
        return out

    def build(self,*args,**kwargs):
        built=super().build(*args,**kwargs)
        # Original scale 5 assumes minute departures. Half-/quarter-minute
        # changes need integer coefficients at scale 10/20 before prefix lock.
        factor=self.l3_scale/built['scales'][2]
        built['costs'][2]*=factor
        built['scales'][2]=self.l3_scale
        if not np.allclose(built['costs'][2],np.rint(built['costs'][2]),atol=1e-7,rtol=0):
            raise ValueError('L3 coefficients are not integral at the grid-aware scale')
        return built

    def solve(self,*args,**kwargs):
        _base.HERE=HERE
        result=super().solve(*args,**kwargs)
        result['runtime_version']=ADDS_RUNTIME_VERSION
        result['l3_scale']=self.l3_scale
        result['complete_sorties']=self.complete_sortie
        return result

    def greedy(self):
        # Same head selection and successor lookahead as the archived engine.
        # Its L3 sort key is scaled to the current grid instead of rounded at 5.
        if self.l3_scale==5:return super().greedy()
        options=self.options();calendar=Counter()
        state={u:dict(clock=v['available_min'],soc=self.initial[u],position=0,held=False) for u,v in self.fleet.items()}
        out=[]
        while any(s['position']<len(self.chains[u]) for u,s in state.items()):
            heads=[(self.chains[u][s['position']],u,s) for u,s in state.items() if s['position']<len(self.chains[u])]
            m,u,s=min(heads,key=lambda x:(-sum(mm['priority']=='urgent' for mm in self.chains[x[1]][x[2]['position']:]),
                         x[0]['release_min'],self.base[x[0]['mission_id']]['depart_min'],x[1],x[0]['sequence_index'],x[0]['mission_id']))
            feasible=[]
            if not s['held']:
                for o in options[m['mission_id']]:
                    if o['start_min']<s['clock']-EPS_TIME:continue
                    after=s['soc']-o['energy_kwh']
                    if after<self.fleet[u]['reserve_kwh']-SOC_TOL or after+o['charge_kwh']>self.fleet[u]['battery_capacity_kwh']+SOC_TOL:continue
                    if any(calendar[key]+count>self.capacity(key) for key,count in o['blocks'].items()):continue
                    feasible.append(o)
            if feasible:
                feasible.sort(key=lambda z:(round(self.l3_scale*z['objectives'][2]),z['objectives'][3],z['objectives'][4],
                                            round(z['energy_kwh'],8),z['depart_min'],z['path_id'],z['charge_blocks']))
                o=feasible[0]
                if s['position']+1<len(self.chains[u]):
                    successor=self.chains[u][s['position']+1]
                    for candidate in feasible:
                        end_soc=s['soc']-candidate['energy_kwh']+candidate['charge_kwh']
                        def successor_ok(nxt):
                            if nxt['start_min']<candidate['finish_min']-EPS_TIME:return False
                            sa=end_soc-nxt['energy_kwh']
                            if sa<self.fleet[u]['reserve_kwh']-SOC_TOL or sa+nxt['charge_kwh']>self.fleet[u]['battery_capacity_kwh']+SOC_TOL:return False
                            return all(calendar[key]+candidate['blocks'][key]+num<=self.capacity(key) for key,num in nxt['blocks'].items())
                        if any(successor_ok(nxt) for nxt in options[successor['mission_id']]):o=candidate;break
                out.append({k:o[k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')})
                calendar.update(o['blocks']);s.update(clock=o['finish_min'],soc=s['soc']-o['energy_kwh']+o['charge_kwh'])
            else:
                s['held']=True;out.append(dict(mission_id=m['mission_id'],uav_id=u,held=True,path_id=None,depart_min=None,charge_blocks=0))
            s['position']+=1
        return sorted(out,key=lambda d:d['mission_id'])

    def verify(self,ds):
        if not self.complete_sortie:return super().verify(ds)
        errors=[];events=[];intervals=[];calendar=Counter();totals=np.zeros(6)
        if not isinstance(ds,list) or len(ds)!=len(self.missions):
            return dict(admissible=False,errors=['SCHEMA_MISSION_COUNT'],objective=None,events=[])
        if any(not isinstance(d,dict) or not isinstance(d.get('mission_id'),str) or not isinstance(d.get('uav_id'),str)
               or (d.get('path_id') is not None and not isinstance(d['path_id'],str)) for d in ds):
            return dict(admissible=False,errors=['SCHEMA_DECISION_TYPES'],objective=None,events=[])
        by={d.get('mission_id'):d for d in ds}
        if len(by)!=len(ds) or set(by)!=set(self.missions):
            return dict(admissible=False,errors=['SCHEMA_MISSION_IDS'],objective=None,events=[])
        for uid,chain in self.chains.items():
            clock=self.fleet[uid]['available_min'];soc=self.initial[uid];held=False
            location=self.fleet[uid]['initial_vertiport']
            for m in chain:
                mid=m['mission_id'];d=by[mid]
                if set(d)!={'mission_id','uav_id','held','path_id','depart_min','charge_blocks'} or d['uav_id']!=uid or type(d['held']) is not bool:
                    errors.append('SCHEMA_DECISION');continue
                if d['held']:
                    if d['path_id'] is not None or d['depart_min'] is not None or type(d['charge_blocks']) is not int or d['charge_blocks']!=0:errors.append('SCHEMA_HOLD')
                    held=True;totals[0]+=m['priority']=='urgent';totals[1]+=1;totals[2]+=1000
                    events.append(dict(record_id=self.task['record_id'],mission_id=mid,uav_id=uid,held=True));continue
                if held:errors.append('SUFFIX_HOLD')
                dep=d['depart_min'];c=d['charge_blocks']
                if type(dep) not in (int,float) or not math.isfinite(dep) or type(c) is not int or c!=0 or d['path_id'] not in self.paths[mid]:
                    errors.append('SCHEMA_PATH_TIME_CHARGE');continue
                if dep<m['release_min']-EPS_TIME or dep>=self.timing['horizon_departure_min']-1e-9 or abs(dep/self.timing['departure_grid_min']-round(dep/self.timing['departure_grid_min']))>EPS_TIME:
                    errors.append('DEPARTURE_DOMAIN')
                path=self.paths[mid][d['path_id']];return_path=m['return_path']
                # Reconstruct both flights directly from source geometry; do
                # not look up options or reuse their resource incidence rows.
                outbound=flight(self.task,path,m['payload_kg']);returning=flight(self.task,return_path,0.)
                if path['origin']!=m['origin'] or path['destination']!=m['destination']:errors.append('SERVICE_PATH_ENDPOINT')
                if return_path['origin']!=m['destination'] or return_path['destination']!=m['origin']:errors.append('RETURN_PATH_ENDPOINT')
                begin=dep-self.timing['load_min'];arrival=dep+outbound['flight_min']
                return_start=arrival+self.timing['unload_min'];return_arrival=return_start+returning['flight_min']
                if begin<clock-EPS_TIME:errors.append('CHAIN_TIME')
                if m['origin']!=location:errors.append('CHAIN_LOCATION')
                s0=soc;sa=s0-outbound['energy_kwh'];sr=sa-returning['energy_kwh']
                if sa<self.fleet[uid]['reserve_kwh']-SOC_TOL:errors.append('SOC_RESERVE_BEFORE_CHARGE')
                if sr<self.fleet[uid]['reserve_kwh']-SOC_TOL:errors.append('SOC_RESERVE_AFTER_RETURN')
                if sr>self.fleet[uid]['battery_capacity_kwh']+SOC_TOL:errors.append('SOC_CAPACITY')
                pieces=[('corridor',cid,dep+s,dep+e) for cid,s,e in outbound['intervals']]
                pieces.extend(('corridor',cid,return_start+s,return_start+e) for cid,s,e in returning['intervals'])
                moves=[(m['origin'],dep),(m['destination'],arrival),(m['destination'],return_start),(return_path['destination'],return_arrival)]
                for kind,node,start,end in pieces:
                    intervals.append(dict(record_id=self.task['record_id'],mission_id=mid,uav_id=uid,kind=kind,resource=node,start_min=start,end_min=end))
                    for b in buckets(start,end,self.width):calendar[kind,node,b]+=1
                for node,t in moves:calendar['pad',node,point_bucket(t,self.pad_width)]+=1
                prior=self.base[mid];rho=20*(d['path_id']!=prior['path_id'])+.2*abs(dep-prior['depart_min'])
                tard=max(0,arrival-m['due_min']);delay=dep-m['release_min'];energy=outbound['energy_kwh']+returning['energy_kwh']
                totals+=np.array([0,0,rho,(10 if m['priority']=='urgent' else 1)*tard,delay,energy])
                events.append(dict(record_id=self.task['record_id'],mission_id=mid,uav_id=uid,held=False,priority=m['priority'],
                      path_id=d['path_id'],depart_min=dep,arrival_min=arrival,loading_start_min=begin,
                      incoming_start_min=None,incoming_arrival_min=None,charge_start_min=return_start,finish_min=return_arrival,
                      return_start_min=return_start,return_arrival_min=return_arrival,return_destination=return_path['destination'],
                      complete_cycle_duration_min=return_arrival-begin,charge_blocks=0,charge_kwh=0.,
                      continuous_flight_min=outbound['flight_min']+returning['flight_min'],
                      soc_before_kwh=s0,soc_service_departure_kwh=s0,soc_arrival_kwh=sa,soc_after_charge_kwh=sa,
                      soc_after_return_kwh=sr,reserve_margin_kwh=sr-self.fleet[uid]['reserve_kwh'],
                      service_energy_kwh=outbound['energy_kwh'],return_energy_kwh=returning['energy_kwh'],flight_energy_kwh=energy,
                      release_wait_min=delay,tardiness_min=tard,route_changed=d['path_id']!=prior['path_id'],departure_shift_min=abs(dep-prior['depart_min'])))
                soc=sr;clock=return_arrival;location=return_path['destination']
        for key,count in calendar.items():
            if count>window_cap(self.task,*key,self.pad_width if key[0]=='pad' else self.width):errors.append(key[0].upper()+'_WINDOW_CAPACITY')
        groups=defaultdict(list)
        for row in intervals:groups[row['kind'],row['resource']].append(row)
        for (kind,node),rows in groups.items():
            endpoints={x for row in rows for x in (row['start_min'],row['end_min'])}
            endpoints.update(x for r in self.task['intervention']['resource_intervals'] if r['kind']==kind and r['resource']==node for x in (r['start_min'],r['end_min']))
            endpoints=sorted(endpoints)
            for a,b in zip(endpoints,endpoints[1:]):
                t=(a+b)/2
                if sum(row['start_min']-1e-9<=t<row['end_min']-1e-9 for row in rows)>cap_at(self.task,kind,node,t):
                    errors.append(kind.upper()+'_ACTUAL_CAPACITY');break
        return dict(admissible=not errors,errors=sorted(set(errors)),objective=dict(zip(TIERS,map(float,totals))) if not errors else None,
                    events=events,resource_intervals=intervals,
                    window_loads=[dict(kind=k,resource=r,bucket=b,width_min=self.pad_width if k=='pad' else self.width,count=value,
                       capacity=window_cap(self.task,k,r,b,self.pad_width if k=='pad' else self.width)) for (k,r,b),value in sorted(calendar.items())],
                    complete_sorties=True,return_energy_in_objective=True,runtime_version=ADDS_RUNTIME_VERSION)
