"""Read three existing analyses; publish prose only after all 96 terminals.

This script does not score plans, redefine structural indicators, solve, or
contact providers. Refresh the three source analyses before running it.
"""
from pathlib import Path
import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta

ROOT=Path(__file__).resolve().parents[1]
PROVIDERS=('deepseek','luna')
NAMES={'deepseek':'DeepSeek','luna':'Luna'}
CUTS=(30,60,180,300,600)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def truth(value):
    return str(value).lower()=='true'


def number(value,default=0):
    return int(value) if value not in ('',None) else default


def stats(attempts,repeats,pairs,arrival,static,structure_attempts):
    output={}
    diagnosed={r['attempt_id']:r for r in structure_attempts}
    for provider in PROVIDERS:
        main=[r for r in attempts if r['provider']==provider and number(r['repeat'])==1]
        done=[r for r in main if r['status']!='pending']
        valid=[r for r in main if truth(r['admissible'])]
        times=[float(r['available_seconds']) for r in valid if r.get('available_seconds')]
        rep=[r for r in repeats if r['provider']==provider]
        complete_rep=[r for r in rep if number(r['completed'])==3]
        # A terminated provider rejection is a delivery outcome, not an
        # observation of a generated plan. Triplet behavior is assessable only
        # when all three scheduled attempts actually returned scorable plans.
        evaluable_rep=[r for r in complete_rep if all(
            diagnosed.get(aid,{}).get('outcome_class') in ('valid_plan','returned_plan_invalid')
            for aid in json.loads(r['attempt_ids']))]
        repeated_diagnoses=[r for r in structure_attempts if r['provider']==provider and number(r['repeat'])>1]
        repeated_misses=[{k:r.get(k) for k in ('attempt_id','record_id','repeat','service_target','first_miss','first_gap')}
                         for r in repeated_diagnoses if truth(r.get('admissible')) and not truth(r.get('reference_quality'))]
        selected_attempt_ids={aid for r in complete_rep for aid in json.loads(r['attempt_ids'])}
        pair=[r for r in pairs if r['provider']==provider]
        valid_pair=[r for r in pair if r['pair_status']=='both_valid']
        route_observable=[r for r in valid_pair if truth(r['reference_wait_to_reroute'])]
        joint_observable=[r for r in valid_pair if truth(r['reference_route_charge_switch'])]
        item={'scheduled_main':len(main),'completed_main':len(done),
              'main_statuses':dict(Counter(r['status'] for r in main)),
              'admissible':len(valid),'service_target':sum(truth(r['service_target']) for r in main),
              'reference_quality':sum(truth(r['reference_quality']) for r in main),
              'availability_time_hits':len(times),
              'median_available_seconds_among_hits':statistics.median(times) if times else None,
              'max_available_seconds_among_hits':max(times) if times else None,
              'repeated_tasks':len(rep),'completed_three_attempt_tasks':len(complete_rep),
              'quality_hits_out_of_three_distribution':{str(k):sum(number(r['reference_quality_count'])==k for r in complete_rep) for k in range(4)},
              'all_three_admissible':sum(number(r['admissible_count'])==3 for r in complete_rep),
              'all_three_service':sum(number(r['service_count'])==3 for r in complete_rep),
              'at_least_one_quality':sum(number(r['reference_quality_count'])>0 for r in complete_rep),
              'scorable_triplet_tasks':len(evaluable_rep),
              'scorable_triplet_quality_distribution':{str(k):sum(number(r['reference_quality_count'])==k for r in evaluable_rep) for k in range(4)},
              'repeat_provider_rejections':sum(r['outcome_class']=='no_candidate_output' for r in repeated_diagnoses),
              'triplet_provider_rejections':sum(diagnosed.get(aid,{}).get('outcome_class')=='no_candidate_output' for aid in selected_attempt_ids),
              'repeat_scorable_plans':sum(r['outcome_class'] in ('valid_plan','returned_plan_invalid') for r in repeated_diagnoses),
              'delivered_repeat_quality_misses':repeated_misses,
              'scheduled_pairs':len(pair),'pair_statuses':dict(Counter(r['pair_status'] for r in pair)),
              'both_valid_pairs':len(valid_pair),
              'both_quality_pairs':sum(truth(r.get('both_reference_quality')) for r in valid_pair),
              'observed_wait_to_reroute_pairs':sum(truth(r.get('observed_wait_to_reroute')) for r in valid_pair),
              'observed_route_charge_pairs':sum(truth(r.get('observed_route_charge_switch')) for r in valid_pair),
              'reference_route_switch_observable':len(route_observable),
              'reference_route_switch_reproduced':sum(truth(r.get('observed_wait_to_reroute')) for r in route_observable),
              'reference_route_charge_switch_observable':len(joint_observable),
              'reference_route_charge_switch_reproduced':sum(truth(r.get('observed_route_charge_switch')) for r in joint_observable),
              'reference_action_counts_match_pairs':sum(truth(r.get('reference_action_counts_match')) for r in valid_pair),
              'single_budget':{},'arrival_pairs':{},'static_pairs':{}}
        for cutoff in CUTS:
            key=(provider,cutoff)
            if key in arrival:item['single_budget'][str(cutoff)]=arrival[key]
        for method in ('Full-MILP','Iter-R4'):
            pairname=method+'+'+provider
            item['arrival_pairs'][method]={str(c):arrival[pairname,c] for c in CUTS if (pairname,c) in arrival}
            item['static_pairs'][method]=static.get(pairname,{})
        output[provider]=item
    return output


