"""Offline scoring and one-source-of-truth manuscript tables. No model calls/solves.

Run: python build_results.py --output results/current
Extend: append a complete source to sources.json (see README), then run again.
"""
import argparse,collections,csv,json,statistics,time
from datetime import datetime
from pathlib import Path
from rescore import ROOT,rows,score,runtime
from admit import admit,public_runtime
from event_ledger import ledger

TIERS=('urgent_holds','total_holds','repair_distance','weighted_tardiness_min','delay_and_charge_wait_min','energy_kwh')
CATS=('no_candidate_answer','schema_invalid_answer','formally_infeasible_plan','admissible_reference_miss','reference_quality_repair')
ORIGINAL=('deepseek','qwen','luna','policy')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jlines(p,rs):p.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rs),encoding='utf-8')
def csvout(p,rs):
    keys=list(dict.fromkeys(k for r in rs for k in r))
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rs)
def table(rs):
    if not rs:return ''
    ks=list(rs[0]);return '| '+' | '.join(ks)+' |\n|'+ '|'.join('---' for _ in ks)+'|\n'+''.join('| '+' | '.join(str(r.get(k,'')) for k in ks)+' |\n' for r in rs)
def dominates(a,b):
    ds=[a[k]-b[k] for k in TIERS]
    return all(d<=(1e-9 if i==5 else 0) for i,d in enumerate(ds)) and any(d<-(1e-9 if i==5 else 0) for i,d in enumerate(ds))
def dominance_vector(record):
    return {**record['objective'],'energy_kwh':record['operational_totals']['flight_energy_kwh']}
