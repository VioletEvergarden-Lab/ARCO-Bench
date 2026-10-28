"""Draw original-network and paired-network availability from saved timestamps."""
from pathlib import Path
import argparse, csv, datetime as dt, json, statistics
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from paper_style_otf import configure
configure()
from matplotlib.lines import Line2D
BASE=Path(__file__).resolve().parents[1]
CUTS=(30,60,180,300,600)
MAIN=('Full-MILP','Iter-R4','deepseek','luna')
OLD=('G','R4','Iter-R4','R_frac','Full-MILP')
STYLE={'Full-MILP':('#355f88','-','o','Full-MILP'),
 'Iter-R4':('#8b6283',':','D',r'Iterative $R_4$'),
 'deepseek':('#b98231','-.','^','DeepSeek'),'luna':('#337d79','--','s','Luna'),
 'G':('#777777','--','s',r'$G$'),'R4':('#b98231','-.','^',r'Single-pass $R_4$'),
 'R_frac':('#6f7d47',(0,(4,1,1,1)),'v',r'$R_{\mathrm{frac}}$')}
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def yes(x):return x is True or x=='True'
def number(x):return float(x) if x not in ('',None) else None
def count(data,method,field,cut):return sum(r['method']==method and r[field] is not None and r[field]<=cut for r in data)



def setup():
 plt.rcParams.update({'font.family':'Latin Modern Roman','font.size':12,'mathtext.fontset':'custom',
  'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'axes.labelcolor':'#272c31','text.color':'#272c31',
  'xtick.color':'#272c31','ytick.color':'#272c31','pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'path',
  'savefig.facecolor':'white','lines.linewidth':1.9})
def stairs(ax,data,method,field):
 color,line,marker,label=STYLE[method]
 values=sorted(r[field] for r in data if r['method']==method and r[field] is not None and r[field]<=600)
 ax.step([0]+values+[600],[0]+list(range(1,len(values)+1))+[len(values)],where='post',color=color,linestyle=line,label=label,zorder=3)
 ax.scatter(CUTS,[count(data,method,field,b) for b in CUTS],s=30,marker=marker,facecolor='white',edgecolor=color,linewidths=1.1,zorder=5,clip_on=False)
 return len(values)
def axes(ax,n):
 ax.set_xlim(0,630);ax.set_ylim(0,n+1.2)
 ax.set_xticks([0,*CUTS]);ax.set_yticks(range(0,n+1,4 if n==24 else 6))
 ax.set_axisbelow(True);ax.grid(axis='y',color='#e4e5e6',linewidth=.65)
 for b in CUTS:ax.axvline(b,color='#eeeeee',linewidth=.65,zorder=0)
 ax.tick_params(length=3,pad=4);ax.set_xlabel('Time to verified plan (s)')
def save(fig,name):
 out=BASE/'generated';out.mkdir(exist_ok=True)
 for suffix in ('pdf','svg','png'):fig.savefig(out/f'{name}.{suffix}',dpi=240,bbox_inches='tight',pad_inches=.07)
 plt.close(fig)
def handles(methods):
 return [Line2D([0],[0],color=STYLE[m][0],ls=STYLE[m][1],marker=STYLE[m][2],mfc='white',markersize=5,label=STYLE[m][3]) for m in methods]
def draw(main,orig):
 setup();fig,ax=plt.subplots(figsize=(7.6,4.25));fig.subplots_adjust(left=.10,right=.98,bottom=.16,top=.84)
 axes(ax,24);ax.set_ylabel('Tasks at reference quality (out of 24)')
 for method in MAIN:
  n=stairs(ax,main,method,'first_quality_seconds');ax.text(609,n,str(n),color=STYLE[method][0],va='center',fontsize=12,fontweight='bold')
 fig.legend(handles=handles(MAIN),loc='upper center',bbox_to_anchor=(.535,.99),ncol=4,frameon=False,columnspacing=1.2,handlelength=2.4)
 save(fig,'paired_quality_availability')
 fig,axs=plt.subplots(2,1,figsize=(7.6,5.8),sharex=True);fig.subplots_adjust(left=.10,right=.98,bottom=.11,top=.83,hspace=.28)
 for ax,field,title in zip(axs,['first_service_seconds','first_quality_seconds'],['(a) Optimal urgent and total service','(b) Reference quality']):
  axes(ax,36);ax.set_title(title,loc='left',fontsize=12,pad=7);ax.set_ylabel('Tasks (out of 36)')
  for method in OLD:stairs(ax,orig,method,field)
  ax.set_xlabel('')
 axs[-1].set_xlabel('Time to verified plan (s)')
 fig.legend(handles=handles(OLD),loc='upper center',bbox_to_anchor=(.535,.99),ncol=3,frameon=False,columnspacing=1.8,handlelength=2.5)
 save(fig,'original_search_progress')
def load_chart_data(name):
 data=rows(BASE/'data'/name)
 for r in data:
  for k in ('first_service_seconds','first_quality_seconds','proof_seconds','termination_seconds'):r[k]=number(r[k])
  for k in ('final_reference_quality','admissible'):r[k]=yes(r[k])
 return data

if __name__=='__main__':
 draw(load_chart_data('availability_first_times.csv'),load_chart_data('availability_original_first_times.csv'))