def publication_gate(bindings,attempts,repeats,structure_attempts,structure_pairs,
                     scored_summary,structure_summary,arrival,online):
    problems=[]
    ids={b['attempt_id'] for b in bindings}
    if len(bindings)!=96 or len(ids)!=96:problems.append('冻结清单不是96个唯一预定尝试')
    score_by={r['attempt_id']:r for r in attempts}
    structure_by={r['attempt_id']:r for r in structure_attempts}
    if set(score_by)!=ids or len(attempts)!=96:problems.append('评分表与96项清单未对齐')
    if set(structure_by)!=ids or len(structure_attempts)!=96:problems.append('结构表与96项清单未对齐')
    score_done=sum(r['status']!='pending' for r in attempts)
    struct_done=sum(truth(r['terminal_observed']) for r in structure_attempts)
    terminal_ids={aid for aid in ids if (online/'attempts'/aid/'TERMINAL.json').exists()}
    if len(terminal_ids)!=96:problems.append(f'正式终态文件仅{len(terminal_ids)}/96')
    if score_done!=96 or number(scored_summary.get('completed'))!=96:problems.append(f'评分快照仅{score_done}/96终止')
    if struct_done!=96 or number(structure_summary.get('terminal_attempts'))!=96:problems.append(f'结构快照仅{struct_done}/96终止')
    mismatched=[]
    for aid in ids & set(score_by) & set(structure_by):
        a,b=score_by[aid],structure_by[aid]
        if (a['status']!='pending')!=truth(b['terminal_observed']):mismatched.append(aid);continue
        if a['status']!='pending' and any(truth(a.get(k))!=truth(b.get(k)) for k in ('admissible','service_target','reference_quality')):
            mismatched.append(aid)
    if mismatched:problems.append(f'评分与结构快照有{len(mismatched)}项未同步')
    for provider in PROVIDERS:
        main=[r for r in attempts if r['provider']==provider and number(r['repeat'])==1]
        rep=[r for r in repeats if r['provider']==provider]
        pair=[r for r in structure_pairs if r['provider']==provider]
        if len(main)!=24:problems.append(provider+'主评测不是24项')
        if len(rep)!=12 or any(number(r['completed'])!=3 for r in rep):problems.append(provider+'的12组三次重复尚未完整')
        if len(pair)!=12 or any(r['pair_status']=='not_yet_complete' for r in pair):problems.append(provider+'短长配对快照尚未完整')
        if any(not truth(r['reference_certified']) for r in main):problems.append(provider+'主评测有未认证参考')
        for method in (provider,'Full-MILP+'+provider,'Iter-R4+'+provider):
            if any((method,c) not in arrival or number(arrival[method,c]['completed_tasks'])!=24 for c in CUTS):
                problems.append(method+'的到达重放尚未覆盖24项')
        for method in ('Full-MILP','Iter-R4'):
            item=scored_summary.get('main_static_pairing',{}).get(method+'+'+provider,{})
            if number(item.get('completed_model_attempts'))!=24:problems.append(method+'+'+provider+'静态配对尚未完整')
    for method in ('Full-MILP','Iter-R4'):
        if any((method,c) not in arrival or number(arrival[method,c]['completed_tasks'])!=24 for c in CUTS):
            problems.append(method+'确定性到达记录未完整')
    return {'publishable':not problems,'reasons':problems,
            'live_terminal_attempts':len(terminal_ids),'scored_terminal_attempts':score_done,
            'structure_terminal_attempts':struct_done,'scheduled_attempts':len(bindings)}


