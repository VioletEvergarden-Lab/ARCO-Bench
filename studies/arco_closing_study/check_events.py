"""Four concrete event-semantic checks, including a nonzero positioning flight."""
import copy
import math
from study_common import HERE,read,write
from continuous_engine import Engine,flight

def main():
    task=read(HERE/'networks/pilots/tasks/PILOT_M02_B.json'); task['intervention']={'resource_intervals':[],'initial_soc_overrides':{}}
    engine=Engine(task); ds=task['baseline']['decisions']; good=engine.verify(ds); assert good['admissible']
    mission=next(m for m in task['missions'] if m['incoming']); event=next(e for e in good['events'] if e['mission_id']==mission['mission_id']); chain=engine.chains[mission['uav_id']]; previous=chain[mission['sequence_index']-2]; prior_event=next(e for e in good['events'] if e['mission_id']==previous['mission_id'])
    inc=flight(task,mission['incoming'],0.); assert inc['energy_kwh']>0 and inc['flight_min']>0
    assert abs(event['incoming_arrival_min']-event['incoming_start_min']-inc['flight_min'])<1e-9
    assert abs(event['depart_min']-event['incoming_arrival_min']-5)<1e-9
    assert prior_event['finish_min']<=event['incoming_start_min']+1e-7
    bad=copy.deepcopy(ds); altered=next(d for d in bad if d['mission_id']==mission['mission_id']); altered['depart_min']=math.floor(prior_event['finish_min']+inc['flight_min']+5-1e-6)
    invalid=engine.verify(bad); assert 'CHAIN_TIME' in invalid['errors']
    checks=read(HERE/'semantic_bridge/checks.json'); checks['nonzero_incoming']={'passed':True,'record_id':task['record_id'],'mission_id':mission['mission_id'],'prior_finish_min':prior_event['finish_min'],'incoming_start_min':event['incoming_start_min'],'incoming_arrival_min':event['incoming_arrival_min'],'service_depart_min':event['depart_min'],'empty_flight_min':inc['flight_min'],'empty_energy_kwh':inc['energy_kwh'],'negative_depart_min':altered['depart_min'],'negative_errors':invalid['errors']}
    write(HERE/'semantic_bridge/checks.json',checks); print(checks['nonzero_incoming'])

if __name__=='__main__': main()
