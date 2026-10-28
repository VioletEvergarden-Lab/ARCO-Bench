from pathlib import Path
import csv,json,collections
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
def read(p):return json.loads((BASE/p).read_text(encoding='utf-8-sig'))
def rows(p):
    with (BASE/p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def yes(v):return v is True or v=='True'
def write_csv(name,data):
    keys=list(dict.fromkeys(k for r in data for k in r))
    with (ROOT/'analysis'/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(data)
def main():
    det=[];by={}
    for family,sub,n in [('original','comparison',36),('paired','new_comparison',24)]:
        p=f'arco_focused_revision_20261002/results/{sub}/per_task.csv'
        rs=rows(p)
        for method in ('G','R4','Iter-R4','R_frac','Full-MILP'):
            group=[r for r in rs if r['method']==method]
            assert len(group)==n and len({r['record_id'] for r in group})==n
            times=[float(r['first_reference_quality_seconds']) for r in group if r['first_reference_quality_seconds']]
            d={'family':family,'base_networks':12,'conditions':n,'method':method,
               'admissible':sum(yes(r['admissible']) for r in group),
               'optimal_service':sum(yes(r['service_target']) for r in group),
               'reference_quality':sum(yes(r['reference_quality']) for r in group),
               'latest_first_verified_quality_s':max(times) if times else None,'source':p}
            det.append(d);by[family,method]=d['reference_quality']
    write_csv('network_method_coverage.csv',det)
    outcomes=[]
    score=read('arco_closing_study/evaluation/scores.json')
    details=rows('arco_closing_study/derived/source_per_task.csv')
    for model in ('deepseek','luna'):
        group=[r for r in score if r['layer']=='network' and r['source']==model]
        counts=collections.Counter(r['status'] for r in group);technical=collections.Counter()
        for r in group:
            if r['status']=='no_answer':
                term=read(f"arco_closing_study/online/{model}/attempts/{r['record_id']}/TERMINAL.json")
                technical['no_candidate_output' if term.get('status')=='no_answer' and not term.get('raw_text') else 'transport_failure']+=1
        first=collections.Counter(r['first_miss'] for r in details if r['source']==model and r['status']=='admissible_miss')
        outcomes.append({'family':'original','model':model,'base_networks':12,'attempts':len(group),
            'technical_unavailable':counts['no_answer'],'technical_breakdown':json.dumps(technical),
            'truncated_incomplete':0,'invalid_schema':counts['schema_invalid'],
            'infeasible_complete':counts['infeasible'],'admissible_miss':counts['admissible_miss'],
            'reference_quality':counts['reference_quality'],'admissible':sum(yes(r['admissible']) for r in group),
            'complete_scorable_plans':sum(r['decisions'] is not None for r in group),
            'first_miss_counts':json.dumps(first),'source':'arco_closing_study/evaluation/scores.json'})
    generated=rows('arco_focused_revision_20261002/results/generated_structure/per_attempt.csv')
    for model in ('deepseek','luna'):
        group=[r for r in generated if r['provider']==model and r['repeat']=='1']
        assert len(group)==24
        counts=collections.Counter(r['outcome_class'] for r in group)
        outcomes.append({'family':'paired','model':model,'base_networks':12,'attempts':24,
            'technical_unavailable':counts['no_candidate_output'],'technical_breakdown':json.dumps({'no_candidate_output':counts['no_candidate_output']}),
            'truncated_incomplete':counts['output_token_limit_no_complete_plan'],'invalid_schema':0,
            'infeasible_complete':counts['returned_plan_invalid'],'admissible_miss':sum(yes(r['admissible']) and not yes(r['reference_quality']) for r in group),
            'reference_quality':sum(yes(r['reference_quality']) for r in group),'admissible':sum(yes(r['admissible']) for r in group),
            'complete_scorable_plans':counts['valid_plan']+counts['returned_plan_invalid'],
            'first_miss_counts':'{}','source':'arco_focused_revision_20261002/results/generated_structure/per_attempt.csv'})
    for r in outcomes:
        assert sum(r[k] for k in ('technical_unavailable','truncated_incomplete','invalid_schema','infeasible_complete','admissible_miss','reference_quality'))==r['attempts']
    write_csv('network_model_outcomes.csv',outcomes)
    pairs=[]
    for family,path in [('original','arco_focused_revision_20261002/results/comparison/historical_static_pairing.csv'),
                        ('paired','arco_focused_revision_20261002/results/generation/deterministic_pairing.csv')]:
        rs=rows(path)
        if family=='paired':rs=[r for r in rs if r['repeat']=='1']
        for method in sorted({r['method'] if family=='original' else r['deterministic'] for r in rs}):
            for model in ('deepseek','luna'):
                group=[r for r in rs if (r.get('method',r.get('deterministic'))==method and r.get('historical_model',r.get('provider'))==model)]
                n=36 if family=='original' else 24
                assert len(group)==n
                q=sum(yes(r.get('pair_quality',r.get('reference_quality'))) for r in group)
                pairs.append({'family':family,'method':method,'model':model,'conditions':n,'deterministic_quality':by[family,method],
                              'selected_quality':q,'selected_gain':q-by[family,method],'scope':'actual static selection from independently delivered candidates','source':path})
    write_csv('actual_selection_gains.csv',pairs)
    budget=rows('arco_focused_revision_20261002/results/arrival_selection/budget_summary.csv')
    relevant=[r for r in budget if float(r['seconds'])==600]
    write_csv('paired_availability_600s.csv',relevant)
    print(json.dumps({'deterministic_rows':len(det),'outcomes':outcomes,'static_selection_rows':len(pairs)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