def fmt(value):
    return '—' if value is None else f'{value:.2f}'


def fraction(hits,denominator):
    return f'{hits}/{denominator}' if denominator else '—（n=0）'


def report(gate,data,structure_summary,arrival,fragment_path):
    timestamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    title='新结构生成评测：完整结果' if gate['publishable'] else '新结构生成评测：未完成快照'
    lines=['# '+title,'',f'更新：{timestamp}（北京时间）。',
        f"评分源已终止 {gate['scored_terminal_attempts']}/96，结构源已终止 {gate['structure_terminal_attempts']}/96；当前正式终态文件 {gate['live_terminal_attempts']}/96。",'']
    if gate['publishable']:
        lines += ['全部96个预定尝试已终止且三个分析快照一致，可使用下述结果及正文片段。','']
    else:
        lines += ['本次只写快照，不生成可纳正文的完整英文结果段。未完成尝试保留 pending，不计为模型失败。',
                  '完整正文须等96项正式尝试全部终止，并刷新评分、结构诊断及到达重放三份汇总。','']
    lines += ['## 主评测：每模型24个第一次尝试','',
              '| 模型 | 已终止 | 有效计划 | 最优服务 | 参考质量 | 600秒质量 | 可交付时间中位数：秒（命中数） |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for p in PROVIDERS:
        d=data[p];cut=d['single_budget'].get('600',{})
        q600=f"{number(cut.get('reference_quality'))}/{number(cut.get('completed_tasks'))} 已终止" if number(cut.get('completed_tasks'))<24 else f"{number(cut.get('reference_quality'))}/24"
        lines.append(f"| {NAMES[p]} | {d['completed_main']}/24 | {d['admissible']}/24 | {d['service_target']}/24 | {d['reference_quality']}/24 | {q600} | {fmt(d['median_available_seconds_among_hits'])}（{d['availability_time_hits']}/24） |")
    lines += ['','有效、服务与质量列始终显示预定24项分母；快照中未完成项不是失败。时间从本方法读入公开任务到完整方案通过在线验证，包含逐题提示构建、生成/轮询、解析和验证。中位数只在已交付有效计划中计算，命中分母同时给出。','']
    for p in PROVIDERS:lines.append(f"- {NAMES[p]} 主评测状态：{json.dumps(data[p]['main_statuses'],ensure_ascii=False)}。")
    lines += ['', '所有已终止尝试的诊断状态（含重复）：'+json.dumps(structure_summary.get('terminal_outcomes',{}),ensure_ascii=False)+'。',
              '未交付完整计划的原因与返回计划违规沿用结构诊断分类，详见 `results/generated_structure/per_attempt.csv`；此类运行细节不写入正文段落。',
              '', '## 十二个预选任务的交付分布与可评价重复','',
              '| 模型 | 三次均已终止 | 质量交付0/3 | 1/3 | 2/3 | 3/3 | 至少一次质量交付 | 三次均有效 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for p in PROVIDERS:
        d=data[p];n=d['completed_three_attempt_tasks'];dist=d['quality_hits_out_of_three_distribution']
        lines.append(f"| {NAMES[p]} | {n}/12 | {dist['0']} | {dist['1']} | {dist['2']} | {dist['3']} | {fraction(d['at_least_one_quality'],n)} | {fraction(d['all_three_admissible'],n)} |")
    lines += ['','上表是预定请求的计划交付分布，含提供方拒绝，不能直接当作模型行为稳定性。每个基础网络只选一个预定条件重复，未用 best-of-three 替代第一次主结果。',
              '', '| 模型 | 三次均返回可评分计划的任务 | 其中三次均匹配参考 | 三次组内提供方拒绝（含首次） |',
              '|---|---:|---:|---:|']
    for p in PROVIDERS:
        d=data[p];n=d['scorable_triplet_tasks'];q=d['scorable_triplet_quality_distribution']['3']
        lines.append(f"| {NAMES[p]} | {n}/12 | {fraction(q,n)} | {d['triplet_provider_rejections']}/36 |")
    if data['luna']['scorable_triplet_tasks']==0:
        lines += ['',f"DeepSeek 的十二个预选任务中，{data['deepseek']['scorable_triplet_tasks']} 个有三次可评分计划，其中 {data['deepseek']['scorable_triplet_quality_distribution']['3']} 个三次匹配参考质量；Regions S01-short 的首次请求被拒，其余两次均有效，所以可评估组是11而非12。Luna 的 {data['luna']['repeat_provider_rejections']} 次额外请求遭提供方信用额度拒绝，没有一个任务具备三次可评分计划；因此无法作对等的三次重复行为稳定性比较，Luna 的0个三次命中不构成不稳定证据。"]
    lines += ['', '已交付重复中低于参考质量的计划如下。它们是实际计划差异，与未生成计划的拒绝分开：','',
              '| 模型 | 任务 | 重复序号 | 达到最优服务 | 首差层及绝对差值 |','|---|---|---:|---|---:|']
    for p in PROVIDERS:
        for r in data[p]['delivered_repeat_quality_misses']:
            lines.append(f"| {NAMES[p]} | {r['record_id']} | {r['repeat']} | {r['service_target']} | {r['first_miss']} +{float(r['first_gap']):.6g} |")
    lines += ['', '## Full-MILP / Iter-R4 的实际增量','',
              '| 模型配对 | 静态已完成分母 | 静态新增质量匹配 | 600秒重放分母 | 600秒新增服务命中 | 600秒新增质量命中 |',
              '|---|---:|---:|---:|---:|---:|']
    for p in PROVIDERS:
        for method in ('Full-MILP','Iter-R4'):
            static=data[p]['static_pairs'][method];cut=data[p]['arrival_pairs'][method].get('600',{})
            lines.append(f"| {method}+{NAMES[p]} | {number(static.get('completed_model_attempts'))}/24 | {number(static.get('model_only_reference_quality'))} | {number(cut.get('completed_tasks'))}/24 | {number(cut.get('new_service_target_hits'))} | {number(cut.get('new_reference_quality_hits'))} |")
    lines += ['','静态选择使用最终已交付计划。预算选择按独立计时轨迹的真实可用时刻重建并行到达次序，并计入实测比较/选择开销；它不是两方法同轮联合实跑。新增命中均相对于同题确定性方法在同一预算下的结果，不能把毫秒级选择开销当成端到端响应时间。',
              '', '| 方法 | 30秒 服务/质量 | 60秒 | 180秒 | 300秒 | 600秒 |',
              '|---|---:|---:|---:|---:|---:|']
    methods=['Full-MILP','Iter-R4',*PROVIDERS]+[m+'+'+p for m in ('Full-MILP','Iter-R4') for p in PROVIDERS]
    for method in methods:
        fields=[]
        for c in CUTS:
            r=arrival.get((method,c),{});n=number(r.get('completed_tasks'))
            fields.append(f"{number(r.get('service_target'))}/{number(r.get('reference_quality'))}（n={n}/24）")
        lines.append('| '+method+' | '+' | '.join(fields)+' |')
    lines += ['', '## 短长关闭的改道与补能响应','',
              '| 模型 | 两条件均有效 | 观察到等待转改道 | 观察到航路与补能同时切换 | 参考改道切换的重现 | 参考航路—补能切换的重现 |',
              '|---|---:|---:|---:|---:|---:|']
    for p in PROVIDERS:
        d=data[p];n=d['both_valid_pairs']
        lines.append(f"| {NAMES[p]} | {n}/12 | {fraction(d['observed_wait_to_reroute_pairs'],n)} | {fraction(d['observed_route_charge_pairs'],n)} | {fraction(d['reference_route_switch_reproduced'],d['reference_route_switch_observable'])} | {fraction(d['reference_route_charge_switch_reproduced'],d['reference_route_charge_switch_observable'])} |")
    lines += ['','动作指标、参考切换标签和有效配对条件全部沿用 `analyze_generated_structure.py` 的 `main_pairs.csv`。只有短长两项均有有效计划时才判断生成方案的跨条件响应；分母较小时不外推到全部十二个网络。此处描述可观察计划，不推断模型内部推理过程。',
              '', '## 正文片段及更新','']
    if gate['publishable']:
        lines += [f'本轮已生成 `{fragment_path.name}`，包含两段英文结果及一张主评测小表。未返回原因、错误细项与完整重复分布留在研究报告/补充材料。']
    else:
        lines += ['本轮未生成正文完整结果片段。全部96项终止后，先刷新以下三个既有分析，再运行本脚本：']
    lines += ['', '```powershell',
              'python arco_focused_revision_20261002/scripts/score_new_models.py',
              'python arco_focused_revision_20261002/scripts/selection_arrival_analysis.py',
              'python arco_focused_revision_20261002/scripts/analyze_generated_structure.py',
              'python arco_focused_revision_20261002/scripts/summarize_final_generation.py',
              '```','']
    return '\n'.join(lines)


def arrival_gain_sentence(data,method):
    clauses=[]
    for p in PROVIDERS:
        values=data[p]['arrival_pairs'][method]
        gains=[(c,number(values[str(c)].get('new_service_target_hits')),
                  number(values[str(c)].get('new_reference_quality_hits'))) for c in CUTS]
        if all(s==0 and q==0 for c,s,q in gains):
            clauses.append(NAMES[p]+' adds no service or reference-quality coverage at these cutoffs')
        else:
            detail=', '.join(f'{c} s: {s}/{q}' for c,s,q in gains)
            clauses.append(NAMES[p]+f' adds the following service/quality task counts ({detail})')
    return '; '.join(clauses)+'.'


def transition_sentence(data,kind,label):
    clauses=[]
    for provider in PROVIDERS:
        d=data[provider];denom=d['reference_'+kind+'_observable'];hits=d['reference_'+kind+'_reproduced']
        if denom:
            clauses.append(f"{NAMES[provider]} reproduces {hits}/{denom} evaluable reference {label} transitions")
        else:
            clauses.append(f"no reference {label} transition has two admissible {NAMES[provider]} plans")
    return '; '.join(clauses)+'. '


def fragment(data,arrival):
    d,l=data['deepseek'],data['luna']
    p1=(r'\subsection{Generated repairs on the paired structures}'+'\n'+r'\label{sec:new_generation}'+'\n\n'+
        f"On the 24 paired structural tasks, DeepSeek and Luna deliver admissible plans on {d['admissible']} and {l['admissible']} tasks, respectively "
        +r'(Table~\ref{tab:new_generation}). '+
        f"They attain optimal urgent and total service on {d['service_target']} and {l['service_target']} tasks and reference quality on "
        f"{d['reference_quality']} and {l['reference_quality']}. ")
    full_gains=[number(data[p]['static_pairs']['Full-MILP'].get('model_only_reference_quality')) for p in PROVIDERS]
    iter_gains=[number(data[p]['static_pairs']['Iter-R4'].get('model_only_reference_quality')) for p in PROVIDERS]
    if full_gains==[0,0]:
        p1+='Neither model adds a final reference-quality match to Full-MILP. '
    else:
        p1+=f'Static selection adds {full_gains[0]} and {full_gains[1]} reference-quality matches to Full-MILP. '
    p1+=f'Static selection adds {iter_gains[0]} and {iter_gains[1]} matches to iterative repair. '
    ig600=[number(data[p]['arrival_pairs']['Iter-R4']['600'].get('new_reference_quality_hits')) for p in PROVIDERS]
    p1+=(f'By 600 s, the corresponding gains over iterative repair are {ig600[0]} and {ig600[1]}. '
         'Replaying the independently measured arrival trajectories at 30, 60, 180, 300 and 600 s, including comparison overhead, ')
    fullzero=all(number(data[p]['arrival_pairs']['Full-MILP'][str(c)].get(k))==0
                 for p in PROVIDERS for c in CUTS for k in ('new_service_target_hits','new_reference_quality_hits'))
    if fullzero:
        p1+='gives no additional service or reference-quality coverage over Full-MILP. '
    else:
        p1=p1.rsplit('Replaying',1)[0]+'The independent-trajectory reconstruction, including comparison overhead, gives the following additional coverage over Full-MILP: '+arrival_gain_sentence(data,'Full-MILP')+' '
    table=[r'\begin{table}[tbp]',r'\centering\small',
        r'\caption{First-attempt generation on the 24 paired structural tasks. All outcome counts use 24 attempts. Availability is measured through online verification; its median uses the admissible plans, whose count is shown.}',
        r'\label{tab:new_generation}',r'\begin{tabular}{@{}lrrrrr@{}}',r'\toprule',
        r'Model & Admissible & Service & Quality & \shortstack{Quality\\by 600 s} & \shortstack{Median\\availability (s)}\\',r'\midrule']
    for p in PROVIDERS:
        x=data[p];median=f"{x['median_available_seconds_among_hits']:.2f}" if x['median_available_seconds_among_hits'] is not None else r'---'
        table.append(f"{NAMES[p]} & {x['admissible']} & {x['service_target']} & {x['reference_quality']} & {number(x['single_budget']['600']['reference_quality'])} & {median}"+r'\\')
    table += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    p2=(f"DeepSeek delivers reference quality in all three scheduled attempts on "
        f"{d['quality_hits_out_of_three_distribution']['3']} of the twelve preselected tasks. ")
    if l['scorable_triplet_tasks']==0:
        p2+='Provider rejections prevent an equivalent three-attempt assessment for Luna. '
    else:
        p2+=f"For Luna, {l['scorable_triplet_tasks']} tasks have three scorable plans and {l['scorable_triplet_quality_distribution']['3']} match reference quality throughout. "
    repeat_misses=d['delivered_repeat_quality_misses']+l['delivered_repeat_quality_misses']
    if repeat_misses and all(truth(r['service_target']) and r['first_miss']=='repair_distance' for r in repeat_misses):
        p2+=(f"The {len(l['delivered_repeat_quality_misses'])} delivered Luna repeats and {len(d['delivered_repeat_quality_misses'])} DeepSeek repeat "
             'below reference quality preserve optimal service but incur additional plan-change cost. ')
    p2+=(
        f"Both closure conditions have admissible plans for {d['both_valid_pairs']}/12 DeepSeek and {l['both_valid_pairs']}/12 Luna pairs. "
        +transition_sentence(data,'route_switch','waiting-to-rerouting')
        +transition_sentence(data,'route_charge_switch','joint route--charging')+
        'The paired plans show how the repair actions respond to the changed closure duration.')
    return '% Complete 96-attempt summary; generated only after synchronized terminal checks.\n'+p1+'\n\n'+'\n'.join(table)+'\n\n'+p2+'\n'


def latex_escape(value):
    return str(value).replace('\\',r'\textbackslash{}').replace('_',r'\_').replace('%',r'\%').replace('&',r'\&').replace('#',r'\#')


def details_fragment(data,arrival,structure_attempts,structure_summary):
    labels={'valid_plan':'Admissible returned plan',
            'no_candidate_output':'No candidate output',
            'output_token_limit_no_complete_plan':'Output limit; no complete plan',
            'provider_http_failure':'Provider HTTP failure',
            'transport_failure':'Transport failure',
            'returned_plan_invalid':'Inadmissible returned plan',
            'schema_or_parse_failure':'Schema or parsing failure',
            'model_identity_mismatch':'Unexpected model identity',
            'no_complete_plan':'No complete plan'}
    classes=sorted(set(r['outcome_class'] for r in structure_attempts))
    lines=['% Complete 96-attempt supplementary detail; first attempts and repeats remain separate.',
           r'\subsection{Generated repairs on the paired structures: outcomes and repetitions}',
           r'\label{sec:s_new_generation}',
           'The main evaluation contains one attempt on each of the 24 tasks per model. Twelve preselected tasks per model have two additional independent attempts, giving 48 attempts per model and 96 overall. Outcome categories retain unsuccessful deliveries in the planned denominators.',
           r'\begin{table}[htbp]',r'\centering\small',
           r'\caption{Delivery and plan outcomes. Main columns contain 24 first attempts per model; all-attempt columns contain 48 attempts per model, including the first attempts.}',
           r'\label{tab:s_generation_outcomes}',r'\begin{tabular}{@{}lrrrr@{}}',r'\toprule',
           r'Outcome & \shortstack{DeepSeek\\main} & \shortstack{Luna\\main} & \shortstack{DeepSeek\\all} & \shortstack{Luna\\all}\\',r'\midrule']
    for cls in classes:
        values=[]
        for main_only in (True,False):
            for provider in PROVIDERS:
                values.append(sum(r['provider']==provider and r['outcome_class']==cls and (not main_only or number(r['repeat'])==1) for r in structure_attempts))
        lines.append(labels.get(cls,latex_escape(cls))+' & '+' & '.join(map(str,values))+r'\\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}',
              'The following table summarizes reference-quality delivery across three scheduled attempts. Unavailable responses contribute no delivered plan; their causes are classified above.',
              r'\begin{table}[htbp]',r'\centering\small',
              r'\caption{Reference-quality delivery across twelve tasks with three scheduled attempts per model, including provider refusals. Each row sums to twelve tasks.}',
              r'\label{tab:s_generation_repeat}',r'\begin{tabular}{@{}lrrrrrr@{}}',r'\toprule',
              r'Model & 0/3 & 1/3 & 2/3 & 3/3 & \shortstack{All three\\admissible} & \shortstack{All three\\optimal service}\\',r'\midrule']
    for provider in PROVIDERS:
        d=data[provider];dist=d['quality_hits_out_of_three_distribution']
        values=[dist[str(k)] for k in range(4)]+[d['all_three_admissible'],d['all_three_service']]
        lines.append(NAMES[provider]+' & '+' & '.join(map(str,values))+r'\\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    lines += [f"DeepSeek has {data['deepseek']['scorable_triplet_tasks']} tasks with three scorable returned plans, of which {data['deepseek']['scorable_triplet_quality_distribution']['3']} attain reference quality throughout; one selected task lost its first response to a provider refusal. "
              f"Luna has {data['luna']['scorable_triplet_tasks']} such tasks: {data['luna']['repeat_provider_rejections']} of its 24 additional attempts were rejected for provider credit exhaustion. "
              'The available observations therefore do not support a three-attempt behavioral comparison for Luna.']
    misses=[]
    for provider in PROVIDERS:
        for r in data[provider]['delivered_repeat_quality_misses']:
            rid=r['record_id'].replace('NEW_','').replace('_',' ')
            if r['first_miss']=='repair_distance':
                misses.append(f"{NAMES[provider]} on {latex_escape(rid)} (attempt {r['repeat']}, $L_3+{float(r['first_gap']):.6g}$)")
    if misses:
        lines += ['Among delivered repeats, '+ '; '.join(misses)+ ' preserve optimal service but differ from reference quality in plan-change cost.']
    lines += [
              'A plan delivered after 600 s remains part of final plan-quality evaluation but is unavailable at the 600-s decision cutoff. ']
    late=[]
    for provider in PROVIDERS:
        d=data[provider];cut=d['single_budget']['600']
        late.append(f"{NAMES[provider]} has {d['admissible']-number(cut['admissible'])} admissible plans, including {d['reference_quality']-number(cut['reference_quality'])} reference-quality plans, first available after 600 s")
    lines[-1]+='; '.join(late)+'.'
    lines += [r'\begin{table}[htbp]',r'\centering\small',
              r'\caption{Available outcomes by 600 s versus final reference quality. Each row covers the same 24 first-attempt tasks. Pair rows reconstruct selection from independently timed arrivals, including measured comparison overhead; their final column uses static selection of final delivered plans.}',
              r'\label{tab:s_generation_arrival}',r'\begin{tabular}{@{}lrrrr@{}}',r'\toprule',
              r'Method & \shortstack{Feasible\\by 600 s} & \shortstack{Service\\by 600 s} & \shortstack{Quality\\by 600 s} & \shortstack{Final\\quality}\\',r'\midrule']
    det={r['method']:r for r in structure_summary['deterministic']}
    methodnames={'Full-MILP':'Full-MILP','Iter-R4':r'Iter-$R_4$',**NAMES}
    methods=['Full-MILP','Iter-R4',*PROVIDERS]+[m+'+'+p for m in ('Full-MILP','Iter-R4') for p in PROVIDERS]
    for method in methods:
        cut=arrival[method,600]
        if '+' in method:
            base,provider=method.split('+')
            final=number(data[provider]['static_pairs'][base]['reference_quality'])
            label=methodnames[base]+' + '+NAMES[provider]
        elif method in PROVIDERS:
            final=data[method]['reference_quality'];label=NAMES[method]
        else:
            final=det[method]['reference_quality'];label=methodnames[method]
        values=[number(cut[k]) for k in ('admissible','service_target','reference_quality')]+[final]
        lines.append(label+' & '+' & '.join(map(str,values))+r'\\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}',
              'The short--long action comparison uses only first-attempt pairs with two admissible plans. Waiting-to-rerouting and joint route--charging indicators follow the same definitions as the reference-pair analysis. Pair availability, reference transitions evaluable within that subset, and observed reproductions are retained separately in the accompanying per-pair data.','']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--online',type=Path,default=ROOT/'online/new_generation')
    p.add_argument('--score-dir',type=Path,default=ROOT/'results/generation')
    p.add_argument('--arrival-dir',type=Path,default=ROOT/'results/arrival_selection')
    p.add_argument('--structure-dir',type=Path,default=ROOT/'results/generated_structure')
    p.add_argument('--report',type=Path,default=ROOT/'D_FINDINGS.md')
    p.add_argument('--fragment',type=Path,default=ROOT/'paper_fragments/new_generation.tex')
    p.add_argument('--details',type=Path,default=ROOT/'paper_fragments/new_generation_details.tex')
    a=p.parse_args()
    bindings=read(a.online/'BINDINGS.json');scored=read(a.score_dir/'summary.json')
    structure=read(a.structure_dir/'summary.json')
    attempts=rows(a.score_dir/'per_attempt.csv');repeats=rows(a.score_dir/'repetition_by_base.csv')
    pair_rows=rows(a.structure_dir/'main_pairs.csv');structure_attempts=rows(a.structure_dir/'per_attempt.csv')
    arrival={(r['method'],number(r['seconds'])):r for r in rows(a.arrival_dir/'budget_summary.csv')}
    gate=publication_gate(bindings,attempts,repeats,structure_attempts,pair_rows,scored,structure,arrival,a.online)
    data=stats(attempts,repeats,pair_rows,arrival,scored.get('main_static_pairing',{}),structure_attempts)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(report(gate,data,structure,arrival,a.fragment),encoding='utf-8')
    if gate['publishable']:
        a.fragment.parent.mkdir(parents=True,exist_ok=True)
        a.fragment.write_text(fragment(data,arrival),encoding='utf-8')
        a.details.parent.mkdir(parents=True,exist_ok=True)
        a.details.write_text(details_fragment(data,arrival,structure_attempts,structure),encoding='utf-8')
    state={'gate':gate,'providers':data,'fragment_written_this_run':gate['publishable'],
           'details_fragment_written_this_run':gate['publishable'],
           'source_scripts':['score_new_models.py','selection_arrival_analysis.py','analyze_generated_structure.py'],
           'new_scoring_or_structure_definitions':False}
    (a.report.parent/'D_FINDINGS.json').write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'report':str(a.report),'fragment_written':gate['publishable'],
                      'live_terminal_attempts':gate['live_terminal_attempts'],
                      'scored_terminal_attempts':gate['scored_terminal_attempts'],
                      'structure_terminal_attempts':gate['structure_terminal_attempts']},indent=2))


if __name__=='__main__':main()
