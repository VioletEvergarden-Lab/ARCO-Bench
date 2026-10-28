"""Static, source-backed manuscript figures from the frozen paired references."""
import csv,json,math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from new_networks import ROOT,OUT,Engine,read,write

plt.rcParams.update({'font.family':'Times New Roman','font.size':9,'axes.titlesize':10,'axes.labelsize':9,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
SHORT='#2B5776';LONG='#C66631';GREY='#C9CDD1'
FIG=ROOT/'figures'

def save(fig,name):
 for ext in ('pdf','svg','png'):fig.savefig(FIG/(name+'.'+ext),dpi=240,bbox_inches='tight',facecolor='white')
 plt.close(fig)

def pairs():
 rows=list(csv.DictReader((ROOT/'results/new_pairs.csv').open(encoding='utf-8-sig')))
 fig,axes=plt.subplots(1,3,figsize=(8.2,5.1),sharey=True,gridspec_kw={'width_ratios':[1,1,1.15]})
 y=[i+(1 if i>=6 else 0) for i in range(12)]
 labels=[('Ladder' if r['topology']=='ladder' else 'Regions')+' '+r['scale']+r['network_id'][-2:] for r in rows]
 for ax,measure,title,maxi in zip(axes[:2],('reroutes','charge_blocks'),('(a) Rerouted missions','(b) Charging blocks'),(2,7)):
  for yi,r in zip(y,rows):
   a,b=int(r['short_'+measure]),int(r['long_'+measure]);ax.plot([a,b],[yi,yi],color=GREY,lw=2,zorder=1)
   ax.scatter(a,yi,facecolors='white',edgecolors=SHORT,marker='o',s=38,linewidth=1.4,zorder=3);ax.scatter(b,yi,color=LONG,marker='|',s=95,linewidth=2,zorder=4)
  ax.set_xlim(-.25,maxi+.45);ax.set_xticks(range(maxi+1));ax.set_title(title,loc='left',pad=12);ax.grid(axis='x',color='#E6E8EB',lw=.6);ax.set_axisbelow(True)
 axes[0].set_yticks(y,labels);axes[0].invert_yaxis();axes[0].tick_params(axis='y',length=0,pad=7)
 ax=axes[2];values=[float(r['energy_delta_kwh'])*1000 for r in rows];ax.barh(y,values,height=.45,color=LONG);ax.set_xlim(0,40);ax.set_xticks([0,10,20,30,40]);ax.set_title('(c) Extra flight energy (Wh)',loc='left',pad=12);ax.grid(axis='x',color='#E6E8EB',lw=.6);ax.set_axisbelow(True)
 for yi,value in zip(y,values):ax.text(value+.6,yi,f'{value:.1f}',va='center',fontsize=8)
 for ax in axes:ax.spines['left'].set_visible(False);ax.spines['bottom'].set_color('#92989E');ax.tick_params(axis='y',length=0);ax.axhline(6,color='#AAB0B5',lw=.6)
 handles=[Line2D([0],[0],marker='o',color='none',markeredgecolor=SHORT,markerfacecolor='white',markersize=6,label='10-min closure'),Line2D([0],[0],marker='|',color='none',markeredgecolor=LONG,markeredgewidth=2,markersize=10,label='35-min closure')]
 fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.49,-.008),ncol=2,frameon=False)
 fig.subplots_adjust(left=.15,right=.98,wspace=.37,bottom=.14,top=.92)
 save(fig,'new_paired_structure')

