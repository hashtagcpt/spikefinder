"""Portable review window (Tkinter + matplotlib; runs on Windows, macOS and Linux).

Open .esx files -> landmarks are marked automatically -> a person checks/corrects them:
  drag a marker line, arrow keys nudge the selected marker, Delete removes it, 'i' then click places a missing one,
  'c' confirms the eye, 'r' resets it to the automatic result, 'n'/'p' next/previous eye, 'f' next eye that needs review.
Edits are auto-saved to review JSON files in the output folder; CSV/PNG export from the File menu.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .detect import MARKER_NAMES, Profile, list_profiles, load_profile
from .export import write_exe_csv, write_tidy_csv
from .render import VIEWS, Y_MODES, draw_eye, save_png
from .session import EyeRecord, apply_review, process_file, save_review

LIMITATIONS = (
    "Validated on chick eyes only (Lenstar LS900 labels 2015-2020). Human or unknown subjects are NOT validated: "
    "every marker must be checked.\n\n"
    "Reasonably reliable (peak-like): Cornea/Aqueous, Aqueous/Capsule, Capsule/Vitreous, RPE, Choroid, Sclera.\n"
    "Not placed automatically: lens-interior markers (Capsule/Cortex, Cortex/Nucleus, Nucleus/Cortex, Cortex/Capsule). "
    "Rough estimates: the two lens baselines. Retina depends on labelling convention.\n\n"
    "Dashed lines = low-confidence automatic markers. Eyes marked * need review, but an unflagged eye is NOT a checked eye "
    "(about 1 eye in 4 has a peak marker >25 samples off, and the flags catch only a minority of those). "
    "Nothing is final until a person confirms it."
)
SHORTCUTS = ("n / p: next / previous eye     f: next eye needing review\n"
             "c: confirm eye      r: reset to automatic      s: save\n"
             "[ ]: select previous / next marker     Left/Right: nudge 1 sample (Shift = 10)\n"
             "Delete: remove marker     i: place selected (missing) marker at next click\n"
             "Toolbar zoom/pan disables dragging; use the Reset-view button of the toolbar (home).")


class App(tk.Tk):
    def __init__(self, paths: list[str] | None = None, outdir: str | None = None, profile: str | None = None):
        super().__init__()
        self.title(f"SpikeFinder {__version__} - Lenstar landmark review")
        self.geometry("1380x800")
        self.records: list[EyeRecord] = []
        self.idx = -1
        self.sel: int | None = None
        self.armed: int | None = None
        self.drag: int | None = None
        self.outdir = outdir or os.path.join(os.path.expanduser("~"), "SpikeFinder", "review")
        self.profile: Profile = load_profile(profile)
        self.q: queue.Queue = queue.Queue()
        self.loading = 0
        self.view = tk.StringVar(value="full")
        self.ymode = tk.StringVar(value="display")
        self.show_cursors = tk.BooleanVar(value=False)
        self.snap = tk.BooleanVar(value=True)
        self.reviewer = tk.StringVar(value=os.environ.get("USERNAME") or os.environ.get("USER") or "")
        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        if paths:
            self.after(200, lambda: self.open_paths(paths))

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Open .esx files...", command=self.menu_open_files, accelerator="Ctrl+O")
        f.add_command(label="Open folder...", command=self.menu_open_folder)
        f.add_command(label="Output folder...", command=self.menu_outdir)
        f.add_separator()
        f.add_command(label="Save review", command=self.save, accelerator="Ctrl+S")
        f.add_command(label="Export table (CSV)...", command=lambda: self.export("tidy"))
        f.add_command(label="Export SpikeFinder-format CSV...", command=lambda: self.export("exe"))
        f.add_command(label="Export PNGs...", command=self.export_png)
        f.add_separator()
        f.add_command(label="Quit", command=self._quit)
        m.add_cascade(label="File", menu=f)
        v = tk.Menu(m, tearoff=0)
        for name in VIEWS:
            v.add_radiobutton(label=f"View: {name}", variable=self.view, value=name, command=lambda: self.redraw(reset=True))
        v.add_separator()
        for name in Y_MODES:
            v.add_radiobutton(label=f"Y axis: {name}", variable=self.ymode, value=name, command=lambda: self.redraw(reset=True))
        v.add_separator()
        v.add_checkbutton(label="Show Lenstar device cursors", variable=self.show_cursors, command=self.redraw)
        v.add_checkbutton(label="Snap dragged markers to local peak", variable=self.snap)
        pm = tk.Menu(v, tearoff=0)
        for name in list_profiles() or ["uncalibrated"]:
            pm.add_command(label=name, command=lambda n=name: self.set_profile(n))
        v.add_cascade(label="Detector profile (applies to newly opened files)", menu=pm)
        m.add_cascade(label="View", menu=v)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Limitations", command=lambda: messagebox.showinfo("Limitations", LIMITATIONS))
        h.add_command(label="Shortcuts", command=lambda: messagebox.showinfo("Shortcuts", SHORTCUTS))
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"SpikeFinder {__version__}\nMIT licensed. Independent Python reimplementation for Lenstar .esx files."))
        m.add_cascade(label="Help", menu=h)
        self.config(menu=m)

        self.banner = tk.Label(self, text="", fg="white", bg="#b00020", anchor="w", padx=8)
        self.banner.pack(fill="x")
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)
        self.pw = pw
        self.banner.pack_forget()                      # shown by redraw() only when there is something to say

        left = ttk.Frame(pw)
        self.tree = ttk.Treeview(left, columns=("subject", "eye", "date", "status", "flags"), show="headings", height=30)
        for c, w in (("subject", 80), ("eye", 35), ("date", 90), ("status", 70), ("flags", 120)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.tag_configure("review", background="#fff3cd")
        self.tree.tag_configure("confirmed", background="#d4edda")
        self.tree.tag_configure("edited", background="#e2e3f5")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree)
        pw.add(left, weight=1)

        mid = ttk.Frame(pw)
        self.fig = Figure(figsize=(8, 5))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=mid)
        self.toolbar = NavigationToolbar2Tk(self.canvas, mid)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("button_press_event", self._press)
        self.canvas.mpl_connect("motion_notify_event", self._motion)
        self.canvas.mpl_connect("button_release_event", self._release)
        pw.add(mid, weight=5)

        right = ttk.Frame(pw)
        self.mtree = ttk.Treeview(right, columns=("n", "marker", "x", "conf"), show="headings", height=14, selectmode="browse")
        for c, t, w in (("n", "#", 28), ("marker", "Marker", 140), ("x", "Sample", 60), ("conf", "Conf", 45)):
            self.mtree.heading(c, text=t)
            self.mtree.column(c, width=w, anchor="w")
        self.mtree.pack(fill="x")
        self.mtree.bind("<<TreeviewSelect>>", self._on_marker_row)
        bf = ttk.Frame(right)
        bf.pack(fill="x", pady=6)
        for text, cmd in (("Confirm eye (c)", self.confirm), ("Reset to auto (r)", self.reset),
                          ("Remove marker (Del)", self.remove_marker), ("Place marker (i)", self.arm_place),
                          ("Next needing review (f)", self.next_flagged)):
            ttk.Button(bf, text=text, command=cmd).pack(fill="x", pady=1)
        ttk.Checkbutton(right, text="Snap dragged markers to peak", variable=self.snap).pack(anchor="w")
        ttk.Label(right, text="Reviewer").pack(anchor="w", pady=(8, 0))
        ttk.Entry(right, textvariable=self.reviewer).pack(fill="x")
        ttk.Label(right, text="Notes").pack(anchor="w", pady=(8, 0))
        self.notes = tk.Text(right, height=5, width=28)
        self.notes.pack(fill="x")
        self.notes.bind("<FocusOut>", lambda e: self._store_notes())
        self.info = tk.Label(right, text="", justify="left", anchor="nw", wraplength=250, fg="#333")
        self.info.pack(fill="x", pady=8)
        pw.add(right, weight=1)

        self.status = tk.Label(self, text="Open .esx files (File > Open) to begin.", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

        for key, fn in (("n", self.next), ("p", self.prev), ("f", self.next_flagged), ("c", self.confirm), ("r", self.reset),
                        ("s", self.save), ("i", self.arm_place), ("<Delete>", self.remove_marker),
                        ("bracketright", lambda: self._select_rel(1)), ("bracketleft", lambda: self._select_rel(-1))):
            self.bind_all(f"<{key}>" if not key.startswith("<") else key, lambda e, fn=fn: self._key(fn, e))
        self.bind_all("<Left>", lambda e: self._nudge(-1, e))
        self.bind_all("<Right>", lambda e: self._nudge(1, e))
        self.bind_all("<Control-o>", lambda e: self.menu_open_files())
        self.bind_all("<Control-s>", lambda e: self.save())

    # ------------------------------------------------------------ loading
    def menu_open_files(self) -> None:
        ps = filedialog.askopenfilenames(title="Open Lenstar .esx files", filetypes=[("EyeSuite export", "*.esx"), ("All", "*.*")])
        if ps:
            self.open_paths(list(ps))

    def menu_open_folder(self) -> None:
        d = filedialog.askdirectory(title="Folder containing .esx files")
        if d:
            self.open_paths([d])

    def menu_outdir(self) -> None:
        d = filedialog.askdirectory(title="Output folder for review files", initialdir=self.outdir)
        if d:
            self.outdir = d
            self.set_status(f"Output folder: {d}")

    def set_profile(self, name: str) -> None:
        self.profile = load_profile(name)
        self.set_status(f"Detector profile: {name} (applies to files opened from now on)")

    def open_paths(self, paths: list[str]) -> None:
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith(".esx")]
            elif p.lower().endswith(".esx") or os.path.isfile(p):
                files.append(p)
        if not files:
            messagebox.showwarning("No files", "No .esx files found.")
            return
        have = {r.source for r in self.records}
        files = [f for f in files if f not in have]
        self.loading += 1
        threading.Thread(target=self._worker, args=(files, self.profile, self.outdir), daemon=True).start()

    def _worker(self, files, profile, outdir) -> None:
        for i, f in enumerate(files):
            name = os.path.basename(f)
            try:
                recs = process_file(f, profile, progress=lambda fr, i=i, n=name: self.q.put(("prog", f"Loading {n} ({i + 1}/{len(files)}) {fr * 100:.0f}%")))
                apply_review(recs, outdir)
                for r in recs:
                    self.q.put(("rec", r))
            except Exception as e:                     # noqa: BLE001 - show any parse failure, keep going
                self.q.put(("err", f"{name}: {e}"))
        self.q.put(("done", len(files)))

    def _poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "prog":
                    self.set_status(val)
                elif kind == "rec":
                    self.records.append(val)
                    self._add_row(len(self.records) - 1)
                    if self.idx < 0:
                        self.select(0)
                elif kind == "err":
                    messagebox.showerror("Could not read file", val)
                elif kind == "done":
                    self.loading -= 1
                    nrev = sum(r.needs_review for r in self.records)
                    self.set_status(f"{len(self.records)} eyes loaded; {nrev} need review.")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ------------------------------------------------------------ list / selection
    def _row_values(self, r: EyeRecord):
        return (r.subject_label, r.eye, r.exam_ts[:10], r.status + ("*" if r.needs_review else ""), ",".join(r.flags)[:30])

    def _row_tag(self, r: EyeRecord):
        return ("confirmed",) if r.status == "confirmed" else ("edited",) if r.status == "edited" else ("review",) if r.needs_review else ()

    def _add_row(self, i: int) -> None:
        r = self.records[i]
        self.tree.insert("", "end", iid=str(i), values=self._row_values(r), tags=self._row_tag(r))

    def _refresh_row(self, i: int) -> None:
        r = self.records[i]
        self.tree.item(str(i), values=self._row_values(r), tags=self._row_tag(r))

    @property
    def rec(self) -> EyeRecord | None:
        return self.records[self.idx] if 0 <= self.idx < len(self.records) else None

    def _on_tree(self, _e=None) -> None:
        s = self.tree.selection()
        if s and int(s[0]) != self.idx:
            self.select(int(s[0]), from_tree=True)

    def select(self, i: int, from_tree: bool = False) -> None:
        self._store_notes()
        if self.idx >= 0:
            self._autosave()
        self.idx, self.sel, self.armed = i, None, None
        if not from_tree:
            self.tree.selection_set(str(i))
            self.tree.see(str(i))
        r = self.rec
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", r.notes)
        self.redraw(reset=True)

    def next(self) -> None:
        if self.records:
            self.select(min(self.idx + 1, len(self.records) - 1))

    def prev(self) -> None:
        if self.records:
            self.select(max(self.idx - 1, 0))

    def next_flagged(self) -> None:
        n = len(self.records)
        for k in range(1, n + 1):
            j = (self.idx + k) % n
            if self.records[j].needs_review:
                return self.select(j)
        self.set_status("No eye needs review.")

    # ------------------------------------------------------------ drawing
    def redraw(self, reset: bool = False) -> None:
        r = self.rec
        if r is None:
            return
        limits = None if reset else (self.ax.get_xlim(), self.ax.get_ylim())
        draw_eye(self.ax, r, self.view.get(), self.ymode.get(), self.show_cursors.get(), self.sel, limits=limits)
        self.canvas.draw_idle()
        self._fill_markers()
        if r.hint != "animal_likely":
            who = "HUMAN-LIKELY" if r.hint == "human_likely" else "UNKNOWN"
            self.banner.config(text=f"  Subject looks {who}: detector is NOT validated for this - check EVERY marker. Identifiers are hidden.")
            self.banner.pack(fill="x", before=self.pw)
        elif r.flags:
            self.banner.config(text="  QC flags: " + ", ".join(r.flags), bg="#b06000")
            self.banner.pack(fill="x", before=self.pw)
        else:
            self.banner.pack_forget()
        if r.hint != "animal_likely":
            self.banner.config(bg="#b00020")
        self.info.config(text=f"{os.path.basename(r.source)}\nprofile: {r.detection.profile}\nstatus: {r.status}"
                              + (f"\nreviewed: {r.reviewed_at}" if r.reviewed_at else ""))

    def _fill_markers(self) -> None:
        r = self.rec
        self.mtree.delete(*self.mtree.get_children())
        for i, n in enumerate(MARKER_NAMES):
            v = r.x[i]
            self.mtree.insert("", "end", iid=str(i), values=(i + 1, n, "-" if np.isnan(v) else int(v), f"{r.detection.conf[i]:.2f}"))
        if self.sel is not None:
            self.mtree.selection_set(str(self.sel))

    def _on_marker_row(self, _e=None) -> None:
        s = self.mtree.selection()
        if s and int(s[0]) != self.sel:
            self.sel = int(s[0])
            self.redraw()

    def _select_rel(self, d: int) -> None:
        self.sel = 0 if self.sel is None else (self.sel + d) % 13
        self.redraw()

    # ------------------------------------------------------------ mouse editing
    def _marker_at(self, event) -> int | None:
        r = self.rec
        if r is None or event.inaxes is not self.ax:
            return None
        best, bd = None, 8.0
        for i in range(13):
            if np.isnan(r.x[i]):
                continue
            px = self.ax.transData.transform((r.x[i], 0))[0]
            d = abs(px - event.x)
            if d < bd:
                best, bd = i, d
        return best

    def _snap(self, x: float) -> float:
        r = self.rec
        if not self.snap.get():
            return x
        lo, hi = int(max(0, x - 15)), int(min(len(r.avg) - 1, x + 15))
        return lo + int(np.argmax(r.avg[lo:hi + 1]))

    def _press(self, e) -> None:
        r = self.rec
        if r is None or getattr(self.toolbar, "mode", "") or e.button != 1 or e.xdata is None:
            return
        if self.armed is not None:
            r.set_marker(self.armed, self._snap(e.xdata))
            self.sel, self.armed = self.armed, None
            self._after_edit()
            return
        i = self._marker_at(e)
        if i is not None:
            self.drag, self.sel = i, i
            self.redraw()

    def _motion(self, e) -> None:
        r = self.rec
        if self.drag is None or r is None or e.xdata is None:
            return
        r.x[self.drag] = float(np.clip(round(e.xdata), 0, len(r.avg) - 1))
        self.redraw()

    def _release(self, e) -> None:
        r = self.rec
        if self.drag is None or r is None:
            return
        i, self.drag = self.drag, None
        if e.xdata is not None:
            r.set_marker(i, self._snap(e.xdata))
        self._after_edit()

    # ------------------------------------------------------------ actions
    def _key(self, fn, event) -> None:
        if isinstance(event.widget, (tk.Text, tk.Entry, ttk.Entry)):
            return
        fn()

    def _nudge(self, d: int, event) -> None:
        if isinstance(event.widget, (tk.Text, tk.Entry, ttk.Entry)) or self.rec is None or self.sel is None:
            return
        step = 10 if (event.state & 0x1) else 1
        v = self.rec.x[self.sel]
        if not np.isnan(v):
            self.rec.set_marker(self.sel, v + d * step)
            self._after_edit()

    def _after_edit(self) -> None:
        self._refresh_row(self.idx)
        self.redraw()

    def confirm(self) -> None:
        r = self.rec
        if r:
            self._store_notes()
            r.confirm(self.reviewer.get().strip())
            self._after_edit()
            self._autosave()
            self.set_status(f"Confirmed {r.subject_label} {r.eye}.")

    def reset(self) -> None:
        r = self.rec
        if r:
            r.reset()
            self._after_edit()

    def remove_marker(self) -> None:
        r = self.rec
        if r and self.sel is not None:
            r.set_marker(self.sel, None)
            self._after_edit()

    def arm_place(self) -> None:
        if self.rec is None or self.sel is None:
            self.set_status("Select a marker in the table first, then press i and click the plot.")
            return
        self.armed = self.sel
        self.set_status(f"Click on the plot to place '{MARKER_NAMES[self.sel]}'.")

    def _store_notes(self) -> None:
        r = self.rec
        if r is not None:
            t = self.notes.get("1.0", "end").strip()
            if t != r.notes:
                r.notes = t

    def _autosave(self) -> None:
        try:
            save_review(self.records, self.outdir, only_reviewed=True)
        except OSError as e:
            self.set_status(f"Could not save review: {e}")

    def save(self) -> None:
        self._store_notes()
        try:
            paths = save_review(self.records, self.outdir, only_reviewed=False)
            self.set_status(f"Saved {len(paths)} review file(s) to {self.outdir}")
        except OSError as e:
            messagebox.showerror("Save failed", str(e))

    def export(self, kind: str) -> None:
        if not self.records:
            return
        self._store_notes()
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                         initialfile="spikefinder_markers.csv" if kind == "tidy" else "spike_finder_export.csv")
        if not p:
            return
        if kind == "tidy":
            write_tidy_csv(self.records, p)
            self.set_status(f"Wrote {p}")
        else:
            n = write_exe_csv(self.records, p)
            self.set_status(f"Wrote {n} eyes (those with all required markers) to {p}")

    def export_png(self) -> None:
        d = filedialog.askdirectory(title="Folder for PNG images")
        if not d:
            return
        for r in self.records:
            fn = f"{r.subject_key}_{r.eye}_{r.exam_ts[:10].replace('.', '')}_{r.exam_ts[11:19].replace(':', '')}.png"
            save_png(r, os.path.join(d, fn), self.view.get(), self.ymode.get())
        self.set_status(f"Wrote {len(self.records)} PNGs to {d}")

    def set_status(self, text: str) -> None:
        self.status.config(text=text)

    def _quit(self) -> None:
        self._store_notes()
        self._autosave()
        self.destroy()


def run(paths: list[str] | None = None, outdir: str | None = None, profile: str | None = None) -> None:
    App(paths, outdir, profile).mainloop()
