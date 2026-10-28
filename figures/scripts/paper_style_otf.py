"""Match the manuscript's lmodern text without a system font installation."""
from pathlib import Path
import matplotlib as mpl
from matplotlib import font_manager as fm
def configure():
    for path in (Path(__file__).resolve().parents[1] / "fonts").glob("*.otf"):
        fm.fontManager.addfont(path)
    mpl.rcParams.update({
        "font.family": "serif", "font.serif": ["Latin Modern Roman"],
        "mathtext.fontset": "custom", "mathtext.rm": "Latin Modern Roman",
        "mathtext.it": "Latin Modern Roman:style=italic",
        "mathtext.bf": "Latin Modern Roman:weight=bold",
        "mathtext.sf": "Latin Modern Roman", "mathtext.tt": "Latin Modern Roman",
        "mathtext.cal": "Latin Modern Roman", "mathtext.fallback": "cm",
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path",
    })
