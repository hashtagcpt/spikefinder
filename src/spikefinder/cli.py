"""Command line:  spikefinder [gui] [FILES/FOLDERS]      open the review window
                spikefinder run FILES/FOLDERS --out DIR  mark everything headlessly, write CSV/JSON (+PNG)
                spikefinder profiles                     list detector profiles
                spikefinder sample [FILE]                write a synthetic .esx to try the tool
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__

COMMANDS = {"gui", "run", "profiles", "sample"}


def collect_files(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith(".esx")]
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"warning: not found: {p}", file=sys.stderr)
    return files


def default_outdir() -> str:
    return os.path.join(os.path.expanduser("~"), "SpikeFinder", "review")


def cmd_run(a) -> int:
    from .detect import load_profile
    from .export import write_exe_csv, write_tidy_csv
    from .render import save_png
    from .session import apply_review, process_file, save_review

    files = collect_files(a.paths)
    if not files:
        print("no .esx files found", file=sys.stderr)
        return 2
    prof = load_profile(a.profile)
    out = a.out or default_outdir()
    os.makedirs(out, exist_ok=True)
    if a.show_identifiers:
        print("NOTE: --show-identifiers writes names to the screen only; files always use animal ids or hashes.")
    records = []
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {os.path.basename(f)}", flush=True)
        try:
            recs = process_file(f, prof, a.show_identifiers)
        except Exception as e:                       # noqa: BLE001 - keep going on a bad file
            print(f"   skipped: {e}", file=sys.stderr)
            continue
        if not a.fresh:
            apply_review(recs, out)                  # keep earlier human edits
        records += recs
    if not records:
        return 1
    save_review(records, out)
    tidy = os.path.join(out, "markers.csv")
    write_tidy_csv(records, tidy)
    print(f"wrote {tidy}")
    if a.exe_csv:
        p = os.path.join(out, "spike_finder_export.csv")
        print(f"wrote {p} ({write_exe_csv(records, p)} eyes, original SpikeFinder format)")
    if a.png:
        pd = os.path.join(out, "png")
        os.makedirs(pd, exist_ok=True)
        for r in records:
            save_png(r, os.path.join(pd, f"{r.subject_key}_{r.eye}_{r.exam_ts[:10].replace('.', '')}_{r.exam_ts[11:19].replace(':', '')}.png"))
        print(f"wrote {len(records)} PNGs to {pd}")
    nrev = sum(r.needs_review for r in records)
    nhum = sum(r.hint != "animal_likely" for r in records)
    print(f"{len(records)} eyes marked; {nrev} flagged for human review; {nhum} not recognised as animal (NOT validated).")
    print("Automatic marks are suggestions: open `spikefinder gui` on the same files to check them.")
    return 0


def cmd_gui(a) -> int:
    try:
        from .gui import run
        run(collect_files(a.paths) if a.paths else None, a.out, a.profile)
    except Exception as e:                           # noqa: BLE001
        import tkinter
        if isinstance(e, tkinter.TclError):
            print(f"Cannot open a window ({e}).\nOn Linux install Tk (e.g. `sudo apt install python3-tk`) and run inside a "
                  "desktop session, or use `spikefinder run ... --png` for headless use.", file=sys.stderr)
            return 3
        raise
    return 0


def cmd_profiles(_a) -> int:
    from .detect import list_profiles, load_profile
    for n in list_profiles():
        p = load_profile(n)
        print(f"{n}: {p.description}  (fitted on {p.meta.get('n_eye_exams', '?')} eye-exams / {p.meta.get('n_animals', '?')} animals)")
    return 0


def cmd_sample(a) -> int:
    from .sample import write_sample_esx
    write_sample_esx(a.path)
    print(f"wrote synthetic sample {a.path} (made-up A-scans for trying the tool; not a real exam)")
    print(f"try:  spikefinder {a.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="spikefinder", description="Automatic landmark marking and review for Lenstar .esx files.")
    ap.add_argument("--version", action="version", version=f"spikefinder {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("gui", "run"):
        sp = sub.add_parser(name, help="open the review window" if name == "gui" else "headless marking + export")
        sp.add_argument("paths", nargs="*", help=".esx files or folders (searched recursively)")
        sp.add_argument("--out", help=f"output folder for review JSON/CSV (default {default_outdir()})")
        sp.add_argument("--profile", help="detector profile (see `spikefinder profiles`)")
        if name == "run":
            sp.add_argument("--exe-csv", action="store_true", help="also write the original SpikeFinder-format CSV")
            sp.add_argument("--png", action="store_true", help="also write one PNG per eye")
            sp.add_argument("--fresh", action="store_true", help="ignore earlier human edits in the output folder")
            sp.add_argument("--show-identifiers", action="store_true", help="show names on screen (never written to files)")
    sub.add_parser("profiles", help="list detector profiles")
    sp = sub.add_parser("sample", help="write a synthetic .esx to try the tool without real data")
    sp.add_argument("path", nargs="?", default="sample.esx")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and not argv[0].startswith("-")):
        argv.insert(0, "gui")                        # `spikefinder file.esx` == `spikefinder gui file.esx`
    a = build_parser().parse_args(argv)
    return {"gui": cmd_gui, "run": cmd_run, "profiles": cmd_profiles, "sample": cmd_sample}[a.cmd](a)


def main_gui() -> int:
    return main(["gui"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
