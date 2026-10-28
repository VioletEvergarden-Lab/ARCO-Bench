"""Source-backed vector figures for the ADDS manuscript insert."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
ROOT=Path(__file__).resolve().parents[1]
for f in (ROOT/'figures/fonts').glob('*.ttf'):fm.fontManager.addfont(str(f))
plt.rcParams.update({'font.family':'Latin Modern Roman','font.size':10,'axes.labelsize':10,'axes.titlesize':11,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
COLORS=['#27648F','#AB6B25','#63804B','#9C5275','#5861A2']
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
def save(fig,name):
 for ext in ['pdf','svg','png']:fig.savefig(ROOT/'figures'/f'{name}.{ext}',dpi=180,bbox_inches='tight',facecolor='white')
 plt.close(fig)

def spatial():
 geometry=read('source/model_geometry.json');sel=read('analysis/input_selection.json')
 buildings=[r for r in geometry['objects'] if r['kind']=='building'];x0=1800000;y0=5579000
 fig,axes=plt.subplots(1,2,figsize=(8,4.5),gridspec_kw={'width_ratios':[1.5,1]})
 ax=axes[0]
 ax.scatter([(r['spatialx']-x0)/1000 for r in buildings],[(r['spatialy']-y0)/1000 for r in buildings],s=3,c='#D5D8DA',linewidth=0,zorder=0)
 for color,wave in zip(COLORS,sel['waves']):
  rows=wave['source_rows'];hx=(float(rows[0]['locker_x'])-x0)/1000;hy=(float(rows[0]['locker_y'])-y0)/1000
  bx=[(float(r['building_x'])-x0)/1000 for r in rows];by=[(float(r['building_y'])-y0)/1000 for r in rows]
  for x,y in zip(bx,by):ax.plot([hx,x],[hy,y],color=color,lw=.7,alpha=.65)
  ax.scatter(bx,by,s=15,facecolor='white',edgecolor=color,lw=.9,zorder=2)
  ax.scatter([hx],[hy],marker='s',s=42,color=color,zorder=3)
  offset=(6,-16) if wave['locker_id']=='PACZ_02' else (5,5)
  ax.annotate(wave['locker_id'].replace('PACZ_','P'),(hx,hy),xytext=offset,textcoords='offset points',color=color,fontweight='bold')
 ax.set_aspect('equal');ax.set_xlabel('Model x offset (km)');ax.set_ylabel('Model y offset (km)');ax.set_title('(a) Selected locker service areas',loc='left')
 ax.text(0,-.2,'Saved simulation coordinates; no map registration.\nOffsets: x = 1,800,000 m; y = 5,579,000 m.',transform=ax.transAxes,fontsize=8.4,va='top')
 ax=axes[1];wave=sel['waves'][-1];rows=wave['source_rows'];hx=float(rows[0]['locker_x']);hy=float(rows[0]['locker_y'])
 for j,(row,a) in enumerate(zip(rows,wave['assignment'])):
  x=(float(row['building_x'])-hx);y=(float(row['building_y'])-hy);col=COLORS[int(a['uav_id'][-1])-1]
  ax.plot([0,x],[0,y],color=col,lw=.9);ax.scatter(x,y,s=25,facecolors='white',edgecolors=col,lw=1,zorder=3)
  dx,dy=(5,4)
  if a['mission_id']=='M007':dx,dy=(-23,4)
  if a['mission_id']=='M005':dx,dy=(5,-12)
  ax.annotate(a['mission_id'][1:].lstrip('0'),(x,y),xytext=(dx,dy),textcoords='offset points',color=col)
 ax.scatter(0,0,marker='s',s=48,color='#30343B',zorder=4);ax.annotate('P05',(0,0),xytext=(5,6),textcoords='offset points',fontweight='bold')
 ax.set_aspect('equal');ax.set_xlabel('Offset from locker (m)');ax.set_ylabel('Offset from locker (m)');ax.set_title('(b) P05 fixed mission chains',loc='left')
 handles=[Line2D([0],[0],color=COLORS[i],label=f'U0{i+1}: '+', '.join(str(j) for j in range(i+1,10,3))) for i in range(3)]
 ax.legend(handles=handles,loc='upper left',bbox_to_anchor=(0,-.25),frameon=False,fontsize=9,ncol=1,handlelength=1.5)
 fig.subplots_adjust(wspace=.38,bottom=.28,top=.91)
 save(fig,'ADDS_A_source_networks')

def scopes():
 panel=read('analysis/scope_panel.json');manifest=read('instances/FROZEN.json')
 fig,ax=plt.subplots(figsize=(6.4,5.7));prefixes=[2,3,4,6]
 for y,item in enumerate(manifest['tasks']):
  for x,prefix in enumerate(prefixes):
   q=next(r for r in panel['joint_frontiers'] if r['record_id']==item['record_id'] and r['target']==f'T{prefix}')
   assert q['all_cap_queries_resolved'] and len(q['verified_pareto_pairs'])==1
   m,u=q['verified_pareto_pairs'][0];fc='#FFFFFF' if m==0 else '#DCE8F1' if m<5 else '#BAD0E1' if m<8 else '#84ABC8'
   ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor=fc,edgecolor='white',lw=2))
   ax.text(x,y,f'{m} / {u}',ha='center',va='center',fontsize=11,fontweight='bold' if m>=8 else 'normal')
 for y in [2.5,5.5,8.5,11.5]:ax.axhline(y,color='#777777',lw=.6)
 labels=[f"P{r['locker_id'][-2:]}  |  "+{'CONTROL':'Control','CLOSE_2MIN':'2-min closure','CLOSE_5MIN':'5-min closure'}[r['condition']] for r in manifest['tasks']]
 ax.set_yticks(range(15),labels);ax.set_xticks(range(4),['T2\nService','T3\nPlan deviation','T4\nTardiness','T6\nFull quality']);ax.xaxis.tick_top();ax.tick_params(length=0,pad=9)
 ax.set_xlim(-.5,3.5);ax.set_ylim(14.5,-.5)
 for s in ax.spines.values():s.set_visible(False)
 fig.text(.5,.015,'Minimum jointly attainable changes from G: missions / UAV chains.\nAll 60 target-condition pairs have exact frontiers; every displayed pair is witnessed.',ha='center',fontsize=9)
 fig.subplots_adjust(left=.34,right=.98,top=.87,bottom=.11)
 save(fig,'ADDS_B_target_scope')

def events():
 record=read('analysis/events/ADDS_PACZ05_N09__CLOSE_2MIN.json');names=['G','T3_witness','scope_witness']
 titles=['(a) G: service retained','(b) Minimum-scope T3 witness: 6 missions / 2 chains','(c) Minimum-scope T6 witness: 8 missions / 3 chains']
 fig,axes=plt.subplots(3,1,figsize=(8,6.2),sharex=True)
 for ax,name,title in zip(axes,names,titles):
  v=record['verified_plans'][name];obj=v['objective']
  ax.axvspan(0,2,color='#ECECEE',zorder=0)
  for t in range(2,13):ax.axvline(t,color='#E0E3E5',lw=.55,zorder=0)
  for e in v['events']:
   y=int(e['uav_id'][-1])-1;d=e['depart_min'];a=e['arrival_min'];rs=e['return_start_min'];ret=e['return_arrival_min']
   ax.broken_barh([(e['loading_start_min'],d-e['loading_start_min'])],(y-.18,.36),facecolors='#343A40')
   ax.broken_barh([(d,a-d)],(y-.18,.36),facecolors='#376E98',edgecolors='#376E98')
   ax.broken_barh([(a,rs-a)],(y-.18,.36),facecolors='#343A40')
   ax.broken_barh([(rs,ret-rs)],(y-.18,.36),facecolors='#D5E3EE',edgecolors='#376E98',linewidth=.7)
   ax.plot(d,y,marker='>',markersize=4,color='#243C51');ax.plot(ret,y,marker='o',markersize=3,markerfacecolor='white',markeredgecolor='#243C51')
   ax.text((d+ret)/2,y-.30,e['mission_id'].replace('M00','M'),ha='center',va='bottom',fontsize=8.8)
  ax.set_ylim(2.6,-.65);ax.set_yticks([0,1,2],['U01','U02','U03']);ax.set_xlim(0,12)
  ax.set_title(title,loc='left',pad=7)
  ax.text(.995,1.08,f"L3 = {obj['repair_distance']:.1f}; L4 = {obj['weighted_tardiness_min']:.1f} min",transform=ax.transAxes,ha='right',fontsize=9)
  ax.tick_params(axis='y',length=0)
 axes[-1].set_xticks(range(13));axes[-1].set_xlabel('Time since disruption (min); vertical guides are fixed 1-min reservation windows')
 handles=[Rectangle((0,0),1,1,facecolor='#376E98',label='Loaded delivery'),Rectangle((0,0),1,1,facecolor='#D5E3EE',edgecolor='#376E98',label='Empty return'),Rectangle((0,0),1,1,facecolor='#343A40',label='5-s handling'),Rectangle((0,0),1,1,facecolor='#ECECEE',label='Hub closure')]
 fig.legend(handles=handles,loc='lower center',ncol=4,frameon=False,bbox_to_anchor=(.5,0),fontsize=9)
 fig.subplots_adjust(left=.08,right=.98,top=.93,bottom=.12,hspace=.57)
 save(fig,'ADDS_C_sortie_events')

if __name__=='__main__':
 spatial();scopes();events();print('Rendered 3 figures as PDF/SVG/PNG')
