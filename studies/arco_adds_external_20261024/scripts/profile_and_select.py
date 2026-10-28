"""Profile supplied ADDS inputs and select waves before any new solver outputs."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import csv,json,math,hashlib,shutil,statistics
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'arco_adds_operational_20261021'
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
out=ROOT/'analysis/input_selection.json'
if out.exists():raise RuntimeError('Selection already recorded; do not overwrite after seeing results')
sources={
 'source/Data.xlsx':OLD/'source/Data.xlsx',
 'source/ADDS_README.txt':OLD/'source/README.txt',
 'source/zenodo_record.json':OLD/'source/zenodo_record.json',
 'source/demand_model_geometry.csv':OLD/'analysis/demand_model_geometry.csv',
 'source/model_geometry.json':OLD/'analysis/model_geometry.json',
 'source/data_cells.json':OLD/'analysis/data_cells.json'}
provenance=[]
for rel,src in sources.items():
 dst=ROOT/rel
 if not src.exists():src=dst
 if src.resolve()!=dst.resolve():shutil.copy2(src,dst)
 provenance.append(dict(path=rel,original_path=src.relative_to(ROOT.parent).as_posix(),sha256=digest(dst)))
rows=list(csv.DictReader((ROOT/'source/demand_model_geometry.csv').open(encoding='utf-8-sig')))
objects={o['name']:o for o in json.loads((ROOT/'source/model_geometry.json').read_text(encoding='utf-8'))['objects']}
assert len(rows)==300 and len({r['demand_id'] for r in rows})==300
assert all(int(r['quantity'])==1 for r in rows)
for r in rows:
 for flag in ['building_recovered','locker_recovered','demand_node_matches_model','demand_locker_matches_model','locker_node_matches_model']:
  assert r[flag]=='True',(r['demand_id'],flag)
 assert r['locker_id'] in objects and r['building_id'] in objects
 dist=math.hypot(float(r['building_x'])-float(r['locker_x']),float(r['building_y'])-float(r['locker_y']))
 assert abs(dist-float(r['locker_to_building_raw_distance']))<1e-7
 assert float(r['weight_kg'])>0
 # Verify row-to-workbook data exported during source recovery.
cells=json.loads((ROOT/'source/data_cells.json').read_text(encoding='utf-8'))['Demand']
headers=cells[0]['values'];source_rows={r['row']:dict(zip(headers,r['values'])) for r in cells[1:]}
for r in rows:
 s=source_rows[int(r['demand_excel_row'])]
 assert (str(s['Nr']),s['BUD'],s['PACZ'],float(s['WAGA']),int(s['SZT']))==(r['demand_id'],r['building_id'],r['locker_id'],float(r['weight_kg']),int(r['quantity']))
eligible=[r for r in rows if float(r['weight_kg'])==0.5]
groups={hub:[r for r in eligible if r['locker_id']==hub] for hub in sorted({r['locker_id'] for r in rows})}
# Larger wave at the two hubs with most eligible source parcels; source order
# selects demand records, independently of distances or recovery outcomes.
large=set(sorted(groups,key=lambda h:(-len(groups[h]),h))[:2])
waves=[];profiles=[]
for hub,light in groups.items():
 all_rows=[r for r in rows if r['locker_id']==hub]
 n=9 if hub in large else 6
 chosen=sorted(light,key=lambda r:int(r['demand_excel_row']))[:n]
 assert len(chosen)==n
 def stats(rs):
  d=[float(r['locker_to_building_raw_distance']) for r in rs]
  return dict(min=min(d),median=statistics.median(d),max=max(d),mean=statistics.mean(d))
 profiles.append(dict(locker_id=hub,total_records=len(all_rows),eligible_records=len(light),
  weights=dict(sorted(Counter(r['weight_kg'] for r in all_rows).items())),source_distance_m=stats(all_rows),eligible_distance_m=stats(light),
  selected_distance_m=stats(chosen)))
 waves.append(dict(base_id='ADDS_'+hub.replace('_','')+f'_N{n:02d}',locker_id=hub,missions=n,uavs=3,
  chain_length=n//3,source_rows=chosen,
  assignment=[dict(source_demand_id=int(r['demand_id']),source_excel_row=int(r['demand_excel_row']),
     mission_id=f'M{i+1:03d}',uav_id=f'U{i%3+1:02d}',sequence_index=i//3+1) for i,r in enumerate(chosen)]))
result=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),stage='input-based selection before new runtime pilot/reference/candidate results',
 source_count=300,source_unique_buildings=len({r['building_id'] for r in rows}),eligible_count=len(eligible),selected_parcels=sum(w['missions'] for w in waves),
 eligibility='Single 0.5 kg source parcels; this is a declared ARCO M100 light-payload scenario, not a claim that 0.5 kg is the aircraft rated maximum.',
 selection_rule='Include all five source locker service areas. Use nine parcels at the two areas with most eligible records, six at the other three. Select first eligible workbook rows in each area; assign round-robin to three fixed UAV chains in source order.',
 intended_design=dict(departure_grid_min=0.5,pad_window_min=1,resource_window_min=1,load_min=5/60,unload_min=5/60,
  no_charging=True,all_routine=True,due_slack_min=3,shared_hub_movements_per_minute=1,
  formal_conditions=['CONTROL','CLOSE_2MIN','CLOSE_5MIN'],closure_start_min=0,
  dispatch_horizon_rule='latest no-disruption incumbent departure rounded up to an integer minute, plus 8 minutes; fixed across conditions of each base',
  label='Design configuration subject only to pre-freeze semantic/feasibility/cost checks; no formal model outputs yet'),
 profiles=profiles,waves=waves,source_provenance=provenance,
 source_integrity=dict(all_geometry_joined=True,source_records_match=True,unique_demand_ids=True,all_quantities_one=True))
write(out,result)
with (ROOT/'analysis/source_profile.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['locker_id','source_records','eligible_0_5kg','selected','source_distance_min_m','source_distance_median_m','source_distance_max_m','selected_mean_distance_m'])
 for p,wave in zip(profiles,waves):w.writerow([p['locker_id'],p['total_records'],p['eligible_records'],wave['missions'],p['source_distance_m']['min'],p['source_distance_m']['median'],p['source_distance_m']['max'],p['selected_distance_m']['mean']])
print(json.dumps({k:result[k] for k in ('source_count','source_unique_buildings','eligible_count','selected_parcels')},indent=2))
print([(w['base_id'],w['missions']) for w in waves])
