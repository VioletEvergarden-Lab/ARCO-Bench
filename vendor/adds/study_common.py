"""Shared objective order and optional solver output location."""
from pathlib import Path
import json
TIERS=['urgent_holds','total_holds','repair_distance','weighted_tardiness_min','delay_and_charge_wait_min','energy_kwh']
HERE=Path.cwd()/'runs'
def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
