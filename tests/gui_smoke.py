"""Manual smoke test for the Tk GUI (needs a display):  python tests/gui_smoke.py path/to/file.esx"""
import os, sys, tempfile
from spikefinder.gui import App

path = sys.argv[1]
out = tempfile.mkdtemp()
app = App([path], outdir=out)
steps = []

def step():
    if app.loading or not app.records:
        app.after(300, step); return
    r = app.rec
    steps.append(f"loaded {len(app.records)} eyes, first status={r.status}")
    app.sel = 12                       # RPE
    before = r.x[12]
    app._nudge(1, type("E", (), {"widget": app, "state": 0})())
    steps.append(f"nudge RPE {before:.0f}->{r.x[12]:.0f} status={r.status}")
    app.sel = 0; app.remove_marker(); steps.append(f"removed cornea -> nan={r.x[0] != r.x[0]}")
    app.sel = 0; app.arm_place()
    class Ev:  # fake click at sample 1250
        button = 1; xdata = 1250.0; inaxes = app.ax; x = 0
    app.toolbar.mode = ""
    app._press(Ev); steps.append(f"placed cornea at {r.x[0]:.0f}")
    app.view.set("lens"); app.redraw(reset=True)
    app.next(); app.prev()
    app.confirm(); steps.append(f"confirmed status={r.status}")
    app.save(); steps.append("saved: " + ", ".join(os.listdir(out)))
    app.show_cursors.set(True); app.ymode.set("linear"); app.redraw(reset=True)
    print("\n".join(steps)); print("GUI SMOKE OK")
    app._quit()

app.after(500, step)
app.mainloop()
