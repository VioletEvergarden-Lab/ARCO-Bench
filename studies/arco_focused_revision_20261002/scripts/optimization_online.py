"""Timed public-option MILP methods with online verified HiGHS incumbents.

Imports the unchanged closing-study event model and comparator. No reference is
read here: reference thresholds are applied by the separate summary script.
"""
from pathlib import Path
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / 'arco_closing_study'
sys.dont_write_bytecode = True
sys.path.insert(0, str(HIST))
from continuous_engine import Engine, compare, quality, QUALITY_TOL, TIERS
from solver_backend import highspy, VERSION
import numpy as np
from scipy.sparse import csr_matrix, vstack

PROTOCOL = 'online_comparison_v1_20261003'
METHODS = ('G', 'R4', 'Full-MILP', 'Iter-R4', 'R_frac')


def plan_x(built, decisions):
    x = np.zeros(len(built['meta']))
    for d in decisions:
        mid = d['mission_id']
        i = built['holds'][mid] if d['held'] else next(
            i for i in built['indices'][mid]
            if all(built['meta'][i][k] == d[k] for k in
                   ('path_id', 'depart_min', 'charge_blocks')))
        x[i] = 1
    return x


def metrics(task, score):
    events = [e for e in score['events'] if not e['held']]
    urgent = sum(m['priority'] == 'urgent' for m in task['missions'])
    return {
        'urgent_served': urgent - int(score['objective'][TIERS[0]]),
        'total_served': len(task['missions']) - int(score['objective'][TIERS[1]]),
        'urgent_on_time': sum(e['priority'] == 'urgent' and e['tardiness_min'] <= 1e-7 for e in events),
        'total_on_time': sum(e['tardiness_min'] <= 1e-7 for e in events),
        'urgent_demand': urgent,
        'route_changes': sum(e['route_changed'] for e in events),
        'min_reserve_margin_kwh': min((e['reserve_margin_kwh'] for e in events), default=None),
    }


class Trajectory:
    def __init__(self, engine, start, budget):
        self.engine, self.start, self.budget = engine, start, budget
        self.best_plan = self.best_score = None
        self.events, self.improvements, self.seen = [], [], set()
        self.validation_seconds = 0.
        self.callback_count = 0
        self.callback_seconds = 0.
        self.duplicate_count = 0

    def now(self):
        return time.perf_counter() - self.start

    def accept(self, plan, generated, source, neighborhood, tier):
        key = tuple((d['mission_id'], d['held'], d['path_id'], d['depart_min'], d['charge_blocks'])
                    for d in sorted(plan, key=lambda d: d['mission_id']))
        if key in self.seen:
            self.duplicate_count += 1
            return None
        self.seen.add(key)
        vstart = time.perf_counter()
        score = self.engine.verify(plan)
        elapsed = time.perf_counter() - vstart
        self.validation_seconds += elapsed
        candidate_metrics = metrics(self.engine.task, score) if score['admissible'] else {}
        better = score['admissible'] and (self.best_score is None or
                 compare(score['objective'], self.best_score['objective']) < 0)
        available = self.now()
        event = {'generated_seconds': generated, 'available_seconds': available,
                 'validation_seconds': elapsed, 'source': source,
                 'neighborhood': neighborhood, 'tier': tier,
                 'admissible': score['admissible'], 'within_budget': available <= self.budget,
                 'objective': score['objective'], 'errors': score['errors']}
        if score['admissible']:
            event.update(candidate_metrics)
        else:
            # The independently checked finite-domain candidate is retained as
            # a rejected event; it can never become a deliverable incumbent.
            self.events.append(event)
            return score
        improved = available <= self.budget and better
        event['improved'] = improved
        self.events.append(event)
        if improved:
            self.best_plan, self.best_score = plan, score
            self.improvements.append({**event, 'decisions': plan})
        return score


