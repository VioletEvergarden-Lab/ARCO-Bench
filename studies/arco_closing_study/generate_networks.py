"""Seeded geometry, pre-disruption operations and paired resource states."""
import argparse
import copy
import itertools
import math
import random
from collections import Counter
import networkx as nx
from study_common import HERE,write,read
from physical_model import MODEL
from continuous_engine import Engine,flight,window_cap,EPS_TIME,SOC_TOL

CONFIG={
 'version':'independent_networks_v2',
 'formal_seeds':{'S':[41001,41002,41003,41004],'M':[42001,42002,42003,42004],'L':[43001,43002,43003,43004]},
 'pilot_cells':[['S',91001,'A'],['M',92001,'B'],['L',93001,'A'],['L',93002,'C']],
 'scales':{'S':{'nodes':7,'chains':[2,3,4]},'M':{'nodes':11,'chains':[3,4,4,4,5]},'L':{'nodes':16,'chains':[3,3,4,4,4,4,5,5]}},
 'engineering_adjustment':{'count':1,'initial_L_chains':[4,4,5,5,5,5,6,6],'initial_L_missions':40,'final_L_missions':32,'reason':'Independent L-C pilot reached 604.2 s with proved prefix 4; retain 8 UAVs and chains up to 5, reduce task quantity before any formal API generation','evidence':'pilots_L40_engineering/references/PILOT_L04_C.json'},
 'coordinate_box_km':[-.55,.55],'minimum_node_separation_km':.08,
 'graph':'bidirectional union of 3 nearest neighbours plus Euclidean MST',
 'paths':'2 to 4 distinct shortest simple paths, seeded count per OD',
 'incoming_successor_target_fraction':.25,'initial_soc_fraction':.8,
 'priorities':'independent Bernoulli .4; payload independent uniform choice .25/.5 kg',
 'release_slack_min':[0,4],'due_slack_min':{'urgent':[3,8],'routine':[8,15]},
 'final_release':'common pre-disruption outbound wave after all incumbent hub charges finish',
 'horizon_extension_min':18,'A_closure_min':10,
 'B':'lower initial SOC of A-affected UAV to reserve + first-flight energy + 0.005 kWh',
 'C':'A+B plus finite shared-hub pad outage, then ceil(UAV/2) unit movement windows before departure horizon',
 'attempts_per_network':20,'reference_total_budget_seconds':600,
 'solver_threads':1,
 'solver':'HiGHS 1.15.1 through highspy; preceding-tier integer starts',
 'selection_rule':'pre-incumbent valid; A/B optimum all served; C individual all served and joint unavoidable holds; six stages proved',
 'quality_filter':False,
}

def decision(m,pid,d,c):
    return {'mission_id':m['mission_id'],'uav_id':m['uav_id'],'held':False,'path_id':pid,'depart_min':d,'charge_blocks':c}