def summary_time(vals):
    vals=sorted(vals)
    if not vals:return {'n':0,'mean_sec':None,'median_sec':None,'p95_sec':None,'max_sec':None}
    q=(len(vals)-1)*.95;l=int(q);p=vals[l]+(vals[min(l+1,len(vals)-1)]-vals[l])*(q-l)
    return {'n':len(vals),'mean_sec':statistics.mean(vals),'median_sec':statistics.median(vals),'p95_sec':p,'max_sec':max(vals)}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sources',type=Path,default=ROOT/'sources.json');ap.add_argument('--output',type=Path,default=ROOT/'results/current');a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    configs=read(a.sources);tasks={p.stem:read(p) for p in sorted((ROOT/'data/public/records').glob('*.json'))};ids=sorted(tasks);assert len(ids)==72
    refs={r['record_id']:r for r in rows(ROOT/'references/public_domain.jsonl')};meta={rid:read(ROOT/f'data/private/evaluator_records/{rid}.json')['metadata'] for rid in ids}
    rt=runtime();prt=public_runtime();selector,_=prt
    refs_tot={rid:ledger(tasks[rid],refs[rid]['decisions'])[0] for rid in ids}
    raw={};rec={};events=[];checks=[]
    def evaluate(s,conf,answers,term):
        scored={r['record_id']:r for r in score(answers,rt)};pub={r['record_id']:r for r in admit(answers,prt)};result={}
        for ans in answers:
            rid=ans['record_id'];sc=scored[rid];pu=pub[rid];ad=pu['admissible'];obj=pu['objective_vector'];ref=refs[rid]['objective']
            rq=ad and all(abs(obj[k]-ref[k])<=(1e-4 if i==5 else 0) for i,k in enumerate(TIERS))
            usable=term.get(rid,{}).get('usable_text',bool(ans.get('raw_text','').strip()))
            category=CATS[0] if not usable else CATS[1] if not pu['schema_valid'] else CATS[2] if not ad else CATS[4] if rq else CATS[3]
            first=next((f'L{i+1}' for i,k in enumerate(TIERS) if abs(obj[k]-ref[k])>(1e-4 if i==5 else 0)),None) if ad else None
            totals={}
            if ad:
                parsed=json.loads(ans['raw_text']);totals,_,ev=ledger(tasks[rid],parsed['decisions']);events.extend({'source':s,'instruction_condition':conf['instruction_condition'],**e} for e in ev)
            item={'source':s,'source_label':conf['label'],'instruction_condition':conf['instruction_condition'],'record_id':rid,'category':category,'schema':pu['schema_valid'],'formal':ad,'reference_quality':rq,'construct_fidelity':sc['required_repair_semantics'],'historical_strict':sc['strict_success'],'first_difference':first,'objective':obj,'reference':ref,'operational_totals':totals,'mechanism':meta[rid]['mechanism'],'terminal_status':term.get(rid,{}).get('terminal_status'),'formal_errors':pu['formal_error_codes']}
            checks.append(pu['schema_valid']==sc['schema_valid'] and ad==sc['formal_feasible'] and bool(rq)==bool(sc['online_admissible'] and sc['oracle_equivalent']))
            result[rid]=item
        return result
    for c in configs:
        s=c['source'];answers=rows(ROOT/c['responses']);assert len(answers)==72 and {r['record_id'] for r in answers}==set(ids),s
        term={r['record_id']:r for r in rows(ROOT/c['terminals'])} if c.get('terminals') else {}
        raw[s]={r['record_id']:r['raw_text'] for r in answers};rec[s]=evaluate(s,c,answers,term)
    paired=[];trace=[];replay_ms=[]
    for c in configs:
        s=c['source']
        if not c.get('pair_with_policy'):continue
        psource='policy_'+s;selected=[];conf={'label':'Policy + '+c['label'],'instruction_condition':c['instruction_condition']+' + code_defined_policy'}
        for rid in ids:
            # Candidate eligibility and comparison use public evaluations only.
            t=time.perf_counter();ev=[]
            for src in ('policy',s):
                parsed,err=selector.parse_public(raw[src][rid],tasks[rid]);ev.append(selector.public_evaluate(parsed,err,tasks[rid],prt[1]))
            pa=ev[0]['schema_valid'] and ev[0]['formal_feasible'];ma=ev[1]['schema_valid'] and ev[1]['formal_feasible']
            cmp=selector.lex_compare(ev[0]['objective_vector'],ev[1]['objective_vector']) if pa and ma else None
            chosen='policy' if pa and (not ma or cmp<=0) else s if ma else None
            elapsed=time.perf_counter()-t;replay_ms.append(elapsed)
            selected.append({'record_id':rid,'raw_text':raw[chosen][rid] if chosen else ''})
            trace.append({'model':s,'record_id':rid,'selected_source':chosen,'tie':cmp==0 if cmp is not None else False,'instruction_condition':c['instruction_condition']})
            p,m=rec['policy'][rid],rec[s][rid];pq,mq=p['reference_quality'],m['reference_quality']
            cell='both' if pq and mq else 'policy_only' if pq else 'model_only' if mq else 'neither'
            add='no_candidate_fallback' if cell=='policy_only' and m['category']==CATS[0] else 'admission_rescue' if cell=='policy_only' and not m['formal'] else 'objective_quality_improvement' if cell=='policy_only' else ''
            paired.append({'model':s,'record_id':rid,'instruction_condition':c['instruction_condition'],'cell':cell,'selected_source':chosen,'policy_contribution_type':add,'model_first_difference':m['first_difference'],'policy_first_difference':p['first_difference']})
        rec[psource]=evaluate(psource,conf,selected,{})
        raw[psource]={x['record_id']:x['raw_text'] for x in selected};jlines(out/f'{psource}_responses.jsonl',selected)
    master=[r for ss in rec.values() for r in ss.values()];assert all(checks)
    old=rows(ROOT/'evidence/candidate_rescoring.jsonl');assert all(rec[r['source']][r['record_id']]['reference_quality']==r['reference_quality'] for r in old)
    # Original selection provenance must remain the same, independently of score counts.
    for s in ('deepseek','qwen','luna'):
        oldtr={r['record_id']:r for r in rows(ROOT/f'evidence/selector_trace_{s}.jsonl')}
        assert all(t['selected_source']==('policy' if oldtr[t['record_id']]['selected_source']=='resource_aware_greedy' else s) for t in trace if t['model']==s)
    t4=[];fig4=[];cf=[];groups=[];l3=[];domrows=[];domsum=[]
    for s,rs in rec.items():
        rr=list(rs.values());head={'source':s,'instruction_condition':rr[0]['instruction_condition'],'n':len(rr)};counts=collections.Counter(r['category'] for r in rr)
        t4.append({**head,**{k:counts[k] for k in CATS},'admissible':sum(r['formal'] for r in rr)})
        cf.append({**head,'construct_fidelity':sum(r['construct_fidelity'] for r in rr),'historical_strict':sum(r['historical_strict'] for r in rr),'reference_quality':sum(r['reference_quality'] for r in rr)})
        fd=collections.Counter(r['first_difference'] for r in rr if r['formal'] and not r['reference_quality'])
        fig4.append({**head,'inadmissible':sum(not r['formal'] for r in rr),**{f'L{i}':fd[f'L{i}'] for i in range(1,7)},'reference_quality':counts[CATS[4]]})
        for mech in sorted({x['mechanism'] for x in rr}):
            sub=[x for x in rr if x['mechanism']==mech];first=collections.Counter(x['first_difference'] for x in sub)
            groups.append({'source':s,'instruction_condition':head['instruction_condition'],'mechanism':mech,'n':len(sub),'admissible':sum(x['formal'] for x in sub),'reference_quality':sum(x['reference_quality'] for x in sub),**{f'L{i}':first[f'L{i}'] for i in range(1,7)}})
        if s not in {c['source'] for c in configs}:continue
        pats=collections.Counter()
        for r in rr:
            if r['first_difference']=='L3':
                d={k:r['operational_totals'].get(k,0)-refs_tot[r['record_id']].get(k,0) for k in ('route_changes','departure_shift_slots','charge_activation_changes','charge_block_change_abs')}
                pat='net_plus_one_departure_shift_slot' if d==dict(route_changes=0,departure_shift_slots=1,charge_activation_changes=0,charge_block_change_abs=0) else 'charging_retiming_exchange' if d==dict(route_changes=0,departure_shift_slots=13,charge_activation_changes=-1,charge_block_change_abs=-1) else 'other'
                pats[pat]+=1
            if r['formal'] and not r['reference_quality']:
                # Fixed observed-candidate pool; reference plans are not witnesses.
                pool={q:dominance_vector(rec[q][r['record_id']]) for q in ORIGINAL if rec[q][r['record_id']]['formal']}
                target=dominance_vector(r)
                ds=[q for q,z in pool.items() if dominates(z,target)]
                domrows.append({'source':s,'record_id':r['record_id'],'instruction_condition':r['instruction_condition'],'dominated':bool(ds),'dominating_sources':ds,'first_difference':r['first_difference'],'comparison_vector':target,'witness_vectors':{q:pool[q] for q in ds},'energy_basis':'unrounded_event_reconstruction_kwh','energy_equality_tolerance_kwh':1e-9})
        l3.append({**head,**{k:pats[k] for k in ('net_plus_one_departure_shift_slot','charging_retiming_exchange','other')}})
        dd=[x for x in domrows if x['source']==s];domsum.append({**head,'admissible_reference_misses':len(dd),'dominated_in_fixed_observed_pool':sum(x['dominated'] for x in dd)})
    t5=[];rescues=[];fig5ops=[]
    for c in configs:
        s=c['source']
        if not c.get('pair_with_policy'):continue
        ps=[p for p in paired if p['model']==s];cnt=collections.Counter(p['cell'] for p in ps);sel=collections.Counter(p['selected_source'] for p in ps);pr=rec['policy_'+s]
        t5.append({'model':s,'instruction_condition':c['instruction_condition'],'n':72,**{k:cnt[k] for k in ('both','policy_only','model_only','neither')},'selected_reference_quality':sum(r['reference_quality'] for r in pr.values()),'selected_admissible':sum(r['formal'] for r in pr.values()),'selected_construct_fidelity':sum(r['construct_fidelity'] for r in pr.values()),'policy_selected':sel['policy'],'model_selected':sel[s]})
        for role in ('policy_only','model_only'):
            pc=[p for p in ps if p['cell']==role];cuts=collections.Counter((p['policy_contribution_type'],p['model_first_difference'] if role=='policy_only' else p['policy_first_difference']) for p in pc)
            rescues.extend({'model':s,'instruction_condition':c['instruction_condition'],'direction':role,'contribution':k[0],'first_difference':k[1],'count':v} for k,v in sorted(cuts.items(),key=str))
            same=[p for p in pc if rec[s][p['record_id']]['formal'] and rec['policy'][p['record_id']]['formal'] and {d['mission_id'] for d in json.loads(raw[s][p['record_id']])['decisions'] if not d['held']}=={d['mission_id'] for d in json.loads(raw['policy'][p['record_id']])['decisions'] if not d['held']}]
            for measure in ('departure_shift_slots','urgent_tardiness_min','routine_tardiness_min','departure_after_release_min','charge_duration_min','flight_energy_kwh'):
                delta=sum(rec[s][p['record_id']]['operational_totals'].get(measure,0)-rec['policy'][p['record_id']]['operational_totals'].get(measure,0) for p in same)
                fig5ops.append({'model':s,'instruction_condition':c['instruction_condition'],'cell':role,'equal_service_tasks':len(same),'measure':measure,'unit':'slots' if measure.endswith('slots') else 'kWh' if measure.endswith('kwh') else 'min','sum_model_minus_policy':delta,'plot_unit':'kWh' if measure.endswith('kwh') else 'min','plot_delta_model_minus_policy':delta*5 if measure.endswith('slots') else delta})
    transitions=[]
    for rid in ids:
        x,y=rec['deepseek'][rid],rec['deepseek_explicit'][rid]
        transitions.append({'record_id':rid,'old_category':x['category'],'explicit_category':y['category'],'old_first_difference':x['first_difference'],'explicit_first_difference':y['first_difference'],'cell':'both' if x['reference_quality'] and y['reference_quality'] else 'explicit_only' if y['reference_quality'] else 'old_only' if x['reference_quality'] else 'neither'})
    transcount=collections.Counter(x['cell'] for x in transitions)
    t6=[{'transition':k,'count':transcount[k],'n':72} for k in ('both','explicit_only','old_only','neither')]
    timing=[];timedetail=[]
    def addtime(source,boundary,entries):
        entries=list(entries);timedetail.extend({'source':source,'boundary':boundary,'record_id':rid,'seconds':v} for rid,v in entries)
        timing.append({'source':source,'boundary':boundary,**summary_time(v for _,v in entries)})
    with (ROOT/'evidence/task_scale_and_archived_runtime.csv').open(encoding='utf-8-sig') as f:scale=list(csv.DictReader(f))
    addtime('MILP_construction','archived six sequential solves; excludes build/load/probe',((x['record_id'],float(x['oracle_runtime_sec'])) for x in scale))
    addtime('policy','archived construct(); excludes file loading/writing',((x['record_id'],x['runtime_sec']) for x in rows(ROOT/'evidence/policy_trace.jsonl')))
    state=collections.defaultdict(dict)
    for r in rows(ROOT/'evidence/attempt_state_ledger.jsonl'):state[r['attempt_id']][r['state']]=r['at_utc']
    primary=rows(ROOT/'evidence/primary_master.jsonl')
    for s in ('deepseek','qwen','luna'):
        entries=[]
        for r in primary:
            if r['model_key']!=s:continue
            t=state[r['attempt_id']]
            if 'POST_INTENT_DURABLE' in t and 'TERMINAL_RESPONSE_FROZEN' in t:entries.append((r['record_id'],(datetime.fromisoformat(t['TERMINAL_RESPONSE_FROZEN'])-datetime.fromisoformat(t['POST_INTENT_DURABLE'])).total_seconds()))
        addtime(s,'archived POST intent to terminal frozen; network/generation/polling/persistence',entries)
        addtime('policy_'+s,'archived local parse+verify+compare after candidates available',((x['record_id'],x['selector_runtime_sec']) for x in rows(ROOT/f'evidence/selector_trace_{s}.jsonl')))
    settings=read(ROOT/'evidence/execution_settings.json')
    addtime('deepseek_explicit','recorded HTTP-call elapsed; includes failed attempts when timed',((x['record_id'],x['latency_seconds']) for x in settings['new'] if x.get('latency_seconds') is not None))
    tokenrows=[]
    for s in ('deepseek','qwen','luna','deepseek_explicit'):
        rs=[r for r in primary if r['model_key']==s] if s!='deepseek_explicit' else settings['new']
        def token(r,k):
            if s!='deepseek_explicit':return r.get(k)
            u=r.get('usage') or {}
            return u.get('completion_tokens_details',{}).get('reasoning_tokens') if k=='reasoning_tokens' else u.get({'input_tokens':'prompt_tokens','output_tokens':'completion_tokens','total_tokens':'total_tokens'}[k])
        for k in ('input_tokens','output_tokens','reasoning_tokens','total_tokens'):
            xs=[token(r,k) for r in rs if token(r,k) is not None]
            tokenrows.append({'source':s,'metric':k,'formal_denominator':72,'records_with_usage':len(xs),'sum_observed_tokens':sum(xs),'median_observed_tokens':statistics.median(xs) if xs else None,'mean_observed_tokens':statistics.mean(xs) if xs else None})
    # Complete-public runs use package-relative recorded usage, not live requests.
    complete_usage=[]
    for c in configs:
        if not c.get('usage_records'):continue
        uu=rows(ROOT/c['usage_records']);s=c['source']
        complete_usage.extend({'source':s,**u} for u in uu)
        addtime(s,'recorded POST intent to terminal; includes timed failed attempts',((u['record_id'],u['latency_seconds']) for u in uu if u.get('latency_seconds') is not None))
        for k in ('input_tokens','output_tokens','reasoning_tokens','visible_output_tokens','cache_hit_tokens','cache_miss_tokens'):
            xs=[u[k] for u in uu if u.get(k) is not None]
            tokenrows.append({'source':s,'metric':k,'formal_denominator':72,'records_with_usage':len(xs),'sum_observed_tokens':sum(xs),'median_observed_tokens':statistics.median(xs) if xs else None,'mean_observed_tokens':statistics.mean(xs) if xs else None})
    endpoints=[]
    for name,file in (('V4-Flash-0731','CORE72_V4FLASH_MASTER.jsonl'),('V4-Pro-0813','CORE72_V4PRO0813_MASTER.jsonl')):
        rr=rows(ROOT/'evidence/supplementary_endpoints'/file)
        endpoints.append({'endpoint':name,'role':'within_family_supplement' if 'Flash' in name else 'temporal_retest','n':len(rr),'admissible':sum(r['schema_valid'] and r['formal_feasible'] for r in rr),'reference_quality':sum(r['schema_valid'] and r['formal_feasible'] and r['oracle_equivalent'] for r in rr),'historical_strict':sum(r['strict_success'] for r in rr)})
    payloads={'Table4_outcomes':t4,'Table5_pairs':t5,'Table6_transitions':t6,'Table6_task_transitions':transitions,'Dominance_summary':domsum,'Dominance_tasks':domrows,'Mechanism_groups':groups,'Figure4a_first_differences':fig4,'Figure4b_L3_patterns':l3,'Figure5_pairs':t5,'Figure5_operating_deltas':fig5ops,'Supplement_construct_fidelity':cf,'Supplement_rescues':rescues,'Supplement_S3_timing':timing,'Supplement_S3_timing_records':timedetail,'Selector_decisions':trace,'Paired_tasks':paired}
    payloads['Supplement_token_usage']=tokenrows;payloads['Supplement_S3_endpoints']=endpoints
    payloads['Complete_public_usage_records']=complete_usage
    for name,rs in payloads.items():csvout(out/(name+'.csv'),rs);dump(out/(name+'.json'),rs)
    jlines(out/'MASTER.jsonl',master);csvout(out/'MASTER.csv',master);csvout(out/'MISSION_EVENTS.csv',events)
    # Reuse reconciled case data; add a derived incumbent event ledger for S1.
    import shutil
    with (ROOT/'evidence/L5_cases.csv').open(encoding='utf-8-sig') as f:l5=[{'instruction_condition':'original_names_order',**r} for r in csv.DictReader(f)]
    csvout(out/'Figure4c_L5_cases.csv',l5)
    with (ROOT/'evidence/case_012_events.csv').open(encoding='utf-8-sig') as f:case=list(csv.DictReader(f))
    _,_,inc=ledger(tasks['CA12_CORE_012'],tasks['CA12_CORE_012']['baseline']['decisions'])
    case.extend({'source':'incumbent','formal_status':'infeasible',**r} for r in inc)
    csvout(out/'Supplement_S1_case012_events.csv',case)
    for file,label in [('changed_construction_counterfactuals.csv','Supplement_construction_domain_changes.csv'),('route_restriction_optima.csv','Supplement_route_restriction_quality.csv'),('capacity_counterfactuals.csv','Supplement_capacity_counterfactuals.csv')]:
        shutil.copy2(ROOT/'evidence'/file,out/label)
    doc='# Machine-generated manuscript tables\n\n'
    for name in ('Table4_outcomes','Table5_pairs','Table6_transitions','Dominance_summary','Mechanism_groups','Supplement_S3_timing'):
        doc+='## '+name+'\n\n'+table(payloads[name])+'\n'
    (out/'TABLES.md').write_text(doc,encoding='utf-8')
    result={'tasks':72,'source_groups':len(rec),'records':len(master),'public_and_offline_score_agreement':all(checks),'original_216_selected_sources_reproduced':True,'archived_576_reference_quality_outcomes_unchanged':True,'counts':{s:sum(r['reference_quality'] for r in rr.values()) for s,rr in rec.items()},'paired_transition':dict(transcount),'dominance':{r['source']:r['dominated_in_fixed_observed_pool'] for r in domsum},'network_calls':0,'reference_solves':0}
    dump(out/'BUILD_RESULT.json',result)
    # Volatile replay timing is separate from deterministic paper data.
    dump(out/'LOCAL_REPLAY_TIMING.json',{'measured_now_public_selection':summary_time(replay_ms),'used_in_paper_historical_timing':False})
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