def make_highs(c, A, lower, upper, incumbent):
    h = highspy.Highs()
    for key, value in [('output_flag', False), ('threads', 1),
                       ('mip_rel_gap', 0.), ('mip_abs_gap', 0.),
                       ('mip_feasibility_tolerance', 1e-7), ('presolve', 'on'),
                       ('random_seed', 0)]:
        if h.setOptionValue(key, value) != highspy.HighsStatus.kOk:
            raise RuntimeError(('solver option', key))
    lp = highspy.HighsLp()
    n = len(c)
    lp.num_col_, lp.num_row_ = n, A.shape[0]
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = c, np.zeros(n), np.ones(n)
    lp.row_lower_, lp.row_upper_ = lower, upper
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_ = A.indptr.astype(np.int32)
    lp.a_matrix_.index_, lp.a_matrix_.value_ = A.indices.astype(np.int32), A.data
    lp.integrality_ = [highspy.HighsVarType.kInteger] * n
    if h.passModel(lp) == highspy.HighsStatus.kError:
        raise RuntimeError('pass sparse MILP')
    if incumbent is not None:
        sol = highspy.HighsSolution()
        sol.col_value, sol.value_valid = np.rint(incumbent), True
        h.setSolution(sol)
    return h


def run_online(task_path, method, budget=600., slice_seconds=60.):
    """One independent online method; runtime imports precede the timed call."""
    if method not in METHODS:
        raise ValueError(method)
    start = time.perf_counter()
    raw = Path(task_path).read_bytes()
    task = json.loads(raw)
    engine = Engine(task)
    trace = Trajectory(engine, start, budget)
    greedy = engine.greedy()
    trace.accept(greedy, trace.now(), 'G', 0, None)
    greedy_done = trace.now()
    radius = None if method in ('G', 'Full-MILP') else (max(4, math.ceil(len(task['missions'])/4)) if method == 'R_frac' else 4)
    neighborhoods, phases, proofs = [], [], []
    stop = 'greedy_complete' if method == 'G' else 'budget'
    current = greedy
    neighborhood = 0
    global_optimal = False
    bounds, bound_proof = engine.service_lower_bounds()
    while method != 'G' and trace.now() < budget and trace.best_plan is not None:
        neighborhood += 1
        local_start = trace.now()
        center = list(current)
        center_score = engine.verify(center)
        built = engine.build(seed=center if radius is not None else None, k=radius)
        build_done = trace.now()
        nrec = {'index': neighborhood, 'start_seconds': local_start,
                'build_seconds': build_done-local_start, 'radius': radius,
                'center_objective': center_score['objective'],
                'center_decisions': center, 'variables': built['variables'],
                'constraints': built['base_rows'], 'slice_continuations': []}
        neighborhoods.append(nrec)
        A, lb, ub = built['A'], built['lb'], built['ub']
        last_x = plan_x(built, center)
        fixed_holds = 0
        proven = 0
        next_slice = local_start + slice_seconds
        interrupted_for_update = False
        for stage, name in enumerate(TIERS):
            if trace.now() >= budget:
                break
            c = built['costs'][stage].copy()
            nearest = np.rint(c)
            c[np.abs(c-nearest)<1e-9] = nearest[np.abs(c-nearest)<1e-9]
            constant = 0.
            if stage == 2:
                c -= 1000*built['scales'][2]*built['costs'][1]
                constant = 1000*fixed_holds
            stage_start = trace.now()
            analytic = stage < 2 and abs(float(c@last_x)-bounds[stage]) < 1e-8
            status = 'Optimal (public lower bound)' if analytic else None
            dual = float(bounds[stage]) if analytic else None
            stage_x = last_x if analytic else None
            if not analytic:
                h = make_highs(c, A, lb, ub, last_x)

                def interrupt(event):
                    nonlocal next_slice, interrupted_for_update
                    now = trace.now()
                    if now >= budget:
                        event.interrupt()
                    elif method == 'Iter-R4' and now >= next_slice:
                        if compare(trace.best_score['objective'], center_score['objective']) < 0:
                            interrupted_for_update = True
                            event.interrupt()
                        else:
                            nrec['slice_continuations'].append({'seconds': now, 'tier': name,
                                'action': 'continue_same_live_solver_state'})
                            next_slice = now + slice_seconds

                def candidate(event):
                    callback_start = time.perf_counter()
                    trace.callback_count += 1
                    generated = trace.now()
                    x = np.asarray(event.data_out.mip_solution).copy()
                    if len(x) == built['variables'] and np.max(np.abs(x-np.rint(x))) < 1e-5:
                        plan = engine.extract(built, np.rint(x))
                        trace.accept(plan, generated, 'highs_mip_solution', neighborhood, name)
                    interrupt(event)
                    trace.callback_seconds += time.perf_counter() - callback_start

                h.cbMipSolution += candidate
                h.cbMipInterrupt += interrupt
                h.cbSimplexInterrupt += interrupt
                remaining = budget - trace.now()
                if remaining <= 0:
                    break
                h.setOptionValue('time_limit', float(remaining))
                h.run()
                info, sol, model_status = h.getInfo(), h.getSolution(), h.getModelStatus()
                status = h.modelStatusToString(model_status)
                dual = float(info.mip_dual_bound) if np.isfinite(info.mip_dual_bound) else None
                if info.primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible and sol.value_valid:
                    stage_x = np.rint(np.asarray(sol.col_value))
                    trace.accept(engine.extract(built, stage_x), trace.now(), 'stage_return', neighborhood, name)
                stage_optimal = model_status == highspy.HighsModelStatus.kOptimal
            else:
                stage_optimal = True
            at = trace.now()
            certified = stage_optimal and stage_x is not None and at <= budget
            phase = {'neighborhood': neighborhood, 'tier': name, 'status': status,
                     'proved': certified, 'start_seconds': stage_start, 'end_seconds': at,
                     'seconds': at-stage_start,
                     'lower_bound': dual/built['scales'][stage]+constant if dual is not None else None,
                     'upper_bound': float(c@stage_x/built['scales'][stage]+constant) if stage_x is not None else None}
            if analytic:
                phase['proof'] = 'public final-departure pad quota'
            phases.append(phase)
            if stage_x is not None:
                last_x = stage_x
            if not certified:
                break
            proven += 1
            proofs.append({'neighborhood': neighborhood, 'proved_prefix': proven,
                           'available_seconds': at, 'scope': 'global' if radius is None else 'neighborhood'})
            value = float(c@stage_x)
            if stage < 3:
                value = float(round(value))
            if stage == 1:
                fixed_holds = round(value)
            tol = 0. if stage < 2 else 1e-5 if stage in (3,4) else 1e-7
            A = vstack([A, csr_matrix(c.reshape(1, -1))], format='csr')
            lb, ub = np.append(lb, value-tol), np.append(ub, value+tol)
            if method == 'Iter-R4' and trace.now() >= next_slice and compare(trace.best_score['objective'], center_score['objective']) < 0:
                interrupted_for_update = True
                break
        nrec.update(end_seconds=trace.now(), proved_prefix=proven)
        improved = compare(trace.best_score['objective'], center_score['objective']) < 0
        nrec['strict_improvement'] = improved
        if method == 'Full-MILP' and proven == 6:
            global_optimal = True
        if method != 'Iter-R4':
            stop = 'all_objectives_proved' if proven == 6 else 'budget_or_solver_stop'
            break
        if improved and trace.now() < budget:
            current = trace.best_plan
            nrec['next_action'] = 'update_center'
            continue
        if proven == 6:
            stop = 'neighborhood_optimal_no_improvement'
        else:
            stop = 'budget_or_solver_stop'
        break
    return {'protocol': PROTOCOL, 'record_id': task['record_id'], 'method': method,
            'task_sha256': hashlib.sha256(raw).hexdigest(), 'budget_seconds': budget,
            'slice_seconds': slice_seconds, 'radius': radius,
            'started_utc': datetime.fromtimestamp(time.time()-trace.now(), timezone.utc).isoformat(),
            'total_seconds': trace.now(), 'greedy_available_seconds': greedy_done,
            'stop_reason': stop, 'global_optimal': global_optimal,
            'admissible': trace.best_plan is not None,
            'decisions': trace.best_plan,
            'objective': trace.best_score['objective'] if trace.best_score else None,
            'metrics': metrics(task, trace.best_score) if trace.best_score else None,
            'events': trace.events, 'improvements': trace.improvements,
            'neighborhoods': neighborhoods, 'phases': phases, 'proof_events': proofs,
            'service_bound_proof': bound_proof, 'callback_count': trace.callback_count,
            'callback_seconds': trace.callback_seconds,
            'duplicate_candidates': trace.duplicate_count,
            'validation_seconds': trace.validation_seconds, 'solver': 'HiGHS '+VERSION,
            'solver_threads': 1, 'warm_start': 'own timed G and own proved preceding tier',
            'reference_used_online': False, 'quality_tolerance': QUALITY_TOL}
