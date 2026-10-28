"""Derive compact mechanism records and prose from the verified stored panel."""
from collections import Counter
from run_origin_target_panel import ROOT,read,write,ce,changes,signature

panel=read(ROOT/'analysis/origin_target_panel.json');summary=read(ROOT/'analysis/origin_target_summary.json');joints=read(ROOT/'analysis/origin_target_joint.json')
def get(rid,origin,j,metric='missions'):
    return next(r for r in panel if (r['record_id'],r['origin'],r['target_prefix'],r['metric'])==(rid,origin,j,metric))
def compact(lo,hi):return str(lo) if lo==hi else f'[{lo},{hi}]'
def pair(rid,name,j):return '('+', '.join(compact(get(rid,name,j,m)['lower_bound'],get(rid,name,j,m)['upper_bound']) for m in ('missions','chains'))+')'
def diff(a,b):
    aa={d['mission_id']:d for d in a};return [dict(mission_id=d['mission_id'],uav_id=d['uav_id'],before=aa[d['mission_id']],after=d) for d in b if d!=aa[d['mission_id']]]

records={}
for rid in ('NET_S02_C','NET_M01_B'):
    folder=ROOT/'runs/origin_target'/rid;task=read(folder/'task.json');origins=read(folder/'origins.json');engine=ce.Engine(task)
    chosen={'G':origins['decisions']['G'],'Gprime':origins['decisions']['Gprime']}
    chosen.update({f'G_T{j}':get(rid,'G',j)['decisions'] for j in (2,3,4,6)})
    chosen.update({f'Gprime_T{j}':get(rid,'Gprime',j)['decisions'] for j in (2,3,4,6)})
    chosen.update({f'{name}_T2_chains':get(rid,name,2,'chains')['decisions'] for name in ('G','Gprime')})
    scores={name:engine.verify(ds) for name,ds in chosen.items()};assert all(s['admissible'] for s in scores.values())
    records[rid]=dict(task_intervention=task['intervention'],missions=[{k:v for k,v in m.items() if k not in ('paths','incoming')} for m in task['missions']],
         decisions=chosen,verification=scores,origin_changes=diff(chosen['G'],chosen['Gprime']),
         G_to_quality=diff(chosen['G'],chosen['G_T6']),Gprime_to_quality=diff(chosen['Gprime'],chosen['Gprime_T6']),
         same_quality_witness=signature(chosen['G_T6'])==signature(chosen['Gprime_T6']),
         T3_to_T4_witness_changes=diff(chosen['G_T3'],chosen['G_T4']))
write(ROOT/'analysis/origin_target_mechanisms.json',records)

ids=list(dict.fromkeys(r['record_id'] for r in panel));origin_records=[read(ROOT/'runs/origin_target'/rid/'origins.json') for rid in ids]
distinct=[o['record_id'] for o in origin_records if o['origin_distance']['missions']>0]
lines=['# 第三部分：双起点与目标层级计算结论','',
 '8条件按历史机制事前选择；128个标量位置全部有经验证的上界，108个闭合、20个保留区间。原G统计不被Gprime替换。本文件只汇总新增面板，综合入文判断由主报告处理。','',
 '**起点对照的实际分母：**预定规则在6/8条件生成与G完全相同的方案；仅S02-C与L01-C不同，分别相差2任务/2链和6任务/6链。因此这是8条件的规则检验、其中2条件有不同恢复起点，不是8个不同方案之间的比较。','',
 '| 条件 | 起点 | T2（任务,链） | T3 | T4 | T6 |','|---|---|---:|---:|---:|---:|']
for rid in ids:
    for name in ('G','Gprime'):lines.append('| '+rid+' | '+name+' | '+' | '.join(pair(rid,name,j) for j in (2,3,4,6))+' |')
