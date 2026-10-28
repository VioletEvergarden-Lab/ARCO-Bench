"""Radius bounds for at most six representative new-task misses."""
from study_common import HERE,read,write,csvout,TIERS
from continuous_engine import QUALITY_TOL

IDS=['NET_S02_C','NET_M01_B','NET_M01_C','NET_M03_B','NET_L02_B','NET_L02_C']
FIELDS=('held','path_id','depart_min','charge_blocks')
def main():
    rows=[]
    for rid in IDS:
        path=HERE/'networks/candidates'/f'{rid}.json'
        if not path.exists(): continue
        result=read(path)
        if result['R4']['quality']: continue
        reference=read(HERE/'networks/references'/f'{rid}.json'); g={d['mission_id']:d for d in result['G']['decisions']}; ref={d['mission_id']:d for d in reference['decisions']}; vector=result['R4']['score']['objective']; target=reference['objective']
        j=next(i for i,(tier,tol) in enumerate(zip(TIERS,QUALITY_TOL)) if abs(vector[tier]-target[tier])>tol+1e-10)
        # Through L4, earlier network coefficients are integer or multiples of
        # .2, so their acceptance intervals cannot admit a different prefix.
        proved=j<=3 and result['R4']['result']['proved_prefix']>j and vector[TIERS[j]]>target[TIERS[j]]+QUALITY_TOL[j]
        changed=[mid for mid in g if any(g[mid][key]!=ref[mid][key] for key in FIELDS)]
        rows.append({'record_id':rid,'first_miss':TIERS[j],'radius4_stage_optimal':proved,'distance_lower_bound':5 if proved else 0,'distance_upper_bound':len(changed),'upper_witness':'stored global reference','changed_missions':changed,'changed_uavs':sorted({ref[mid]['uav_id'] for mid in changed}),'reference':target,'R4_objective':vector})
    write(HERE/'coordination_bounds/results.json',rows); csvout(HERE/'coordination_bounds/results.csv',rows); print([(r['record_id'],r['distance_lower_bound'],r['distance_upper_bound']) for r in rows])

if __name__=='__main__': main()
