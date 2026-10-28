"""Redraw saved-data figures without optimization, model calls or source-file writes."""
from pathlib import Path
import argparse,importlib.util,subprocess,sys
ROOT=Path(__file__).resolve().parent
SCRIPTS=['draw_paired_references.py','draw_m01b.py','draw_route_energy.py','draw_reservation.py','draw_availability.py','draw_core_construction.py']
def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--only',choices=['all','paired','m01b','route-energy','reservation','availability','core-construction','adds'],default='all')
 a=parser.parse_args();(ROOT/'generated').mkdir(exist_ok=True)
 mapping=dict(zip(['paired','m01b','route-energy','reservation','availability','core-construction'],SCRIPTS))
 for key,name in mapping.items():
  if a.only in ('all',key):subprocess.run([sys.executable,'-B',str(ROOT/'scripts'/name)],check=True,cwd=ROOT)
 if a.only in ('all','adds'):
  path=ROOT.parent/'studies/arco_adds_external_20261024/scripts/draw_figures.py'
  spec=importlib.util.spec_from_file_location('adds_figure_source',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  def save(fig,name):
   for ext in ('pdf','svg','png'):fig.savefig(ROOT/'generated'/f'{name}.{ext}',dpi=180,bbox_inches='tight',facecolor='white')
   mod.plt.close(fig)
  mod.save=save
  mod.spatial();mod.events()
if __name__=='__main__':main()
