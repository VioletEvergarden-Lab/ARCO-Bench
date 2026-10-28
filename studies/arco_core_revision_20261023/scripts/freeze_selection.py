"""Write the mechanism-selected panel before new origins or results exist."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]; WS=ROOT.parent; OLD=WS/'arco_contribution_20261011'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
selection=[
 ('NET_M01_B','Original medium; charging mechanism, known T3 and restricted-U02 T4 records'),
 ('NET_S02_C','Original small; service mission/chain joint-budget tradeoff'),
 ('NET_L01_C','Original large; preserved open global bounds and candidate-specific 10/11 budgets'),
 ('NEW_regions_L02_long','Regions large; chain-set identity mechanism'),
 ('NEW_regions_L01_long','Regions large; original domain of the capacity case; capacity interventions themselves reused only'),
 ('NEW_ladder_M01_long','Ladder medium; archived G already reaches complete reference, retain zero control'),
 ('NEW_ladder_S01_short','Ladder small; short-closure scale/topology and archived-G-at-target control'),
 ('NET_S01_A','Original small A-only disruption; service already restored but complete quality not reached')]
sources=['e1_results.json','e1_origin_comparison.json','e1_joint_minima.json','e1_joint_tradeoff.json',
         'e1_support_identity.json','e3_interventions.json','e3_fixed_lex_bounds.json']
e1=read(OLD/'analysis/e1_results.json'); inventory=read(OLD/'analysis/task_manifest.json')
plan=dict(frozen_utc=datetime.now(timezone.utc).isoformat(),status='frozen_before_new_Gprime_or_queries',
 conditions=[dict(record_id=rid,reason=reason,metadata=next(r for r in inventory if r['record_id']==rid),
                  historical_G_bounds=[{k:q[k] for k in ('target_prefix','metric','lower_bound','upper_bound','status')}
                                       for q in e1 if q['record_id']==rid]) for rid,reason in selection],
 selection_basis='Purposeful mechanism coverage based exclusively on historical records; retain zero changes and unclosed intervals; no distributional representativeness claim',
 Gprime_rule='Keep remaining-urgent count and release-time priorities; then select chain head by reverse fixed UAV ID before incumbent-departure tie-break. Reuse original option ranking, feasibility checks and one-successor lookahead. No reference values or scope answers enter construction.',
 Gprime_head_key=['-remaining_urgent_count','release_min','-sorted_UAV_rank','incumbent_depart_min','sequence_index','mission_id'],
 fixed=['task','incumbent','finite action domain','resource interventions','lexicographic reference','QUALITY_TOL'],
 base_panel=dict(conditions=8,origins=['G','Gprime'],target_prefixes=[2,3,4,6],metrics=['missions','chains'],scalar_positions=128),
 solve_policy=dict(default_seconds=15,pilot_queries=[dict(record_id='NET_M01_B',origin='Gprime',prefix=2,metric='missions',seconds=5),
                       dict(record_id='NET_L01_C',origin='Gprime',prefix=3,metric='missions',seconds=5)],
                   no_automatic_repeat=True,open_bounds_allowed=True,
                   T5_trigger='Only if closed T4/T6 minima differ, or a T6 lower bound exceeds the corresponding T4 upper bound',
                   joint='All closed marginal pairs: use verified stored witness if available, matching historical exclusions if valid, otherwise one bounded feasibility query. For open pairs report verified attainable witness budgets without calling them marginal minima.'),
 historical_sources=[dict(path=str((OLD/'analysis'/name).relative_to(WS)),sha256=hashlib.sha256((OLD/'analysis'/name).read_bytes()).hexdigest()) for name in sources],
 interpretation='Historical incumbent-origin comparisons remain separate because incumbent can be infeasible after disruption. No capacity reruns, paid models, or ADDS experiments.')
out=ROOT/'analysis/selection_plan.json'
if out.exists():raise RuntimeError('Frozen selection already exists; do not overwrite')
out.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 起点与目标层级面板：事前选择','',f'冻结时间（UTC）：{plan["frozen_utc"]}。本文件生成时尚未构造本轮 Gprime、未运行本轮范围查询。','',
       '按历史机制选取8条件；这是有目的的解释样本，不用于估计网络总体规律。保留零变化和未闭合区间。','',
       '| 条件 | 事前选择理由 |','|---|---|']
lines += [f'| {rid} | {reason} |' for rid,reason in selection]
lines += ['', 'Gprime仅改变链头处理顺序：优先剩余紧急任务数、最早release，随后使用反向固定UAV序，再以incumbent出发时刻等打破平局。保持原动作排序、可行性判断和一步后继检查；构造过程不读取参考目标或范围查询答案。',
          '', '主面板为8条件×2起点×4目标×2指标=128个标量位置，包含历史复用与零距离。通常每次新求解15秒；M01-B/Gprime/T2任务数与L01-C/Gprime/T3任务数两个事先指定的短pilot仅5秒，结果保留，不自动重跑。T4至T6出现已证范围变化时才加T5。',
          '', '闭合的边际预算优先用已有共同见证或相同历史排除；缺口仅做一次有界联合查询。边际未闭合时报告可执行见证预算而不宣称共同最小。起点、实例、目标、容差和证据指针逐项保留。',
          '', '不开展新增容量矩阵、模型调用或ADDS试验。历史incumbent参照不替代两个可行恢复起点的比较。','']
(ROOT/'analysis/selection_plan.md').write_text('\n'.join(lines),encoding='utf-8')
print(out)
