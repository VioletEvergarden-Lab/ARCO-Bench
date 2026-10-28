"""Recover saved XML geometry from bounded FlexSim bytes; never execute model code.

Each complete named object is independently parsed with ElementTree. The saved
dt=1 numeric representation contains two big-endian IEEE-754 words in low-word,
high-word order. Decode by swapping those 32-bit words, validated against exact
workbook coordinates for parcel lockers and the network nodes present in sample.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'source/flexsim_tail16mb_sample.bin'
DATA = SOURCE.read_bytes()
SAMPLING = json.loads((ROOT / 'source/flexsim_sampling.json').read_text(encoding='utf-8'))
MATCHING_RANGES = [span for span in SAMPLING['ranges'] if span[1] - span[0] + 1 == len(DATA) and span[1] == SAMPLING['total_bytes']-1]
assert len(MATCHING_RANGES) == 1, MATCHING_RANGES
RANGE_START = MATCHING_RANGES[0][0]
START = re.compile(rb'<node\b[^>]*\bdt="4"[^>]*><name>(BUD_\d+|PACZ_\d+|\d+)</name><data>')
NODE_TOKEN = re.compile(rb'<node(?:\s[^>]*)?>|</node>')

def complete_fragment(start):
    level = 0
    for token in NODE_TOKEN.finditer(DATA, start):
        if token.group() == b'</node>':
            level -= 1
        elif not token.group().endswith(b'/>'):
            level += 1
        if level == 0:
            return DATA[start:token.end()], token.end()
    return None, None

def named_child(element, name):
    if element is None:
        return None
    return next((node for node in element.findall('node') if node.findtext('name') == name), None)

def decode_number(text):
    assert re.fullmatch(r'[a-fA-F0-9]{16}', text), text
    number_bytes = bytes.fromhex(text)
    value = struct.unpack('>d', number_bytes[4:] + number_bytes[:4])[0]
    assert math.isfinite(value), text
    return value

assert decode_number('000000003ff00000') == 1.0
objects, incomplete, skipped = [], [], []
for match in START.finditer(DATA):
    name = match[1].decode('ascii')
    fragment, end = complete_fragment(match.start())
    if fragment is None:
        incomplete.append(name)
        continue
    element = ET.fromstring(fragment)
    content = element.find('data')
    classes_element = named_child(content, 'classes')
    class_names = [node.findtext('name') for node in classes_element.findall('node') if node.findtext('name')] if classes_element is not None else []
    spatial = named_child(content, 'spatial')
    if spatial is None:
        skipped.append(name)
        continue
    geometry, raw_hex = {}, {}
    for field in ['spatialx','spatialy','spatialz','spatialsx','spatialsy','spatialsz','spatialrx','spatialry','spatialrz']:
        field_node = named_child(spatial, field)
        if field_node is not None:
            raw_hex[field] = field_node.findtext('data')
            geometry[field] = decode_number(raw_hex[field])
    assert all(field in geometry for field in ['spatialx','spatialy','spatialz']), name
    variables = named_child(content, 'variables')
    network_node = named_child(variables, 'networknodes')
    network_couplings = [node.text for node in network_node.findall('.//coupling')] if network_node is not None else []
    network_ids = []
    for coupling in network_couplings:
        found = re.match(r'^/"?(\d+)"?>', coupling)
        if found:
            network_ids.append(int(found[1]))
    connections = named_child(content, 'connections')
    center = named_child(connections, 'connectionscenter')
    center_couplings = [node.text for node in center.findall('.//coupling') if node.text != 'null'] if center is not None else []
    locker_ids = sorted(set(m[1] for path in center_couplings if (m := re.match(r'^/(PACZ_\d+)>', path))))
    objects.append({'name':name, 'kind':'building' if name.startswith('BUD_') else 'locker' if name.startswith('PACZ_') else 'network_node' if 'NetworkNode' in class_names else 'other_named_object',
                    'class_names':class_names,
                    **geometry, 'raw_hex':raw_hex, 'network_node_ids':network_ids,
                    'network_node_couplings':network_couplings,'center_couplings':center_couplings,
                    'associated_locker_ids':locker_ids,
                    'sample_byte_range':[match.start(),end-1], 'original_file_byte_range':[RANGE_START+match.start(),RANGE_START+end-1]})

assert len({obj['name'] for obj in objects}) == len(objects)
lookup = {obj['name']:obj for obj in objects}
book = load_workbook(ROOT/'source/Data.xlsx',read_only=True,data_only=False)
nodes = {row[0]:(i,row[1],row[2]) for i,row in enumerate(list(book['Nodes'].values)[1:],2)}
lockers = {row[0]:(i,row) for i,row in enumerate(list(book['Parcel lockers'].values)[1:],2)}
demand = list(enumerate(list(book['Demand'].values)[1:],2))

validation=[]
for name,obj in lookup.items():
    if obj['kind']=='network_node' and int(name) in nodes:
        row,x,y = nodes[int(name)];sheet='Nodes'
    elif obj['kind']=='locker' and name in lockers:
        row,source_row = lockers[name];x,y = source_row[1:3];sheet='Parcel lockers'
    else:
        continue
    validation.append({'name':name,'sheet':sheet,'row':row,'workbook_x':x,'workbook_y':y,
                       'model_x':obj['spatialx'],'model_y':obj['spatialy'],
                       'x_difference':obj['spatialx']-x,'y_difference':obj['spatialy']-y,
                       'exact_match':obj['spatialx']==x and obj['spatialy']==y})

joined=[]
for row,record in demand:
    serial,bid,lid,qty,weight,node,l_node = record
    b=lookup.get(bid);l=lookup.get(lid)
    joined.append({'demand_excel_row':row,'demand_id':serial,'building_id':bid,'locker_id':lid,
                   'quantity':qty,'weight_kg':weight,'demand_network_node':node,'demand_locker_node':l_node,
                   'building_recovered':b is not None,'locker_recovered':l is not None,
                   'building_x':b['spatialx'] if b else None,'building_y':b['spatialy'] if b else None,
                   'locker_x':l['spatialx'] if l else None,'locker_y':l['spatialy'] if l else None,
                   'model_building_network_nodes':b['network_node_ids'] if b else [],
                   'model_building_locker_ids':b['associated_locker_ids'] if b else [],
                   'demand_node_matches_model':node in b['network_node_ids'] if b else False,
                   'demand_locker_matches_model':lid in b['associated_locker_ids'] if b else False,
                   'locker_node_matches_model':l_node in l['network_node_ids'] if l else False,
                   'locker_to_building_raw_distance':math.hypot(b['spatialx']-l['spatialx'],b['spatialy']-l['spatialy']) if b and l else None})

counts={kind:sum(o['kind']==kind for o in objects) for kind in ['building','locker','network_node','other_named_object']}
out={'source':str(SOURCE.resolve()),'source_sha256':hashlib.sha256(DATA).hexdigest(),
     'source_bytes':len(DATA),'original_file_sample_range':[RANGE_START,RANGE_START+len(DATA)-1],
     'method':'Balanced complete XML objects, ElementTree structural reads, numeric dt=1 low/high 32-bit word swap. No simulation scripts, expressions, or callbacks are executed.',
     'counts':counts,'incomplete_named_objects':incomplete,'skipped_no_spatial':skipped,
     'validation':validation,'validation_all_exact':all(v['exact_match'] for v in validation),
     'validation_locker_count':sum(v['sheet']=='Parcel lockers' for v in validation),
     'validation_network_node_count':sum(v['sheet']=='Nodes' for v in validation),
     'demand_coverage':{'rows':len(joined),'unique_building_ids':len({r['building_id'] for r in joined}),
                        'rows_with_building_geometry':sum(r['building_recovered'] for r in joined),
                        'rows_with_locker_geometry':sum(r['locker_recovered'] for r in joined),
                        'rows_with_matching_network_node':sum(r['demand_node_matches_model'] for r in joined),
                        'rows_with_matching_locker':sum(r['demand_locker_matches_model'] for r in joined),
                        'rows_with_matching_locker_network_node':sum(r['locker_node_matches_model'] for r in joined)},
     'interpretation':[
         'The saved model contains geometry for every Demand BUD identifier; the published Residential buildings sheet does not provide this mapping.',
         'Exact locker and sampled network-node equality validates decoding and establishes a common numerical coordinate system with Data.xlsx Nodes/Parcel lockers. No translation or scaling is needed to overlay these saved model objects.',
         'This extraction does not establish CRS, physical distance units, geographic correctness, original map transform, or aircraft suitability. The stored locker-to-node distance factor of five still needs separate interpretation.',
         'Recovered geometry is saved model state, not measured parcel-flight logs. The complete model and its runtime behavior were not executed.'
     ],'objects':objects}
(ROOT/'analysis/model_geometry.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
fields=['name','kind','spatialx','spatialy','spatialz','network_node_ids','associated_locker_ids']
with (ROOT/'analysis/model_geometry.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for obj in objects:
        writer.writerow({key:json.dumps(obj[key],ensure_ascii=False) if isinstance(obj[key],list) else obj[key] for key in fields})
with (ROOT/'analysis/demand_model_geometry.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(joined[0]));writer.writeheader()
    for record in joined:
        writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,list) else value for key,value in record.items()})
print(json.dumps({key:value for key,value in out.items() if key not in ['objects','validation']},ensure_ascii=False,indent=2))
