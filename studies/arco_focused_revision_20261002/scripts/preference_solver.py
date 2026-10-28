"""Lexicographic diagnostic solves; only certified prefixes are fixed."""
from pathlib import Path
import sys, time
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'arco_closing_study'
sys.path.insert(0, str(OLD))
import numpy as np
from scipy.sparse import csr_matrix, vstack
from continuous_engine import Engine, QUALITY_TOL, EPS_TIME
from study_common import TIERS
from solver_backend import solve as mip, VERSION

ORDER = (0, 1, 3, 2, 4, 5)

def lex_compare(a, b, order=ORDER):
    for j in order:
        if a[TIERS[j]] < b[TIERS[j]] - QUALITY_TOL[j]: return -1
        if a[TIERS[j]] > b[TIERS[j]] + QUALITY_TOL[j]: return 1
    return 0

def solve(task, budget=600., order=ORDER, warm=None, allowed=None, service=None):
    start = time.perf_counter()
    engine = Engine(task)
    built = engine.build(allowed=allowed)
    A, lb, ub = built['A'], built['lb'], built['ub']
    def add_row(c, lower, upper):
        nonlocal A, lb, ub
        A = vstack([A, csr_matrix(c.reshape(1, -1))], format='csr')
        lb, ub = np.append(lb, lower), np.append(ub, upper)
    if service is not None:
        for j, value in enumerate(service): add_row(built['costs'][j], value, value)
    best_x = last_x = None
    best_vector = None
    if warm is not None:
        sc = engine.verify(warm)
        if sc['admissible'] and (service is None or all(sc['objective'][TIERS[j]] == v for j,v in enumerate(service))) and (allowed is None or all(d['held'] or allowed(d) for d in warm)):
            last_x = np.zeros(built['variables'])
            for d in warm:
                mid = d['mission_id']
                pick = built['holds'][mid] if d['held'] else next(i for i in built['indices'][mid] if all(built['meta'][i][k] == d[k] for k in ('path_id','depart_min','charge_blocks')))
                last_x[pick] = 1.
            best_x, best_vector = last_x.copy(), sc['objective']
    phases = []
    fixed_holds = None
    public_bounds, _ = engine.service_lower_bounds()
    build_seconds = time.perf_counter() - start
    for j in order:
        remain = budget - (time.perf_counter() - start)
        if remain <= 0: break
        c = built['costs'][j].copy()
        near = np.rint(c); c[np.abs(c-near)<1e-9] = near[np.abs(c-near)<1e-9]
        constant = 0.
        if j == 2 and fixed_holds is not None:
            c -= 1000 * built['scales'][2] * built['costs'][1]
            constant = 1000 * fixed_holds
        clock = time.perf_counter()
        if j < 2 and last_x is not None and abs(float(c @ last_x) - (service[j] if service is not None else public_bounds[j])) < 1e-8:
            from types import SimpleNamespace
            result = SimpleNamespace(status=0, x=last_x, mip_dual_bound=float(c@last_x), mip_gap=0., message='certified service constraint' if service is not None else 'public final-departure pad bound')
        else:
            result = mip(c, A, lb, ub, remain, last_x)
        x = np.rint(result.x) if result.x is not None else None
        phase = {'tier':TIERS[j], 'status':int(result.status), 'status_text':result.message, 'seconds':time.perf_counter()-clock,
                 'upper_bound':float(c@x/built['scales'][j]+constant) if x is not None else None,
                 'lower_bound':float(result.mip_dual_bound/built['scales'][j]+constant) if result.mip_dual_bound is not None else None,
                 'mip_gap':result.mip_gap}
        phases.append(phase)
        if x is not None:
            sc = engine.verify(engine.extract(built,x))
            if not sc['admissible']: raise RuntimeError(('invalid solver plan',task['record_id'],sc['errors']))
            if best_vector is None or lex_compare(sc['objective'],best_vector,order)<0: best_x, best_vector = x, sc['objective']
            last_x = x
        if result.status != 0 or x is None: break
        value = float(c@x)
        if j in (0,1,2): value = float(round(value))
        if j == 1: fixed_holds = round(value)
        tolerance = 0. if j < 2 else 1e-5 if j in (3,4) else EPS_TIME
        add_row(c,value-tolerance,value+tolerance)
    complete = len(phases)==6 and all(p['status']==0 for p in phases)
    chosen = last_x if complete else best_x
    decisions = engine.extract(built,chosen) if chosen is not None else None
    score = engine.verify(decisions) if decisions is not None else None
    return {'record_id':task['record_id'],'objective_order':[TIERS[j] for j in order],
            'optimal':complete,'proved_prefix':sum(p['status']==0 for p in phases),'phases':phases,
            'decisions':decisions,'objective':score['objective'] if score else None,
            'status':'optimal' if complete else 'infeasible' if phases and phases[-1]['status']==2 else 'limit_or_unknown',
            'build_seconds':build_seconds,'total_seconds':time.perf_counter()-start,'budget_seconds':budget,
            'solver':'HiGHS '+VERSION,'solver_threads':1,'fixed_service':service,'variables':built['variables'],
            'prefix_policy':'fix only status=optimal or a valid certified service bound; stop at first unproved layer'}
