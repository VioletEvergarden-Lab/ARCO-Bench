"""Draw L04-A shared charging reservations from the saved event ledger."""
from pathlib import Path
import json,csv,math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from paper_style_otf import configure
configure()
from matplotlib.patches import Patch
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/charger_reservation_events.json'


def main():
    if not DATA.exists():raise FileNotFoundError(DATA)
    d=json.loads(DATA.read_text(encoding='utf8'))
    plt.rcParams.update({'font.family':'serif','font.serif':['Latin Modern Roman'],'font.size':11,
                        'pdf.fonttype':42,'svg.fonttype':'path','axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(7.2,2.8))
    fig.subplots_adjust(left=.17,right=.97,bottom=.23,top=.75)
    blue='#315e85';gold='#c78b39'
    for y,r in zip([1,0],d['events']):
        ax.barh(y,r['reserved_end']-r['reserved_start'],left=r['reserved_start'],height=.48,
                facecolor='#f3f4f5',edgecolor='#9ba6af',hatch='////',linewidth=.65)
        ax.barh(y,r['end']-r['start'],left=r['start'],height=.19,color=blue,zorder=3)
    ax.axvspan(52,53,facecolor=gold,alpha=.25,zorder=2)
    ax.set(yticks=[1,0],yticklabels=['U04 / M015','U06 / M024'],ylim=(-.55,2.0),
           xlim=(41.5,64),xticks=[42,47,52,53,57,62],xlabel='Time (min)')
    ax.text(52.5,1.53,'Shared reservation [52, 53)\n2 users / capacity 1',ha='center',va='center',fontsize=10.5)
    ax.tick_params(axis='y',length=0)
    fig.legend(handles=[Patch(facecolor=blue,label='Actual charging'),
                       Patch(facecolor='#f3f4f5',edgecolor='#9ba6af',hatch='////',label='Reserved one-minute windows')],
               frameon=False,ncol=2,loc='upper center',bbox_to_anchor=(.57,.98),fontsize=10.5)
    for ext in ['pdf','svg','png']:fig.savefig(ROOT/'generated'/f'charger_reservation_case.{ext}',dpi=220)
    plt.close(fig)

if __name__=='__main__':main()
