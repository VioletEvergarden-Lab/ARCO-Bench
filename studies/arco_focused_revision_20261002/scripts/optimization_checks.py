"""Small checks of the new timing/trace boundaries, without extra solver runs."""
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from optimization_online import Engine, ROOT, Trajectory, plan_x, TIERS


def main():
    task = json.loads((ROOT/'arco_closing_study/networks/tasks/NET_S01_A.json').read_text())
    engine = Engine(task)
    greedy = engine.greedy()
    built = engine.build(greedy, 4)
    x = plan_x(built, greedy)
    assert int((built['A'][-1]@x).item()) == len(greedy)
    # One row coefficient per original mission decision: all fields jointly
    # changed still consume one mission distance, never one per field.
    for mid, idx in built['indices'].items():
        row = built['A'][-1, idx].toarray().ravel()
        assert np.count_nonzero(row) <= 1
        original = next(d for d in greedy if d['mission_id']==mid)
        alternatives = [i for i in idx if any(built['meta'][i][k] != original[k]
                         for k in ('path_id','depart_min','charge_blocks'))]
        if alternatives:
            changed = x.copy()
            changed[idx + [built['holds'][mid]]] = 0
            changed[alternatives[-1]] = 1
            assert int((built['A'][-1]@changed).item()) == len(greedy)-1
    # A valid proposal generated before the cutoff but validated after it must
    # not enter the delivered incumbent or any cutoff slice.
    trace = Trajectory(engine, 0., 600.)
    with patch.object(trace, 'now', return_value=600.0001):
        trace.accept(greedy, 599.9, 'boundary_check', 0, None)
    assert trace.best_plan is None
    assert not trace.events[-1]['within_budget']
    timely = Trajectory(engine, 0., 600.)
    with patch.object(timely, 'now', return_value=599.999):
        timely.accept(greedy, 599.9, 'boundary_check', 0, None)
    assert timely.best_plan == greedy
    # The old event verifier remains the source of suffix, SOC and booking
    # validity; a held predecessor followed by service cannot be delivered.
    invalid = [dict(d) for d in greedy]
    first = engine.chains[next(iter(engine.chains))][0]['mission_id']
    for d in invalid:
        if d['mission_id']==first:
            d.update(held=True,path_id=None,depart_min=None,charge_blocks=0)
    rejected = Trajectory(engine, 0., 600.)
    with patch.object(rejected, 'now', return_value=1.):
        rejected.accept(invalid, .5, 'suffix_check', 0, None)
    assert rejected.best_plan is None and 'SUFFIX_HOLD' in rejected.events[0]['errors']
    # Smoke proof events and deliveries must lie in their measured budgets.
    smoke = Path(__file__).resolve().parents[1]/'results/comparison/smoke'
    checks = []
    for p in smoke.glob('*__*.json'):
        run = json.loads(p.read_text())
        assert all(e['available_seconds']<=run['budget_seconds'] for e in run['improvements'])
        assert all(e['available_seconds']<=run['budget_seconds'] for e in run['proof_events'])
        for n in run['neighborhoods']:
            pp = [r for r in run['phases'] if r['neighborhood']==n['index']]
            proved = [r['tier'] for r in pp if r['proved']]
            assert proved == list(TIERS[:len(proved)])
        checks.append(p.name)
    result={'passed':True,'checks':['grouped task radius','late verification excluded',
              'on-time verification retained','suffix hold rejected','proof prefix contiguous',
              'no post-budget proof or improvement'], 'smoke_files':checks}
    out=smoke.parent/'boundary_checks.json'
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
