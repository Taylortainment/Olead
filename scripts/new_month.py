"""Create the manual-entry stub for a month.

Only the channels with no connector appear -- currently TikTok, Reddit,
Spotify and StackAdapt. Each field is pre-annotated with last month's value
so a wrong-order paste is obvious at a glance.

Usage:  python3 scripts/new_month.py 2026-08
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib


def prev_month(m):
    y, mm = (int(x) for x in m.split("-"))
    return f"{y-1:04d}-12" if mm == 1 else f"{y:04d}-{mm-1:02d}"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: new_month.py YYYY-MM")
    month = sys.argv[1]
    schema = lib.load_schema()
    store = lib.read_store()
    prev = prev_month(month)
    manual = [c for c, s in schema["sourcing"].items() if s["mode"] == "manual"]
    manual = [c for c in schema["channels"] if c in manual]

    path = os.path.join(lib.ROOT, "manual_input", f"{month}.yml")
    if os.path.exists(path):
        sys.exit(f"{path} already exists -- edit it, or delete it to regenerate.")

    L = [f"# Manual channel entry -- {lib.month_label(month)}",
         "# Only channels without an API connector live here. Meta, Google and",
         "# YouTube are pulled automatically by the /mom-update skill.",
         "#",
         "# Leave a field blank or delete the line if there is genuinely no data.",
         "# A 0 means 'measured zero'; blank means 'not reported'. They render",
         "# differently in the client report, so the distinction matters.",
         f"month: \"{month}\"", "channels:"]

    for ch in manual:
        L.append(f"  {ch}:")
        pv = lib.get(store, prev, ch, "spend_actual")
        pv_s = f"{pv:,.2f}" if pv is not None else "n/a"
        L.append(f"    spend:            # {lib.month_label(prev, True)} was {pv_s}")
        for p in schema["products"]:
            if ch not in schema["product_channels"][p["key"]]:
                continue
            pv = lib.get(store, prev, ch, p["key"])
            pv_s = f"{pv:,.0f}" if pv is not None else "n/a"
            L.append(f"    {p['key']+':':<18}# {p['label']} -- "
                     f"{lib.month_label(prev, True)} was {pv_s}")
        L.append("")

    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"created {path}")
    print(f"channels needing manual entry: {', '.join(manual)}")


if __name__ == "__main__":
    main()
