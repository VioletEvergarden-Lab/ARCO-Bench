"""One composite, editable scientific figure, exported as PDF/SVG/PNG."""
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from study_common import HERE,read,csvout

SOURCES=['G','R4','deepseek','luna']
COLORS={'G':'#8c8c8c','R4':'#bd8732','deepseek':'#355f88','luna':'#8b6283'}

def main(available=False):
    global SOURCES
    rows=read(HERE/'derived/source_per_task.json'); by={(r['source'],r['record_id']):r for r in rows}
    incomplete=[src for src in SOURCES if any(r['status']=='pending' for r in rows if r['source']==src)]
    if not available:assert not incomplete,('unfinished sources',incomplete)
    SOURCES=[src for src in SOURCES if src not in incomplete]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8.5,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none'})
    fig=plt.figure(figsize=(7.3,5.4));grid=fig.add_gridspec(2,2,height_ratios=[1,1.1],hspace=.64,wspace=.35,left=.105,right=.98,top=.94,bottom=.17)
    ax=fig.add_subplot(grid[0,:]);data=np.array([[sum(by[src,f'NET_{scale}{n:02d}_{c}']['quality'] for n in range(1,5)) for scale in 'SML' for c in 'ABC'] for src in SOURCES])
    cmap=LinearSegmentedColormap.from_list('coverage',['#f4f4f1','#aac4d5','#244f75']);ax.imshow(data,vmin=0,vmax=4,cmap=cmap,aspect='auto')
    for i in range(len(SOURCES)):
        for j in range(9): ax.text(j,i,f'{data[i,j]}/4',ha='center',va='center',color='white' if data[i,j]>=3 else '#25323b')
    names={'G':'Greedy G','R4':'Local R4','deepseek':'DeepSeek','luna':'Luna'}
    ax.set_xticks(range(9),[f'{s}\n{c}' for s in 'SML' for c in 'ABC']);ax.set_yticks(range(len(SOURCES)),[names[s] for s in SOURCES])
    ax.tick_params(length=0);ax.set_title('(a) Reference quality by scale and resource condition',loc='left',pad=12,fontweight='bold',fontsize=9.3)
    for x in (2.5,5.5):ax.axvline(x,color='white',lw=2)
    ax.spines['left'].set_visible(False);ax.spines['bottom'].set_visible(False)
    bx=fig.add_subplot(grid[1,0]);nets=[f'NET_{s}{i:02d}' for s in 'SML' for i in range(1,5)]; offsets=np.linspace(-.24,.24,len(SOURCES))
    points=[]
    for src,off in zip(SOURCES,offsets):
        xx=[];yy=[]
        for i,net in enumerate(nets):
            r=by[src,net+'_C']; points.append(dict(network_id=net,source=src,admissible=r['admissible'],extra_total_fraction=r['extra_total_fraction']))
            if r['admissible']:xx.append(i+off);yy.append(100*r['extra_total_fraction'])
            else:bx.plot(i+off,-2,marker='x',color=COLORS[src],ms=5)
        bx.plot(xx,yy,linestyle='none',marker={'G':'o','R4':'s','deepseek':'^','luna':'D'}[src],color=COLORS[src],ms=4,label={'G':'G','R4':'R4','deepseek':'DeepSeek','luna':'Luna'}[src])
    has_invalid=any(not by[src,net+'_C']['admissible'] for src in SOURCES for net in nets)
    bx.axhline(0,color='#aaaaaa',lw=.6);bx.set_xticks(range(12),[f'{s}{i}' for s in 'SML' for i in range(1,5)],rotation=55,ha='right');bx.set_xlim(-.65,11.65)
    bx.set_ylabel('Additional holds / missions (%)');bx.set_ylim(bottom=-3.5 if has_invalid else -.8);bx.grid(axis='y',color='#ececec',lw=.5);bx.set_title('(b) Service loss within each C network',loc='left',fontweight='bold',fontsize=9.3,pad=29)
    bx.legend(ncol=len(SOURCES),frameon=False,fontsize=7.7,loc='lower left',bbox_to_anchor=(0.,1.01));bx.text(.02,-.37,'×: no admissible candidate; service loss undefined' if has_invalid else 'Each point represents one paired base network.',transform=bx.transAxes,fontsize=6.8)
    cx=fig.add_subplot(grid[1,1]);record=next(r for r in read(HERE/'evaluation/scores.json') if r['record_id']=='NET_L04_A' and r['source']=='deepseek')
    intervals=[r for r in record['score']['resource_intervals'] if r['kind']=='charger' and r['resource']=='V05' and r['mission_id'] in ['M015','M024']]
    export=[]
    for y,mid in zip([1,0],['M015','M024']):
        r=next(r for r in intervals if r['mission_id']==mid);s=r['start_min'];e=r['end_min'];rs=np.floor(s);re=np.ceil(e)
        cx.barh(y,re-rs,left=rs,height=.56,color='#eef0f2',edgecolor='#adb5bc',hatch='///',lw=.6)
        cx.barh(y,e-s,left=s,height=.26,color='#355f88',zorder=3)
        export.append(dict(mission_id=mid,actual_start_min=s,actual_end_min=e,reserved_start_min=rs,reserved_end_min=re))
    cx.axvspan(52,53,color='#bd8732',alpha=.26,zorder=2);cx.axvline(52,color='#bd8732',lw=.6);cx.axvline(53,color='#bd8732',lw=.6)
    cx.set_yticks([1,0],['U04 / M015','U06 / M024']);cx.set_ylim(-.5,1.9);cx.set_xlim(41,65);cx.set_xticks([42,47,52,57,62]);cx.set_xlabel('Actual time (min)');cx.set_title('(c) Charger reservation conflict: L04-A',loc='left',fontweight='bold',fontsize=9.3,pad=12)
    cx.text(52.5,1.6,'[52,53)\n2 reservations / 1 charger',ha='center',va='center',fontsize=7.5)
    cx.text(.02,-.37,'Solid: actual charging; hatched: reserved windows',transform=cx.transAxes,fontsize=6.8)
    out=HERE/'figures';out.mkdir(exist_ok=True)
    for ext in ('pdf','svg','png'):fig.savefig(out/f'network_results.{ext}',dpi=200)
    csvout(HERE/'derived/figure_C_service_points.csv',points);csvout(HERE/'derived/figure_charger_intervals.csv',export)
    print(out/'network_results.pdf')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--available',action='store_true');a=p.parse_args();main(a.available)
