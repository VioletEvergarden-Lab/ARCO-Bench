"""Read-only replay of archived E2 candidates, queries, and actual neighborhoods.

No solver is called. Positive plans are re-evaluated with the original event
verifier; exclusions are checked against archived completed solver statuses,
bound arithmetic, and reuse containment. Historical files are never written.
"""
from pathlib import Path
import collections
import csv
import hashlib
import json
import sys

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parents[1]
WS = OUT.parent
OLD = WS / 'arco_contribution_20261011'
sys.path.insert(0, str(OLD / 'scripts'))
from coordination_study import load_cases
from coordination_solver import canonical_plan, changes, target_met
from continuous_engine import Engine, TIERS, QUALITY_TOL

SOURCES = {}
COUNTS = collections.Counter()
REPLAY = {}


def path(s):
    p = Path(s)
    if p.is_absolute():
        return p
    return (WS if str(p).startswith('arco_') else OLD) / p


def track(p):
    p = path(p)
    SOURCES[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return p


def read(p):
    return json.loads(track(p).read_text(encoding='utf-8-sig'))


def write(name, data):
    p = OUT / 'analysis' / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def csvwrite(name, rows):
    with (OUT / 'analysis' / name).open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)


def canon(c, p):
    return canonical_plan(p, c['task'])


def replay(c, p):
    p = canon(c, p)
    key = c['record_id'], json.dumps(p, sort_keys=True)
    if key not in REPLAY:
        REPLAY[key] = Engine(c['task']).verify(p)
        COUNTS['unique_plans_replayed'] += 1
    return REPLAY[key]


def compact_score(z):
    return {k: z.get(k) for k in ('admissible', 'objective', 'errors')}


def objective_same(a, b):
    if a is None or b is None:
        return a is b
    return all(abs(a[t] - b[t]) <= 1e-8 for t in TIERS)


def decision_diff(c, before, after):
    a = {d['mission_id']: d for d in canon(c, before)}
    task = {m['mission_id']: m for m in c['task']['missions']}
    out = []
    for d in canon(c, after):
        m = d['mission_id']
        delta = {k: {'before': a[m][k], 'after': d[k]} for k in ('held', 'path_id', 'depart_min', 'charge_blocks') if a[m][k] != d[k]}
        if delta:
            out.append({'mission_id': m, 'uav_id': d['uav_id'], 'mission': task[m], 'changes': delta})
    return out


def verify_query(c, qpath):
    q = read(qpath)
    if 'record_id' in q:
        assert q['record_id'] == c['record_id']
    else:
        assert c['record_id'] in path(qpath).parts
    assert q['feasible'] in (True, False)
    qq = q['query']
    out = dict(source=str(path(qpath)), query=qq, feasible=q['feasible'], evidence=q['evidence'],
               solver_status=q.get('solver_status'), target_objective=c['reference']['objective'])
    if q['feasible']:
        z = replay(c, q['decisions'])
        assert z['admissible'] and target_met(z['objective'], c['reference']['objective'], qq['prefix'])
        ms, us = changes(canon(c, q['decisions']), canon(c, c['origins']['G']))
        assert set(us) <= set(qq['allowed'])
        assert qq['mission_budget'] is None or len(ms) <= qq['mission_budget']
        if q.get('objective') is not None:
            assert objective_same(z['objective'], q['objective'])
        out.update(witness_source=q.get('witness_source', q.get('source')), changed_missions=ms,
                   changed_uavs=us, mission_changes=len(ms), score=compact_score(z),
                   verification='original_event_verifier_replayed')
        COUNTS['positive_query_records_checked'] += 1
    elif q['evidence'] == 'proved_exclusion_reuse':
        ancestor = read(q['source'])
        aq = ancestor['query']
        assert ancestor['feasible'] is False
        assert aq['prefix'] <= qq['prefix'] and set(qq['allowed']) <= set(aq['allowed'])
        k1 = float('inf') if aq['mission_budget'] is None else aq['mission_budget']
        k2 = float('inf') if qq['mission_budget'] is None else qq['mission_budget']
        assert k2 <= k1
        # Recursively validate to a completed direct infeasibility record.
        parent = verify_query(c, q['source'])
        out.update(reused_source=str(path(q['source'])), verification='archived_exclusion_and_subset_relation_checked', parent=parent)
        COUNTS['negative_reuse_records_checked'] += 1
    else:
        assert q['solver_status'] == 'Infeasible'
        assert q.get('target_objective') == c['reference']['objective']
        assert q.get('origin_name') == 'G'
        out['verification'] = 'archived_completed_solver_infeasibility_checked_not_resolved_again'
        COUNTS['negative_direct_records_checked'] += 1
    return out


