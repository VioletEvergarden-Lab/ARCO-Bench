"""Compact A5 evidence derived only from completed saved results."""
from pathlib import Path
import csv,json
from optimization_online import compare,quality,TIERS
from optimization_summary import csvout

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'arco_closing_study'
def rows(path):return list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))

def main():
    historical=rows(OLD/'evaluation/per_task.csv')
    models={(r['record_id'],r['source']):r for r in historical if r['layer']=='network' and r['source'] in ('deepseek','luna')}
    old_r4={r['record_id']:r for r in historical if r['layer']=='network' and r['source']=='R4'}
    evidence={};residuals=[];static=[]
    for folder,refdir in [('comparison',OLD/'networks/references'),('new_comparison',ROOT/'new_networks/references')]:
        records=rows(ROOT/'results'/folder/'per_task.csv')
        refs={p.stem:json.loads(p.read_text())['objective'] for p in refdir.glob('*.json')}
        item={'extra_holds':{},'quality_gains_over_R4':{}}
        by={(r['record_id'],r['method']):r for r in records};ids=sorted(set(r['record_id'] for r in records))
        for method in ('G','R4','Full-MILP','Iter-R4','R_frac'):
            sub=[r for r in records if r['method']==method]
            item['extra_holds'][method]={k:sum(json.loads(r['objective'])[k]-refs[r['record_id']][k] for r in sub) for k in TIERS[:2]}
            if method in ('Iter-R4','R_frac'):
                item['quality_gains_over_R4'][method]=[rid for rid in ids if by[rid,method]['reference_quality']=='True' and by[rid,'R4']['reference_quality']=='False']
            for r in sub:
                if r['reference_quality']=='True':continue
                run=json.loads((ROOT/'results'/folder/'runs'/f"{r['record_id']}__{method}.json").read_text())
                residuals.append({'dataset':folder,'record_id':r['record_id'],'method':method,
                    'service_target':r['service_target'],'first_miss':r['first_miss'],'first_gap':float(r['first_gap']),
                    'stop_reason':run['stop_reason'],'last_proved_prefix':run['neighborhoods'][-1]['proved_prefix'] if run['neighborhoods'] else 0,
                    'neighborhoods':len(run['neighborhoods']),'objective':run['objective']})
        if folder=='comparison':
            item['R4_vector_equal_to_historical']={rid:json.loads(by[rid,'R4']['objective'])==json.loads(old_r4[rid]['objective']) for rid in ids}
            for method in ('R4','Iter-R4','R_frac','Full-MILP'):
                for model in ('deepseek','luna'):
                    for rid in ids:
                        dv=json.loads(by[rid,method]['objective']);mr=models[rid,model]
                        mv=json.loads(mr['objective']) if mr['admissible']=='True' else None
                        mq=bool(mv and quality(mv,refs[rid]));dq=quality(dv,refs[rid])
                        static.append({'record_id':rid,'method':method,'historical_model':model,
                            'det_quality':dq,'model_quality':mq,'pair_quality':mq or dq,
                            'model_only_reference_quality':mq and not dq,
                            'model_strictly_improves':bool(mv and compare(mv,dv)<0),
                            'scope':'static selection of stored model answer and new timed deterministic result'})
            screen=rows(ROOT/'results/comparison/historical_model_response_screen.csv')
            item['Full_before_valid_model_response']={}
            for model in ('deepseek','luna'):
                sub=[r for r in screen if r['model']==model and r['deterministic']=='Full-MILP' and r['model_admissible']=='True']
                item['Full_before_valid_model_response'][model]={
                    'denominator':len(sub),'service':sum(r['det_service_before_response']=='True' for r in sub),
                    'quality':sum(r['det_quality_before_response']=='True' for r in sub),
                    'quality_exceptions':[r['record_id'] for r in sub if r['det_quality_before_response']!='True']}
            item['L02_B_times']={method:{k:by['NET_L02_B',method][k] for k in ('first_service_seconds','first_reference_quality_seconds','full_proof_seconds','total_seconds')} for method in ('Full-MILP','R_frac')}
            item['L02_B_times'].update({model:{'historical_response_seconds':float(models['NET_L02_B',model]['latency_seconds'])} for model in ('deepseek','luna')})
        evidence[folder]=item
    out=ROOT/'results/comparison'
    csvout(out/'remaining_gaps.csv',residuals)
    csvout(out/'historical_static_pairing.csv',static)
    (out/'A5_EVIDENCE.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('A5 evidence written; historical R4 identical vectors:',sum(evidence['comparison']['R4_vector_equal_to_historical'].values()))

if __name__=='__main__':main()
