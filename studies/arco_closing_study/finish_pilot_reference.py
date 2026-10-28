"""Complete the already constructed independent C pilot using the final solver."""
from study_common import HERE,read,write
from continuous_engine import Engine
from generate_networks import solo

def main():
    out=HERE/'networks/pilots'; task=read(out/'tasks/PILOT_L04_C.json'); eng=Engine(task)
    individuals=read(out/'individuals.json') if (out/'individuals.json').exists() else []
    reused=len(individuals)==len(eng.fleet) and all(Engine(solo(task,row['uav_id'])).verify(row['result']['decisions'])['admissible'] and not any(d['held'] for d in row['result']['decisions']) for row in individuals)
    if reused:
        print('Reused independently checked individual all-service witnesses',flush=True)
    else: individuals=[]
    for uid in eng.fleet:
        if reused: break
        r=Engine(solo(task,uid)).solve(all_served=True,budget=120,stages=1)
        assert r['decisions'] is not None,uid
        individuals.append({'uav_id':uid,'feasible':True,'result':r})
    write(out/'individuals.json',individuals)
    r=eng.solve(budget=600); write(out/'references/PILOT_L04_C.json',r)
    rows=read(out/'results.json'); rows=[row for row in rows if row['network_id']!='PILOT_L04']; rows.append({'network_id':'PILOT_L04','scale':'L','condition':'C','reference':r,'individual_C_all_service':True,'task_file':'tasks/PILOT_L04_C.json'})
    write(out/'results.json',rows); print('Pilot C',r['optimal'],r['proved_prefix'],r['total_seconds'],flush=True)

if __name__=='__main__': main()