def plan_bundle(c, p, source):
    z = replay(c, p)
    ms, us = changes(canon(c, p), canon(c, c['origins']['G']))
    return dict(source=str(path(source)), decisions=canon(c, p), score=compact_score(z),
                target6=bool(z['admissible'] and target_met(z['objective'], c['reference']['objective'], 6)),
                changed_missions_vs_G=ms, changed_uavs_vs_G=us,
                decision_changes_vs_G=decision_diff(c, c['origins']['G'], p),
                events=z.get('events', []), resource_intervals=z.get('resource_intervals', []),
                violating_windows=[x for x in z.get('window_loads', []) if x['count'] > x['capacity']])


def notes(rows, localrows, representatives, summary):
    def link(label, p):
        return f'[{label}](<{Path(p).as_posix()}>)'
    names = {'support_insufficient': '链集合不足', 'support_sufficient_budget_insufficient': '任务预算不足',
             'support_and_budget_sufficient': '范围与预算足够'}
    def objective(obj):
        return '无合法目标向量' if obj is None else '(' + ', '.join(f'{obj[t]:.6g}' for t in TIERS) + ')'
    lines = [
        '# 候选方案诊断复核（2026-10-23）', '',
        '已复核全部 13 个完整生成决策未达参考质量的记录，分类仍为 5 / 2 / 6；其中 8 个可行，5 个完整但不可行。'
        '总体分母是 60 个条件各两个模型的首次正式生成，共 120 个记录：97 个达标、13 个完整未达标、10 个没有完整可评估决策。'
        '不与 Core-72、后续重试或新模型调用合并。', '',
        '诊断以 G 为范围原点：允许改变的 UAV 链集合取候选相对 G 的变化链，任务预算取变化任务数。'
        '允许在这些链中重新选择任务、路径、时刻和充电量，并不固定候选已改变的具体任务或决策值。'
        'L3 仍按原验证器相对 incumbent 计算，其数值不是相对 G 的变化任务数。T2 匹配前两层目标，T6 匹配全部六层；使用历史容差。', '',
        '| 记录 / 模型 | 可行 | 链集合（相对 G） | 任务数 | 分类 | G 已达标 | 原目标向量 L1–L6 | 原记录 / T6 查询 |',
        '|---|---|---|---:|---|---|---|---|'
    ]
    for r in rows:
        lines.append(f"| {r['record_id']} / {r['source']} | {'是' if r['admissible'] else '否'} | {','.join(r['support_vs_G']) or '空集'} | {r['mission_changes_vs_G']} | {names[r['diagnosis']]} | {'是' if r['G_already_target6'] else '否'} | {objective(r['original_objective'])} | " +
                     ' / '.join([link('原始输出', r['raw_candidate_source']), link('链集合', r['T6_support_query_source']), link('加预算', r['T6_budget_query_source'])]) + ' |')
    lines += ['', '所有 13 个记录的 T2 两类查询均可行。6 个“范围与预算足够”中，M02-A / deepseek、S03-C / deepseek 和 ladder M02-short / deepseek 的 G 已经达标；'
              '这三项是维持或回到 G 即可，不作为非平凡修复案例。其余三项为 L01-C / luna、M01-B / luna、S01-B / deepseek。', '',
              '5 个不可行完整输出分别触发：L04-A / deepseek 的充电预约容量、M02-A / deepseek 的航路预约容量、ladder M02-short / deepseek 的充电前最低电量、'
              'regions L01-long / deepseek 和 regions L02-long / deepseek 的航路预约容量。不可行方案的原目标向量保持空值，不把事件的局部代价当作合法分数。', '',
              '## 代表一：Regions L02-long——链身份比链数量更关键', '',
              '实例有 32 个任务、8 架 UAV，E_V02_V01 在 [8,43) 分钟关闭。DeepSeek 改了 4 条链 U03/U04/U06/U07、11 个任务，但输出存在航路预约容量冲突。'
              '固定这个允许链集合、放开任务数仍被历史目标查询排除，因此仅增加任务预算不能到达 T6。', '',
              '一个通过原验证器的目标见证改了 10 个任务、4 条链 U03/U04/U05/U07。与候选相比，它把 U03 的 M009/M010 再提前 1 分钟，'
              '把 U05 的 M016 从 10 分钟提前到 9 分钟，并把 U06 的 M021/M022 恢复为 G 的 44/51 分钟。'
              '这说明改动链总数无须增加，允许参与的链身份需要改变；这里的“替换”是替换调整范围中的链，不是把任务重新分配给另一架 UAV。', '',
              '固定目标见证的其他决策、仅把 M016 恢复为 10 分钟，会使 E_V01_V13 在分钟窗口 [11,12) 出现 M012/M016/M024 三份预约，超过容量 2。'
              '这项检查只触发 CORRIDOR_WINDOW_CAPACITY，不能写成三机在连续时间同时占用航路。目标见证中 M016 提前后，该预约冲突消失。'
              '完整范围排除来自目标查询；此单项检查只是说明见证内的具体资源关系，不证明 U05 对所有可行方案都全局必要。', '',
              '## 代表二：L01-C——同一链集合内，10 与 11 个任务预算不同', '',
              '实例有 32 个任务、8 架 UAV，包含 U03 初始电量下降、航路关闭与 V13 起降资源受限。DeepSeek 和 Luna 都只涉及 U01/U03/U05/U07/U08。'
              'DeepSeek 改 10 个任务，原方案可行但目标为 (0,4,4045,261,253,0.382724)。同一链集合内，10 个任务预算被排除，11 个任务存在目标见证，'
              '目标为 (0,4,4045,221,245,0.382724)。这关闭的是该集合内的 10/11 阈值；原全域任务数界仍为 [9,11]，不能写成全局至少 11。', '',
              '相对 DeepSeek，目标见证只把 M020（U05）从 53 提前到 49 分钟，把原来未偏离 G 的 M028（U07）从 48 提前到 44 分钟。'
              '前者仍计入原 10 个变化任务，后者新增一个变化任务，因此相对 G 是 11 个。两次提前让 V13 充电时段分别由 M028 的 [54.594,59.594)'
              '及 M020 的 [60.045,70.045)，变成 [50.594,55.594) 及 [56.045,66.045)。M020 的迟到从 10 降至 6 分钟；'
              '全局 L4 降 40、L5 降 8，L1–L3 与能耗保持不变。若只提前 M020，V13 会产生连续充电重叠和分钟预约冲突。', '',
              'Luna 已改变同样的 11 个任务，但选了 M020=45、M028=57，目标为 (0,4,4045.2,221,254,0.382724)。'
              '因此它属于范围与预算足够但决策值未达标，不能把“触及相同任务”直接当成修复成功。', '',
              '## 代表三：M01-B——范围足够，充电与时刻选择仍可改善', '',
              '实例有 20 个任务、5 架 UAV，U02 初始电量下降，E_V09_V11 在 [24,34) 分钟关闭。Luna 已调整 U01/U02 共 6 个任务，全部服务可行，'
              '但目标为 (0,0,39.8,210,132,0.226906)。同一允许链集合和不超过 6 个任务的范围内，有只改 5 个任务的目标见证，'
              '目标为 (0,0,38.8,180,112,0.226906)。', '',
              '相对 Luna，见证把 M004 出发从 45 恢复为 36 分钟、充电从 2 块减为 1 块，把 M005 从 62 恢复为 53 分钟，'
              '把 M008 从 39 调到 42 分钟，其余决策不变。这里单个任务未必越早越好；充电容量、先后次序和 incumbent-relative L3 共同决定目标。', '',
              '| M01-B 对照 | 相对 G 任务 / 链 | 服务数 | L3 | L4 | L5 | M004 在 V11 充电 | M008 在 V11 充电 |',
              '|---|---:|---:|---:|---:|---:|---|---|',
              '| R4 服务恢复 | 4 / 1 | 20 | 38.8 | 230 | 127 | [42.800,52.800) | [53.004,58.004) |',
              '| Luna 原候选 | 6 / 2 | 20 | 39.8 | 210 | 132 | [51.800,61.800) | [45.004,50.004) |',
              '| T6 目标见证 | 5 / 2 | 20 | 38.8 | 180 | 112 | [42.800,47.800) | [48.004,53.004) |', '',
              'R4 到目标见证体现从服务恢复到质量恢复：M004 少充 5 分钟，V11 更早释放，M008/M009 均提前 5 分钟。'
              'M005 到达后的储备余量仍为 1.375 Wh，原验证器通过。固定见证其他决策、仅恢复 M004 两块充电，会与 M008 在 V11 连续重叠，'
              '同时违反预约容量。230→180 与 127→112 属于 R4 对照；Luna 自身的对应变化是 210→180 与 132→112，且 L3 从 39.8 降至 38.8。', '',
              '三类代表的完整决策、任务定义、事件和查询来源：' + link('candidates_representatives.json', OUT/'analysis/candidates_representatives.json') + '。'
              '三项固定其余决策的事件检查：' + link('candidates_event_controls.json', OUT/'analysis/candidates_event_controls.json') + '。', '',
              '## 40 个局部优化未达标记录', '',
              '保留每次运行最后一个实际邻域的 center 与 radius，结果为 36 个范围已排除、4 个范围内存在目标见证。'
              '33 个排除来自该实际中心的已证明词典序阶段界，2 个来自历史定向不可行查询，1 个中心确为 G 且目标距离下界超过半径。'
              '4 个内部见证为 L02-B 与 L04-B 各自的 R4、Iter-R4，半径均为 4，见证距实际中心均为 4。', '',
              '其中 4 个 Iter-R4 最终中心不等于 G：L01-B、L01-C、L02-C、L04-C，中心距 G 分别为 4、7、4、4；半径都是 4。'
              '结论只针对最后实际搜索范围，不外推到所有迭代邻域。完整中心决策保存在 ' + link('candidates_local_neighborhoods.json', OUT/'analysis/candidates_local_neighborhoods.json') + '。', '',
              '| 条件 | 方法 | 最后半径 | 中心距 G | 分类 | 证据 |', '|---|---|---:|---:|---|---|']
    for r in localrows:
        lines.append(f"| {r['record_id']} | {r['method']} | {r['radius']} | {r['center_changes_from_G']} | {r['classification']} | {link(r['evidence_kind'], r['evidence_source'])} |")
    lines += ['', '## 核验范围与定义注意事项', '',
              f"本轮用原始 continuous_engine.Engine.verify 重放 {summary['checks']['unique_plans_replayed']} 个唯一方案；全部 13 个原候选与原始 TERMINAL 决策一致，"
              '历史可行性与合法目标向量一致。正向目标见证还核对了目标容差、允许链集合和任务预算；两种查询模式结果一致。'
              '负向证据核对历史 Infeasible 状态、目标/范围与复用包含关系，未重跑 MILP，不声称重新生成了形式化不可行证明。', '',
              '没有发现本轮重放与既有分类的数值冲突。需要保持的定义区别是：完整输出不等于可行输出；G 原点的变化计数不等于 incumbent 原点的 L3；'
              '单一见证的链身份不等于全局必要链；分钟预约冲突不一定等于连续同时占用冲突；R4 事件对照不等于 Luna 的原始分数。'
              '原生成分数中的匿名 public record_id 与归档条件名不同，决策已通过对应任务逐一核对，没有据此改写历史 ID。', '',
              '运行方式：`python arco_core_revision_20261023/scripts/validate_candidates.py`。无付费调用、无新增求解器调用。'
              '历史来源读取前后 SHA256 一致；来源清单见 ' + link('candidates_source_manifest.json', OUT/'analysis/candidates_source_manifest.json') + '，'
              '复核汇总见 ' + link('candidates_validation.json', OUT/'analysis/candidates_validation.json') + '。']
    (OUT/'analysis/candidates_findings.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    for p in ('scripts/coordination_study.py', 'scripts/coordination_solver.py', 'scripts/candidate_scope.py',
              'scripts/local_neighborhood_diagnostics.py', 'arco_closing_study/continuous_engine.py',
              'arco_closing_study/study_common.py', 'arco_closing_study/solver_backend.py'):
        track(p)
    cases = {c['record_id']: c for c in load_cases()}
    diagnoses = read('analysis/e2_candidate_diagnoses.json')
    queries = read('analysis/e2_query_results.json')
    querymap = {(r['record_id'], r['mode'], r['key']): r for r in queries}
    generated = [r for r in diagnoses if r['source'] in ('deepseek', 'luna')]
    assert len(generated) == 120
    population = collections.Counter(r['diagnosis'] if r['included'] else 'excluded' for r in generated)
    assert population == dict(successful_control=97, excluded=10, support_insufficient=5,
                              support_sufficient_budget_insufficient=2, support_and_budget_sufficient=6)
    misses = [r for r in generated if r['included'] and not r['reference_quality']]
    rows = []
    by_candidate = {}
    for r in misses:
        c = cases[r['record_id']]
        v = c['candidates'][r['source']]
        for p in (c['task_path'], c['reference_path'], v['source_path'], c['candidates']['G']['source_path']):
            track(p)
        z = replay(c, v['decisions'])
        assert z['admissible'] == v['admissible'] == r['admissible']
        assert objective_same(z['objective'], v['objective'])
        ms, us = changes(canon(c, v['decisions']), canon(c, c['origins']['G']))
        assert us == r['support'] and len(ms) == r['mission_changes']
        rawpath = (WS / 'arco_closing_study/online' / r['source'] / 'attempts' / r['record_id'] / 'TERMINAL.json') if c['group'] == 'original' else path(v['source_path'])
        raw = read(rawpath)
        rawplan = json.loads(raw['raw_text'])['decisions'] if c['group'] == 'original' else raw['decisions']
        assert canon(c, rawplan) == canon(c, v['decisions'])
        g = replay(c, c['origins']['G'])
        ref = replay(c, c['reference']['decisions'])
        assert ref['admissible'] and target_met(ref['objective'], c['reference']['objective'], 6)
        check = {}
        for label, key in r['queries'].items():
            pairs = []
            for mode in ('direct_static', 'cross_query_reuse'):
                qr = querymap[c['record_id'], mode, key]
                q = verify_query(c, qr['source_file'])
                assert q['feasible'] == r[label]
                pairs.append(q)
            assert pairs[0]['query'] == pairs[1]['query'] and pairs[0]['feasible'] == pairs[1]['feasible']
            check[label] = dict(direct=pairs[0], reuse=pairs[1])
        gquality = bool(g['admissible'] and target_met(g['objective'], c['reference']['objective'], 6))
        row = dict(record_id=c['record_id'], group=c['group'], source=r['source'],
                   original_status=r['status'], complete_decisions=True, admissible=z['admissible'],
                   original_objective=z['objective'], original_errors=z['errors'], support_vs_G=us,
                   mission_changes_vs_G=len(ms), changed_missions_vs_G=ms,
                   T2_support=r['T2_support'], T2_budget=r['T2_budget'], T6_support=r['T6_support'],
                   T6_budget=r['T6_budget'], diagnosis=r['diagnosis'], G_already_target6=gquality,
                   same_scope_subtype=('G_already_suffices' if gquality else 'nontrivial_quality_repair') if r['diagnosis'] == 'support_and_budget_sufficient' else None,
                   target_objective=c['reference']['objective'], task_source=str(path(c['task_path'])),
                   raw_candidate_source=str(rawpath), score_source=str(path(v['source_path'])),
                   G_source=str(path(c['candidates']['G']['source_path'])),
                   reference_source=str(path(c['reference_path'])),
                   T6_support_query_source=check['T6_support']['direct']['source'],
                   T6_budget_query_source=check['T6_budget']['direct']['source'])
        rows.append(row)
        by_candidate[c['record_id'], r['source']] = dict(row=row, queries=check, candidate_decisions=canon(c, v['decisions']))
    assert len(rows) == 13
    assert sum(r['admissible'] for r in rows) == 8
    assert sum(r['G_already_target6'] for r in rows) == 3
    write('candidates_classification.json', dict(definition='First formal generated attempts across the archived 60 conditions; 13 complete quality misses, including infeasible full decisions.',
          origin='G; not the incumbent used by objective L3', quality_tolerances=list(QUALITY_TOL),
          population_counts=dict(population), rows=rows, query_checks=list(by_candidate.values())))
    csvwrite('candidates_classification.csv', rows)

    # Validate every actual final neighborhood, without replacing its center by G.
    local = read('analysis/e2_actual_neighborhoods.json')
    e1 = read('analysis/e1_results.json')
    localrows = []
    localdetails = []
    for d in local['details']:
        c = cases[d['record_id']]
        track(c['task_path']); track(c['reference_path'])
        run = read(d['source_run'])
        nh = run['neighborhoods'][-1]
        center = canon(c, nh['center_decisions'])
        assert center == canon(c, d['center_decisions'])
        assert nh['radius'] == d['radius'] and nh['index'] == d['final_neighborhood_index']
        assert (center == canon(c, c['origins']['G'])) == d['center_equals_G']
        assert len(changes(center, canon(c, c['origins']['G']))[0]) == d['center_changes_from_G']
        z = replay(c, run['decisions'])
        assert z['admissible'] == run['admissible'] and objective_same(z['objective'], run['objective'])
        assert not (z['admissible'] and target_met(z['objective'], c['reference']['objective'], 6))
        evidence = d['evidence_kind']
        if d['classification'] == 'witness_inside':
            w = d['witness']; wz = replay(c, w['decisions'])
            assert wz['admissible'] and target_met(wz['objective'], c['reference']['objective'], 6)
            dist = len(changes(canon(c, w['decisions']), center)[0])
            assert dist == d['witness_distance'] and dist <= d['radius']
            raww = read(w['source'])
            assert canon(c, raww['decisions']) == canon(c, w['decisions'])
            validation = 'target_witness_replayed_at_actual_center'
        elif evidence == 'saved_actual_center_prefix_exclusion':
            proof = d['proof']; phaseproof = proof['prefix_phases']
            assert [p['tier'] for p in phaseproof] == list(TIERS[:len(phaseproof)])
            for i, p in enumerate(phaseproof):
                assert p in run['phases'] and p['proved'] and p['neighborhood'] == nh['index']
                t = TIERS[i]; target = c['reference']['objective'][t]
                if i < len(phaseproof) - 1:
                    assert abs(p['lower_bound'] - target) <= QUALITY_TOL[i] + 1e-10
                    assert abs(p['upper_bound'] - target) <= QUALITY_TOL[i] + 1e-10
                else:
                    assert p['lower_bound'] - target > QUALITY_TOL[i] + 1e-10
                    assert p['lower_bound'] == proof['lower_bound'] and target == proof['target_value']
            validation = 'saved_actual_center_phase_bounds_checked_not_resolved_again'
        elif evidence == 'same_G_distance_bound':
            assert d['center_equals_G']
            proof = d['proof']
            bounds = [q for q in e1 if q['record_id'] == c['record_id'] and q['metric'] == 'missions'
                      and q['target_prefix'] == proof['target_prefix'] and q['lower_bound'] == proof['lower_bound']]
            assert bounds and proof['lower_bound'] > d['radius']
            validation = 'archived_G_lower_bound_exceeds_actual_radius'
        elif evidence == 'new_actual_neighborhood_infeasibility':
            q = read(d['new_query_source'])
            assert q['feasible'] is False and q['solver_status'] == 'Infeasible'
            assert q['origin_name'] == 'actual_final_search_center' and q['task_budget'] == d['radius']
            assert q['source_neighborhood_index'] == nh['index'] and q['source_run'] == d['source_run']
            assert q['target_objective'] == c['reference']['objective'] and q['target_prefix'] == 6
            sig = hashlib.sha256(json.dumps([nh['center_decisions'], d['radius']], sort_keys=True).encode()).hexdigest()[:12]
            assert sig in d['new_query_source']
            validation = 'archived_actual_center_infeasibility_record_and_center_digest_checked'
        else:
            raise AssertionError(evidence)
        rr = {k: d[k] for k in ('record_id', 'group', 'method', 'radius', 'final_neighborhood_index',
                               'number_of_neighborhoods', 'center_equals_G', 'center_changes_from_G',
                               'classification', 'evidence_kind', 'witness_distance', 'old_stop_reason', 'conclusion_scope')}
        rr.update(source_run=str(path(d['source_run'])), evidence_source=str(path(d['evidence_source'])),
                  center_sha256=hashlib.sha256(json.dumps(center, sort_keys=True).encode()).hexdigest(),
                  validation=validation)
        localrows.append(rr)
        localdetails.append(dict(**rr, center_decisions=center, proof=d['proof'], witness=d['witness']))
    lc = collections.Counter(r['classification'] for r in localrows)
    assert len(localrows) == 40 and lc == dict(proved_scope_excluded=36, witness_inside=4)
    write('candidates_local_neighborhoods.json', dict(counts=dict(lc), rows=localrows, details=localdetails))
    csvwrite('candidates_local_neighborhoods.csv', localrows)

    # One operational representative for each class, with complete replayable plans.
    representatives = []
    for rid, model, category in [('NEW_regions_L02_long', 'deepseek', 'support_insufficient'),
                                 ('NET_L01_C', 'deepseek', 'support_sufficient_budget_insufficient'),
                                 ('NET_M01_B', 'luna', 'support_and_budget_sufficient')]:
        c = cases[rid]; v = c['candidates'][model]
        info = by_candidate[rid, model]
        label = 'T6_support' if category == 'support_sufficient_budget_insufficient' else 'T6_budget'
        qfile = info['queries'][label]['direct']['source']
        q = read(qfile)
        if q['feasible']:
            witness, witness_source = q['decisions'], qfile
        else:
            witness, witness_source = c['reference']['decisions'], c['reference_path']
        w = plan_bundle(c, witness, witness_source)
        assert w['target6']
        rep = dict(record_id=rid, source=model, diagnosis=category, task_source=str(path(c['task_path'])),
                   intervention=c['task']['intervention'], mission_count=c['mission_count'], uav_count=c['uav_count'],
                   origin_G=plan_bundle(c, c['origins']['G'], c['candidates']['G']['source_path']),
                   original_candidate=plan_bundle(c, v['decisions'], v['source_path']), target_witness=w,
                   queries=info['queries'], changes_from_candidate_to_witness=decision_diff(c, v['decisions'], witness))
        if rid == 'NEW_regions_L02_long':
            b = [r for r in e1 if r['record_id'] == rid and r['target_prefix'] == 6]
            rep['global_target_distance_bounds'] = [{k: x[k] for k in ('metric', 'lower_bound', 'upper_bound', 'status')} for x in b]
            assert set(w['changed_uavs_vs_G']) == {'U03', 'U04', 'U05', 'U07'}
            rep['interpretation'] = 'Candidate uses 4 chains and 11 mission changes; its chain set is excluded even with unlimited mission changes. A target witness uses 4 different-identity chains and 10 missions: U05 replaces U06. This is a support-identity failure, not a need for more than 4 participating chains. The witness alone does not prove U05 globally necessary.'
        elif rid == 'NET_L01_C':
            rep['paired_luna_candidate'] = plan_bundle(c, c['candidates']['luna']['decisions'], c['candidates']['luna']['source_path'])
            rep['interpretation'] = 'For the same allowed set U01/U03/U05/U07/U08, budget 10 is excluded while a target witness uses 11. Luna already changed 11 missions but missed quality; allowed set and budget suffice without preserving its exact changed missions or decision values. This proves the threshold only inside this chain set, not a global 11-mission lower bound.'
        else:
            r4 = c['candidates']['R4']
            rep['service_recovery_R4'] = plan_bundle(c, r4['decisions'], r4['source_path'])
            rep['reference_plan'] = plan_bundle(c, c['reference']['decisions'], c['reference_path'])
            rep['interpretation'] = 'Luna has sufficient allowed chains U01/U02 and budget 6; the target witness uses 5 missions. Separately, the R4-to-reference event comparison holds full service and L3 fixed while M004 charging changes and U02 timing/charging improve. Do not identify the R4 score as the Luna score.'
        representatives.append(rep)
    write('candidates_representatives.json', representatives)

    # Three local event checks explain the displayed witness, not global necessity.
    controls = []
    for rid, source, mid, field, value in [
            ('NEW_regions_L02_long', 'reference', 'M016', 'depart_min', 10),
            ('NET_L01_C', 'deepseek', 'M020', 'depart_min', 49),
            ('NET_M01_B', 'reference', 'M004', 'charge_blocks', 2)]:
        c = cases[rid]; v = c['candidates'][source]
        p = canon(c, v['decisions'])
        d = next(d for d in p if d['mission_id'] == mid)
        old_value = d[field]; d[field] = value
        z = replay(c, p)
        assert not z['admissible']
        bad = [w for w in z['window_loads'] if w['count'] > w['capacity']]
        contributors = []
        for w in bad:
            start = w['bucket'] * w['width_min']; end = start + w['width_min']
            contributors.append(dict(window=w, intervals=[x for x in z['resource_intervals']
                if x['kind'] == w['kind'] and x['resource'] == w['resource']
                and min(x['end_min'], end) > max(x['start_min'], start) + 1e-9]))
        controls.append(dict(record_id=rid, base_source=str(path(v['source_path'])),
                             edit={mid: {field: {'before': old_value, 'after': value}}},
                             score=compact_score(z), violating_windows=bad, contributors=contributors,
                             claim_scope='Fixed-other-decisions event illustration; not a new unrestricted necessity proof.'))
    write('candidates_event_controls.json', controls)

    summary = dict(population_counts=dict(population), complete_misses=13, admissible_misses=8, inadmissible_complete_misses=5,
                   categories=dict(collections.Counter(r['diagnosis'] for r in rows)),
                   scope_budget_sufficient_G_already_target6=3, scope_budget_sufficient_nontrivial=3,
                   local_counts=dict(lc), local_center_not_G=sum(not r['center_equals_G'] for r in localrows),
                   local_evidence_kinds=dict(collections.Counter(r['evidence_kind'] for r in localrows)),
                   checks=dict(COUNTS), negative_evidence_limit='Archived completed infeasibility/bound records were checked; no MIP was rerun and no independently checkable MILP certificate is claimed.',
                   new_fixed_other_decisions_event_checks=3,
                   new_paid_calls=0, new_solver_calls=0, historical_files_unchanged=True)
    for p, digest in SOURCES.items():
        assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest, p
    write('candidates_validation.json', summary)
    write('candidates_source_manifest.json', [{'path': p, 'sha256': h} for p, h in sorted(SOURCES.items())])
    notes(rows, localrows, representatives, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
