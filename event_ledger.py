"""Unchanged ledger function extracted from the V3 read-only analysis."""
import collections, statistics
COMPONENTS=('urgent_holds','total_holds','route_changes','departure_shift_slots','charge_activation_changes','charge_block_change_abs','urgent_tardiness_min','routine_tardiness_min','departure_after_release_min','charge_duration_min','flight_energy_kwh','flight_duration_min','sum_arrival_slots')

def ledger(task,decisions):
    inst=task['instance'];inter=task['intervention'];mission={m['mission_id']:m for m in inst['missions']};fleet={u['uav_id']:u for u in inst['fleet']};base={d['mission_id']:d for d in task['baseline']['decisions']}
    soc={u:x['initial_soc_kwh'] for u,x in fleet.items()};soc.update({x['uav_id']:x['initial_soc_kwh'] for x in inter['initial_soc_overrides']})
    windows={m:(x['release_slot'],x['due_slot']) for m,x in mission.items()}
    for x in inter['mission_window_overrides']:windows[x['mission_id']]=(x['release_slot'],x['due_slot'])
    out=[];c=collections.Counter();slot=inst['slot_min']
    for d in sorted(decisions,key=lambda x:(x['uav_id'],mission[x['mission_id']]['sequence_index'])):
        m=mission[d['mission_id']];u=fleet[d['uav_id']];b=base[d['mission_id']];rid=task['record_id']
        if d['held']:
            c['total_holds']+=1;c['urgent_holds']+=m['priority']=='urgent'
            out.append({'record_id':rid,'mission_id':m['mission_id'],'uav_id':d['uav_id'],'held':True,'priority':m['priority']});continue
        p=next(x for x in m['path_options'] if x['path_id']==d['path_id']);inc=m.get('incoming_deadhead');ed=inc['energy_kwh'] if inc else 0.0
        # Recompute energy at original precision, as the formal verifier does.
        corridors={x['corridor_id']:x for x in inst['topology']['corridors']}
        def energy(path,payload):
            distance=sum(corridors[k]['distance_km'] for k in path['corridor_ids']);winds=[x['wind_level'] for x in path['edge_segments']]
            return distance*(u['empty_energy_kwh_per_km']+payload*u['payload_energy_kwh_per_km_kg'])*(1+u['wind_energy_multiplier_per_level']*statistics.mean(winds))
        es=energy(p,m['payload_kg']);ed=energy(inc,0) if inc else 0.0
        dep=d['depart_slot'];arr=dep+p['travel_slots'];g=arr+inst['turnaround_slots'];end=g+d['charge_blocks'];release,due=windows[m['mission_id']]
        s0=soc[d['uav_id']];sdep=s0-ed;sarr=sdep-es;send=sarr+d['charge_blocks']*u['charge_kwh_per_block'];soc[d['uav_id']]=send
        row={'record_id':rid,'mission_id':m['mission_id'],'uav_id':d['uav_id'],'held':False,'priority':m['priority'],'path_id':d['path_id'],'baseline_path_id':b['path_id'],'depart_slot':dep,'baseline_depart_slot':b['depart_slot'],'arrival_slot':arr,'release_slot':release,'due_slot':due,'charge_blocks':d['charge_blocks'],'baseline_charge_blocks':b['charge_blocks'],'charge_start_slot':g,'completion_slot':end,'incoming':bool(inc),'incoming_start_slot':dep-inc['travel_slots']-inst['turnaround_slots'] if inc else dep,'incoming_arrival_slot':dep-inst['turnaround_slots'] if inc else None,'soc_before_incoming_kwh':s0,'soc_service_departure_kwh':sdep,'soc_service_arrival_kwh':sarr,'soc_after_charge_kwh':send,'reserve_margin_kwh':sarr-u['reserve_kwh'],'incoming_energy_kwh':ed,'service_energy_kwh':es,'route_changes':int(d['path_id']!=b['path_id']),'departure_shift_slots':abs(dep-b['depart_slot']),'charge_activation_changes':int((d['charge_blocks']>0)!=(b['charge_blocks']>0)),'charge_block_change_abs':abs(d['charge_blocks']-b['charge_blocks']),'urgent_tardiness_min':max(0,arr-due)*slot if m['priority']=='urgent' else 0,'routine_tardiness_min':max(0,arr-due)*slot if m['priority']!='urgent' else 0,'departure_after_release_min':max(0,dep-release)*slot,'charge_duration_min':d['charge_blocks']*slot,'flight_energy_kwh':es+ed}
        row['flight_duration_min']=(p['travel_slots']+(inc['travel_slots'] if inc else 0))*slot
        row['sum_arrival_slots']=arr
        for k in COMPONENTS:c[k]+=row.get(k,0)
        out.append(row)
    obj=[c['urgent_holds'],c['total_holds'],1000*c['total_holds']+20*c['route_changes']+c['departure_shift_slots']+10*c['charge_activation_changes']+2*c['charge_block_change_abs'],10*c['urgent_tardiness_min']+c['routine_tardiness_min'],c['departure_after_release_min']+c['charge_duration_min'],round(c['flight_energy_kwh'],6)]
    c['fleet_completion_slot']=max((x['completion_slot'] for x in out if not x['held']),default=0)
    return dict(c),obj,out