def construct(scale,seed,index=1,pilot=False):
    rng=random.Random(seed); spec=CONFIG['scales'][scale]; n=spec['nodes']; chains=spec['chains'][:]; rng.shuffle(chains)
    prefix=('PILOT' if pilot else 'NET')+f'_{scale}{index:02d}'
    nodes=[]
    while len(nodes)<n:
        p=[rng.uniform(-.55,.55),rng.uniform(-.55,.55)]
        if all(math.dist(p,v['xy_km'])>=.08 for v in nodes): nodes.append({'vertiport_id':f'V{len(nodes)+1:02d}','xy_km':p})
    pos={v['vertiport_id']:v['xy_km'] for v in nodes}; ids=list(pos); graph=nx.Graph()
    for a,b in itertools.combinations(ids,2): graph.add_edge(a,b,weight=math.dist(pos[a],pos[b]))
    edges=set(tuple(sorted(e)) for e in nx.minimum_spanning_edges(graph,data=False))
    for a in ids:
        for b in sorted((b for b in ids if b!=a),key=lambda b:graph[a][b]['weight'])[:3]: edges.add(tuple(sorted((a,b))))
    graph=nx.Graph(); graph.add_nodes_from(ids)
    corridors=[]; edge_ids={}
    for a,b in sorted(edges):
        graph.add_edge(a,b,weight=math.dist(pos[a],pos[b]))
        for src,dst in [(a,b),(b,a)]:
            cid=f'E_{src}_{dst}'; edge_ids[src,dst]=cid
            corridors.append({'corridor_id':cid,'origin':src,'destination':dst,'distance_km':math.dist(pos[src],pos[dst]),'geometry_xy_km':[pos[src],pos[dst]]})
    hub=rng.choice(ids); chargers=set(rng.sample([v for v in ids if v!=hub],max(2,n//2-1)))|{hub}
    task={'record_id':prefix,'schema_version':'arco_continuous_events_v1','model':copy.deepcopy(MODEL),
      'timing':{'departure_grid_min':1,'resource_window_min':1,'charge_block_min':5,'max_charge_blocks':3,'turnaround_min':5,'horizon_departure_min':240},
      'nodes':nodes,'corridors':corridors,'fleet':[],'missions':[],
      'resources':{'corridor':{c['corridor_id']:rng.choice([1,2]) for c in corridors},'pad':{v:rng.choice([1,2]) for v in ids},'charger':{v:(rng.choice([1,2]) if v in chargers else 0) for v in ids}},
      'baseline':{'decisions':[]},'intervention':{'resource_intervals':[],'initial_soc_overrides':{}}}
    # The hub accepts concurrent arrivals before the outage; its post-outage
    # throughput, rather than ground parking, creates the shared choice.
    task['resources']['pad'][hub]=len(chains)
    path_nodes={}
    def paths(src,dst,payload):
        if (src,dst) not in path_nodes:
            path_nodes[src,dst]=list(itertools.islice(nx.shortest_simple_paths(graph,src,dst,weight='weight'),rng.randint(2,4)))
        result=[]
        for j,seq in enumerate(path_nodes[src,dst]):
            p={'path_id':f'P{j+1}','origin':src,'destination':dst,'corridor_ids':[edge_ids[a,b] for a,b in zip(seq,seq[1:])]}
            info=flight(task,p,payload); p.update(flight_min=info['flight_min'],energy_kwh=info['energy_kwh']); result.append(p)
        return result
    successor_count=sum(chains)-len(chains)
    eligible=[(u,j) for u,c in enumerate(chains) for j in range(1,c-1)]
    incoming_positions=set(rng.sample(eligible,round(.25*successor_count)))
    mid=0
    for u,length in enumerate(chains):
        uid=f'U{u+1:02d}'; origin=rng.choice([v for v in ids if v!=hub]); first=origin
        for j in range(length):
            incoming=None
            if (u,j) in incoming_positions:
                prior=origin
                origin=rng.choice(sorted((v for v in ids if v not in (prior,hub)),key=lambda v:math.dist(pos[prior],pos[v]))[:3])
                incoming=paths(prior,origin,0.)[0]
            if j==length-2: dest=hub
            elif j==length-1: origin=hub; dest=rng.choice([v for v in ids if v!=hub])
            elif j==0: dest=rng.choice([v for v in sorted(chargers) if v not in (origin,hub)])
            else: dest=rng.choice([v for v in ids if v not in (origin,hub)])
            mid+=1; priority='urgent' if rng.random()<.4 else 'routine'; payload=rng.choice([.25,.5])
            m={'mission_id':f'M{mid:03d}','uav_id':uid,'sequence_index':j+1,'origin':origin,'destination':dest,'payload_kg':payload,'priority':priority,'release_min':0,'due_min':240,'paths':paths(origin,dest,payload),'incoming':incoming}
            task['missions'].append(m); task['baseline']['decisions'].append(decision(m,'P1',0,0)); origin=dest
        task['fleet'].append({'uav_id':uid,'initial_soc_kwh':.8*.0999,'battery_capacity_kwh':.0999,'reserve_kwh':.2*.0999,'available_min':rng.randint(0,4),'initial_vertiport':first})
    engine=Engine(task); calendar=Counter(); baseline=[]; specs={}
    for uid,chain in engine.chains.items():
        soc=engine.initial[uid]; clock=engine.fleet[uid]['available_min']; reserve=engine.fleet[uid]['reserve_kwh']
        for j,m in enumerate(chain):
            info=engine.info[m['mission_id'],'P1']; inc=engine.deadhead[m['mission_id']]; e=info['energy_kwh']+(inc['energy_kwh'] if inc else 0)
            arrival_soc=soc-e
            if arrival_soc<reserve-SOC_TOL: raise ValueError('baseline energy between chargers')
            # Charge only enough to reach the next charging opportunity with
            # a 5 Wh margin. This uses pre-disruption geometry and chain data.
            needed=0
            for nxt in chain[j+1:]:
                nf=engine.info[nxt['mission_id'],'P1']; ni=engine.deadhead[nxt['mission_id']]
                needed+=nf['energy_kwh']+(ni['energy_kwh'] if ni else 0)
                if task['resources']['charger'][nxt['destination']]>0: break
            c=0
            if task['resources']['charger'][m['destination']]>0 and j<len(chain)-1:
                c=max(0,math.ceil((reserve+needed+.005-arrival_soc-1e-9)/(.1*.88*5/60)))
            if c>3: raise ValueError('baseline maximum charging duration')
            lower=math.ceil(clock+(inc['flight_min']+5 if inc else 0)-1e-9)
            chosen=None
            for d in range(lower,220):
                o=engine.option(m,'P1',d,c)
                if all(calendar[key]+num<=window_cap(task,*key,1) for key,num in o['blocks'].items()): chosen=o; break
            if chosen is None: raise ValueError('baseline scheduling horizon')
            baseline.append(decision(m,'P1',chosen['depart_min'],c)); calendar.update(chosen['blocks']); clock=chosen['finish_min']; soc=arrival_soc+chosen['charge_kwh']
            m['release_min']=max(0,chosen['depart_min']-rng.randint(0,4))
            low,high=CONFIG['due_slack_min'][m['priority']]; m['due_min']=chosen['arrival_min']+rng.randint(low,high)
            specs[m['mission_id']]=chosen
    # Establish the outbound release wave before imposing any disruptions.
    # Every final job exists only from this release onward; the C outage then
    # allocates a limited number of shared departure windows among these jobs.
    finals={chain[-1]['mission_id']:chain for chain in engine.chains.values()}
    wave=math.ceil(max(specs[chain[-2]['mission_id']]['finish_min'] for chain in engine.chains.values())+1e-9)
    calendar=Counter()
    for mid,o in specs.items():
        if mid not in finals: calendar.update(o['blocks'])
    baseline=[d for d in baseline if d['mission_id'] not in finals]
    for mid,chain in finals.items():
        m=chain[-1]; m['release_min']=wave
        chosen=None
        for d in range(wave,230):
            o=engine.option(m,'P1',d,0)
            if all(calendar[key]+num<=window_cap(task,*key,1) for key,num in o['blocks'].items()): chosen=o; break
        if chosen is None: raise ValueError('pre-disruption outbound wave')
        baseline.append(decision(m,'P1',chosen['depart_min'],0)); calendar.update(chosen['blocks']); specs[mid]=chosen
        low,high=CONFIG['due_slack_min'][m['priority']]; m['due_min']=chosen['arrival_min']+rng.randint(low,high)
    task['baseline']['decisions']=baseline; H=max(d['depart_min'] for d in baseline)+CONFIG['horizon_extension_min']; task['timing']['horizon_departure_min']=H
    before=Engine(task).verify(baseline)
    if not before['admissible']: raise ValueError(('baseline verifier',before['errors']))
    # Choose a used non-final flight, so A necessarily invalidates the incumbent.
    targets=[m for m in task['missions'] if m['sequence_index']<len(engine.chains[m['uav_id']])]
    target=rng.choice(targets); chosen=specs[target['mission_id']]; kind,cid,s,e=chosen['intervals'][0]
    first=engine.chains[target['uav_id']][0]; first_energy=engine.info[first['mission_id'],'P1']['energy_kwh']
    lower_soc=min(.8*.0999-.008,.2*.0999+first_energy+.005)
    closure={'kind':'corridor','resource':cid,'start_min':math.floor(s),'end_min':math.floor(s)+CONFIG['A_closure_min'],'capacity':0}
    arrivals=[specs[chain[-2]['mission_id']]['arrival_min'] for chain in engine.chains.values()]
    cut=wave; K=math.ceil(len(chains)/2)
    if cut>=H-K: raise ValueError('insufficient pre-outage arrival interval')
    states={}
    for condition in 'ABC':
        t=copy.deepcopy(task); t['record_id']=prefix+'_'+condition; t['intervention']['resource_intervals']=[copy.deepcopy(closure)]
        if condition in 'BC': t['intervention']['initial_soc_overrides']={target['uav_id']:lower_soc}
        if condition=='C':
            t['intervention']['resource_intervals'] += [
              {'kind':'pad','resource':hub,'start_min':cut,'end_min':H-K,'capacity':0},
              {'kind':'pad','resource':hub,'start_min':H-K,'end_min':H,'capacity':1}]
        states[condition]=t
    meta={'network_id':prefix,'scale':scale,'seed':seed,'hub':hub,'cut_min':cut,'final_movement_windows':K,'affected_mission':target['mission_id'],'incoming_successors':len(incoming_positions),'successors':successor_count,'pre_incumbent_valid':True,'horizon_min':H}
    return states,meta

def solo(task,uid):
    t=copy.deepcopy(task); t['fleet']=[u for u in t['fleet'] if u['uav_id']==uid]; t['missions']=[m for m in t['missions'] if m['uav_id']==uid]; t['baseline']['decisions']=[d for d in t['baseline']['decisions'] if d['uav_id']==uid]; t['intervention']['initial_soc_overrides']={u:s for u,s in t['intervention']['initial_soc_overrides'].items() if u==uid}
    return t

def pilot(large_only=False):
    out=HERE/'networks'; write(out/'generation_config.json',CONFIG)
    results=read(out/'pilots/results.json')[:2] if large_only else []
    for index,(scale,seed,condition) in enumerate(CONFIG['pilot_cells'],1):
        if large_only and scale!='L': continue
        for attempt in range(CONFIG['attempts_per_network']):
            try:
                states,meta=construct(scale,seed+100*attempt,index,True); task=states[condition]
                if condition=='C':
                    individuals=[]
                    for uid in Engine(task).fleet:
                        r=Engine(solo(task,uid)).solve(all_served=True,budget=120,stages=1); individuals.append({'uav_id':uid,'feasible':r['decisions'] is not None,'result':r})
                        if r['decisions'] is None: raise ValueError('C solo infeasible '+uid)
                break
            except ValueError as exc: print('pilot generation',scale,attempt,str(exc),flush=True)
        else: raise RuntimeError(('pilot exhausted',scale))
        rid=task['record_id']; write(out/'pilots/tasks'/f'{rid}.json',task)
        eng=Engine(task); result=eng.solve(budget=CONFIG['reference_total_budget_seconds']); write(out/'pilots/references'/f'{rid}.json',result)
        meta.update(condition=condition,reference=result,attempt=attempt); results.append(meta); write(out/'pilots/results.json',results)
        print(rid,'optimal',result['optimal'],'prefix',result['proved_prefix'],'seconds',round(result['total_seconds'],2),'variables',result['variables'],flush=True)
        if not result['optimal']: return
        if condition=='C':
            write(out/'pilots/individuals.json',individuals)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--pilot',action='store_true'); parser.add_argument('--large-only',action='store_true'); args=parser.parse_args()
    if args.pilot: pilot(args.large_only)