lines += ['', '括号中两个值是边际最小值或其区间，不能自动拼成可执行预算。64个“条件×起点×目标”组合中，52个有同时达到边际最小值的见证；S02-C两个起点的T2均排除(2,1)，分别保留(2,2)与(3,1)的可执行前沿；其余10个组合的边际尚未闭合，只报告已有共同可执行上界。',
 '', '## S02-C：同一个质量方案，两个不同的剩余调整范围','',
 '两起点均服务7/9任务、暂停2个普通任务。Gprime仅改变共享V07在47分钟的出发名额：M002（U01）从P1、47分钟执行改为暂停；M006（U02）从暂停改为P1、47分钟执行。不是两项提前执行的路径改动，也没有增加当前服务数。G与Gprime的L3分别为2025.8、2025.4，加权延误分别为74、75分钟；所以不能把较小的剩余范围归因于Gprime所有指标更优。',
 '', '同一个经验证的完整质量见证相对G改变M002/M006/M007/M008/M009，达到5任务、3链；相对Gprime仅改变U03的M007/M008/M009，达到3任务、1链。下界分别由历史排除、直接查询及跨起点距离不等式支持，两个联合预算都有该共同见证。T3就达到这些最小范围，T4/T6不再增加。T2的(2,1)预算在两个起点均不可达，原任务数与链数贸易并未因Gprime而消失。',
 '', '剩余U03调整有具体事件含义：M007由P1@13改为P2@3，绕开3–13分钟的E_V05_V04关闭，保留两块充电；M008由46分钟、无充电改为26分钟、一块充电，在26.855分钟到达V07，早于28–46分钟的起降关闭；M009从暂停改为46分钟出发。Gprime的M008在46.855分钟才到达V07，占用46分钟唯一运动名额；质量见证将这一到达移到关闭前，因而46分钟可用于M009出发，47分钟仍用于M006。最终服务8/9任务，L3=1055、加权延误=9、L5=71。M009到达后的储备余量为0.0009533 kWh；增加服务使飞行能耗由Gprime的0.0803693升至0.0918122 kWh，不能称为节能改善。这里解释的是选定见证，不宣称该链集合唯一。',
 '', '**可粘贴英文：** In S02-C, the alternative greedy order changed which routine departure used the remaining 47-minute movement slot at V07. It held M002 on U01 and operated M006 on U02, whereas G made the opposite choice. Both origins served seven of nine missions. The same complete-quality witness required five mission changes across three UAV chains from G, but only the three missions of U03 from the alternative origin. These budgets were jointly attainable and attained the respective marginal minima. The difference therefore concerns recovery work already reflected in the origin, rather than a change in the incumbent-relative objective or reference. The service-level trade-off persisted: at either origin, the budget of two mission changes within one chain was infeasible.',
 '', '## M01-B：新增链从准点性要求开始','',
 'Gprime在本条件恰等于G。T2和T3的最小共同预算均为(4,1)，T4和T6均为(5,2)。新增计算把原服务/完整质量之间的范围变化定位在T3→T4，而不是泛称任何质量要求都需要更多链。T3见证服务20/20、L3=38.8、加权延误230、L5=127；T4见证保持服务和L3不变，延误降至180、L5降至112。',
 '', '对应事件为U01/M004在V11的充电由两块缩短到一块，释放时刻52.800→47.800分钟；U02/M008的充电开始53.004→48.004分钟，M008与后继M009都提前5分钟。50个加权延误分钟来自紧急M008减少5分钟迟到。T4与T6最小范围相同，不表示所有T4见证都达到T6；本报告使用的见证同时达到完整参考。',
 '', '**可粘贴英文：** In M01-B, the minimum jointly attainable budget remained four mission changes within one UAV chain through the service and plan-stability targets. Requiring the reference weighted tardiness increased it to five missions across two chains; the complete-quality target required no further increase. A verified witness shortened M004 charging at V11 by one five-minute block and advanced M008 and its successor by five minutes. It preserved all 20 services and the incumbent-relative change cost of 38.8 while reducing weighted tardiness from 230 to 180 minutes and L5 from 127 to 112 minutes.',
 '', '## 未闭合结果与收敛','',
 'L01-C的历史半径8排除在L3已经成立，已核验其前两层匹配参考。因此可向T3/T4传播任务下界9；Gprime再用起点间任务距离6得到下界3。该传播新增0次求解。G的T3任务[9,10]、T4/T6任务[9,11]，链均[2,5]；Gprime的T3/T4/T6任务[3,9]、链[1,5]。这些区间不足以宣称链最小值降低或确定完整的增幅。',
 '', 'Regions L01-long的T3/T4仍为任务[9,12]、链[2,3]；T6为(12,3)。不能由重叠区间认定T4→T6严格增加。所有条件均未触发事前规定的“已证T4→T6范围变化”规则，故未新增T5。5个条件在服务目标之上从T3开始已需要更多范围，M01-B从T4开始，两个ladder对照始终零距离；这些是机制选样内的结果，不作为总体比例。',
 '', '## 计算与验证口径','',
 f'128主标量位置中：40个起点达标零距离、36个相同起点历史界与见证复用、23个其他有效界/见证推导、29个有新增标量MILP记录。另新增1次联合MILP，总计30次实际MILP，求解器累计{summary["solver_seconds"]:.2f}秒；不把128位置当作128次优化，也不把累计求解器时间当端到端算法速度。',
 '', '独立验证检查128个标量位置、64个联合位置和30份新增查询记录；按完整决策去重后重放25个可行计划。逐条核对目标前缀、同域无额外限制的历史下界、跨起点三角不等式、最长链覆盖及已证半径排除；源实例、参考和事前历史文件哈希保持一致。Gprime从task独立重构并与存储结果完全一致。详见origin_target_validation.json。','']
(ROOT/'analysis/origin_target_findings.md').write_text('\n'.join(lines),encoding='utf-8')
write(ROOT/'analysis/origin_target_mechanism_summary.json',dict(distinct_origin_conditions=distinct,identical_origin_conditions=[r for r in ids if r not in distinct],
    joint_status_counts=dict(Counter(j['status'] for j in joints)),first_quality_increase_from_T2={'T3':['NET_S02_C','NET_L01_C','NEW_regions_L02_long','NEW_regions_L01_long','NET_S01_A'],'T4':['NET_M01_B'],'none':['NEW_ladder_M01_long','NEW_ladder_S01_short']},new_T5_positions=0))
print('Wrote mechanism records and findings')
