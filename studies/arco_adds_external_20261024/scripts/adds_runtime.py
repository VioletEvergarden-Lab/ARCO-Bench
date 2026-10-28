"""Load the self-contained ADDS sortie runtime and unchanged query machinery."""
from pathlib import Path
import importlib,json,sys,types
ROOT=Path(__file__).resolve().parents[1]

def load_runtime():
    sys.dont_write_bytecode=True
    vendor=ROOT/'runtime'
    sys.path.insert(0,str(vendor))
    shared=types.ModuleType('study_common')
    shared.HERE=ROOT/'runs'
    shared.TIERS=['urgent_holds','total_holds','repair_distance','weighted_tardiness_min','delay_and_charge_wait_min','energy_kwh']
    def write(path,obj):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    shared.write=write;sys.modules['study_common']=shared
    physical=types.ModuleType('physical_model')
    physical.MODEL=json.loads((vendor/'model_parameters.json').read_text(encoding='utf-8'))
    sys.modules['physical_model']=physical
    engine=importlib.import_module('continuous_engine')
    coordination=importlib.import_module('coordination_solver')
    for name in ('base_engine','continuous_engine','solver_backend','coordination_solver'):
        module=importlib.import_module(name)
        if Path(module.__file__).resolve().parent!=vendor.resolve():
            raise RuntimeError(f'Nonlocal runtime module: {name}: {module.__file__}')
    return engine,coordination.CoordinationProblem,coordination.changes,coordination.target_met,physical.MODEL
