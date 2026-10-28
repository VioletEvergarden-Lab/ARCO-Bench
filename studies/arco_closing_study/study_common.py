"""Shared paths and archive imports for the independent closing study."""
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
R30=ROOT/'arco_codex_research_20260930'
R25=ROOT/'arco_codex_research_20260925'
P=ROOT.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(R30))
from common import Runtime,local_repair,read,write,jl,jsonl,csvout,diff,TIERS