def case():
 nid='NEW_regions_S02';tasks={c:read(OUT/'tasks'/(nid+'_'+c+'.json')) for c in ('short','long')};scores={c:Engine(tasks[c]).verify(read(OUT/'references'/(nid+'_'+c+'.json'))['decisions']) for c in tasks};ev={c:{e['mission_id']:e for e in s['events']} for c,s in scores.items()};task=tasks['long'];e=Engine(task);m=e.missions['M009'];pos={v['vertiport_id']:v['xy_km'] for v in task['nodes']};corr={v['corridor_id']:v for v in task['corridors']}
 fig=plt.figure(figsize=(9.5,5.8));gs=fig.add_gridspec(2,2,width_ratios=[1,1.35],height_ratios=[1,1.1]);a=fig.add_subplot(gs[:,0]);b=fig.add_subplot(gs[0,1]);c=fig.add_subplot(gs[1,1])
 seen=set()
 for edge in task['corridors']:
  key=tuple(sorted((edge['origin'],edge['destination'])))
  if key in seen:continue
  seen.add(key);xy=edge['geometry_xy_km'];a.plot(*zip(*xy),color='#D5D8DB',lw=1.2,zorder=0)
 for cond,col,ls in [('short',SHORT,'--'),('long',LONG,'-')]:
  path=e.paths['M009'][ev[cond]['M009']['path_id']]
  for cid in path['corridor_ids']:
   edge=corr[cid];a.plot(*zip(*edge['geometry_xy_km']),color=col,lw=2.4,ls=ls,zorder=2)
 closed=corr[task['intervention']['resource_intervals'][0]['resource']];xy=closed['geometry_xy_km'];cx=sum(p[0] for p in xy)/2;cy=sum(p[1] for p in xy)/2;a.scatter(cx,cy,marker='x',s=80,lw=2,color='#222',zorder=5)
 for v,xy in pos.items():
  charger=task['resources']['charger'][v]>0;a.scatter(*xy,s=90 if charger else 65,marker='s' if charger else 'o',color='white',edgecolors='#4D555B',zorder=4);a.text(xy[0],xy[1]+.055,v,ha='center',fontsize=10.5)
 a.set_aspect('equal');a.set_xlabel('x (km)');a.set_ylabel('y (km)');a.set_title('(a) M009 route choice',loc='left');a.text(.02,.035,'Squares: charging facilities\nCross: closed corridor',transform=a.transAxes,fontsize=10.5,va='bottom');a.set_ylim(-.62,.48)
 for yi,cond,col in [(1,'short',SHORT),(0,'long',LONG)]:
  first,final=ev[cond]['M008'],ev[cond]['M009'];b.plot([first['arrival_min'],first['charge_start_min']],[yi,yi],color='#9CA3AA',lw=4)
  if first['charge_blocks']:b.plot([first['charge_start_min'],first['finish_min']],[yi,yi],color=col,lw=7);b.text((first['charge_start_min']+first['finish_min'])/2,yi+.16,'Charge 10 min',ha='center',fontsize=10.5,color=col)
  b.plot([final['depart_min'],final['arrival_min']],[yi,yi],color=col,lw=4);b.scatter(final['depart_min'],yi,color=col,s=20);b.text(final['arrival_min']+.6,yi,f"Arrive {final['arrival_min']:.2f}",va='center',fontsize=10.5,color=col)
 b.axvline(35,color='#5D6369',ls=':',lw=1);b.text(35,.65,'Departure\nhorizon',ha='right',fontsize=10.5);b.set_yticks([0,1],['35-min closure','10-min closure']);b.set_xlim(16,44);b.set_ylim(-.45,1.6);b.set_xlabel('Time (min)');b.set_title('(b) U03: charging before the detour',loc='left');b.spines['left'].set_visible(False);b.tick_params(axis='y',length=0)
 data=[]
 for cond,col,ls in [('short',SHORT,'--'),('long',LONG,'-')]:
  chain=[ev[cond][mid] for mid in ('M006','M007','M008','M009')];times=[0];soc=[79.92]
  for evv in chain:
   times.extend([evv['depart_min'],evv['arrival_min'],evv['charge_start_min'],evv['finish_min']]);soc.extend([evv['soc_before_kwh']*1000,evv['soc_arrival_kwh']*1000,evv['soc_arrival_kwh']*1000,evv['soc_after_charge_kwh']*1000])
  c.plot(times,soc,color=col,ls=ls,lw=1.8,label='10-min closure' if cond=='short' else '35-min closure');data.append({'condition':cond,'time_min':times,'soc_Wh':soc})
 reserve=task['fleet'][0]['reserve_kwh']*1000;c.axhline(reserve,color='#4A4F55',ls=':',lw=1);c.text(1,reserve+2,'Reserve 19.98 Wh',fontsize=10.5)
 no_charge=(ev['long']['M008']['soc_arrival_kwh']-ev['long']['M009']['flight_energy_kwh'])*1000;c.scatter(ev['long']['M009']['arrival_min'],no_charge,marker='x',s=35,color='#333');c.annotate(f'Without added charge:\n{no_charge:.2f} Wh',xy=(ev['long']['M009']['arrival_min'],no_charge),xytext=(19,2),fontsize=10.5,arrowprops={'arrowstyle':'-','color':'#777'})
 c.set_xlim(0,41);c.set_ylim(0,85);c.set_xlabel('Time (min)');c.set_ylabel('Battery energy (Wh)');c.set_title('(c) U03 battery trajectory',loc='left');c.grid(axis='y',color='#E8EBED',lw=.6);c.legend(frameon=False,loc='upper right',fontsize=10.5)
 for ax in (a,b,c):
  ax.tick_params(axis='both',labelsize=10.5)
  ax.xaxis.label.set_size(11.5);ax.yaxis.label.set_size(11.5)
  ax.title.set_size(12)
 fig.subplots_adjust(left=.07,right=.98,top=.94,bottom=.105,wspace=.46,hspace=.7)
 save(fig,'new_route_energy_case');write(ROOT/'results/new_case_plot_data.json',data)

if __name__=='__main__':pairs();case();print('Wrote new_paired_structure and new_route_energy_case: PDF, SVG, PNG')
