"""Plot an EyeRecord (matplotlib only, no GUI toolkit): used by the GUI canvas and by the PNG exporter."""
from __future__ import annotations

import numpy as np

from .detect import MARKER_NAMES
from .esx import display_curve

# marker colours cycle red/blue/green like the original tool
_COLORS = ["#d62728", "#1f77b4", "#2ca02c"]
VIEWS = ("full", "anterior", "lens", "posterior")
Y_MODES = ("display", "linear")
SHORT = ["Cornea/Aq", "Aq/LensBase", "Aq/Capsule", "Caps/Cortex", "Cortex/Nuc", "Choroid", "Sclera", "Nuc/Cortex",
         "Cortex/Caps", "Caps/Vitr", "Lens/VitrBase", "Retina", "RPE"]
STATUS_COLOR = {"auto": "#555555", "edited": "#b8860b", "confirmed": "#2e7d32"}


def marker_color(i: int) -> str:
    return _COLORS[i % 3]


def view_range(rec, view: str) -> tuple[float, float]:
    n = len(rec.avg)
    x = rec.x
    ok = lambda i: not np.isnan(x[i])
    if view == "anterior" and ok(0) and ok(10):
        return max(0, x[0] - 600), min(n, x[10] + 1500)
    if view == "lens" and ok(1) and ok(10):
        return max(0, x[1] - 400), min(n, x[10] + 400)
    if view == "posterior" and ok(9):
        hi = np.nanmax(x[[5, 6, 12]]) if not np.isnan(x[[5, 6, 12]]).all() else x[9] + 8000
        return max(0, x[9] + 1500), min(n, hi + 1200)
    return 0, min(n, (np.nanmax(x) + 2500) if not np.isnan(x).all() else 21000)


def y_curve(rec, y_mode: str) -> np.ndarray:
    return display_curve(rec.avg) if y_mode == "display" else rec.avg


def draw_eye(ax, rec, view: str = "full", y_mode: str = "display", show_cursors: bool = False,
             selected: int | None = None, show_conf: bool = True, limits=None) -> None:
    """(Re)draw everything on ax. Marker lines carry gid='marker:<i>' so the GUI can hit-test them."""
    ax.clear()
    y = y_curve(rec, y_mode)
    lo, hi = view_range(rec, view)
    ax.plot(np.arange(len(y)), y, color="black", lw=0.7)
    ax.set_xlim(lo, hi)
    seg = y[int(lo):int(hi) + 1]
    top = float(np.nanmax(seg)) if len(seg) else 1.0
    ax.set_ylim(-0.04 * top, 1.18 * top)
    if limits is not None:                       # keep the user's zoom/pan between redraws
        ax.set_xlim(limits[0])
        ax.set_ylim(limits[1])
        lo, hi = limits[0]
    for i in range(13):
        v = rec.x[i]
        if np.isnan(v):
            continue
        c = marker_color(i)
        low = show_conf and rec.detection.conf[i] < 0.5 and rec.status == "auto"
        line = ax.axvline(v, color=c, lw=2.2 if i == selected else 1.1, ls="--" if low else "-", alpha=0.95, gid=f"marker:{i}")
        line.set_picker(False)
        if lo <= v <= hi:
            ax.text(v, ax.get_ylim()[1] * 0.985, f"{i + 1} {SHORT[i]}", rotation=90, va="top", ha="right", fontsize=7,
                    color=c, fontweight="bold" if i == selected else "normal")
            ax.plot([v], [y[int(v)]], "o", ms=4, color=c)
    if show_cursors:
        for k, pos in rec.cursors.items():
            if lo <= pos <= hi:
                ax.plot([pos], [0], "^", color="orange", ms=7, mec="k", mew=0.5)
                ax.text(pos, -0.03 * top, f"dev{k}", fontsize=6, color="darkorange", ha="center", va="top")
    ax.set_xlabel("sample index (Lenstar A-scan)")
    ax.set_ylabel("display: max(0,log2 I)^1.5" if y_mode == "display" else "mean intensity (linear)")
    flags = (" | flags: " + ",".join(rec.flags)) if rec.flags else ""
    ax.set_title(f"{rec.subject_label}  {rec.eye}  {rec.exam_ts}  scans={rec.n_scans}  [{rec.status}]{flags}", fontsize=8,
                 color=STATUS_COLOR[rec.status])
    ax.margins(x=0)


def save_png(rec, path: str, view: str = "full", y_mode: str = "display", dpi: int = 110) -> None:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(12, 4.5))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_eye(ax, rec, view, y_mode, show_cursors=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
