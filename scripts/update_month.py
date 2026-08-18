"""Merge a month's connector pulls + manual entry into the store.

Inputs for month M:
  data/pulls/M-<connector>.json   written by the /mom-update skill from MCP
  manual_input/M.yml              typed by hand for connector-less channels

Facts already in the store are only replaced when the new value differs, and
the change is always printed. Nothing is overwritten silently.

Usage:
  python3 scripts/update_month.py 2026-08 [--apply] [--force]
Without --apply it is a dry run.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib


def collect(month, schema):
    """-> {(channel, metric): (value, source)}"""
    incoming, problems = {}, []
    valid_ch = set(schema["channels"])
    valid_metrics = {"spend_actual", "spend_forecast"} | {p["key"] for p in schema["products"]}

    for path in sorted(glob.glob(os.path.join(lib.ROOT, "data", "pulls", f"{month}-*.json"))):
        with open(path) as fh:
            blob = json.load(fh)
        if blob.get("month") != month:
            problems.append(f"{os.path.basename(path)}: month is {blob.get('month')!r}, expected {month!r}")
            continue
        src = blob.get("connector", os.path.basename(path))
        for r in blob.get("rows", []):
            ch, mt, v = r.get("channel"), r.get("metric"), r.get("value")
            if ch not in valid_ch or mt not in valid_metrics:
                problems.append(f"{os.path.basename(path)}: unknown {ch!r}/{mt!r}")
                continue
            if v is None:
                continue
            incoming[(ch, mt)] = (float(v), src)

    mpath = os.path.join(lib.ROOT, "manual_input", f"{month}.yml")
    if os.path.exists(mpath):
        import yaml
        blob = yaml.safe_load(open(mpath)) or {}
        if str(blob.get("month")) != month:
            problems.append(f"{month}.yml: month field is {blob.get('month')!r}")
        for ch, fields in (blob.get("channels") or {}).items():
            if ch not in valid_ch:
                problems.append(f"{month}.yml: unknown channel {ch!r}")
                continue
            for k, v in (fields or {}).items():
                mt = "spend_actual" if k == "spend" else k
                if mt not in valid_metrics:
                    problems.append(f"{month}.yml: unknown field {ch}.{k}")
                    continue
                if v is None or v == "":
                    continue
                incoming[(ch, mt)] = (float(v), "manual")
    else:
        problems.append(f"no manual_input/{month}.yml -- run: python3 scripts/new_month.py {month}")

    return incoming, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("month")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--force", action="store_true",
                    help="also replace values whose source is the original doc")
    a = ap.parse_args()

    schema = lib.load_schema()
    store = lib.read_store()
    incoming, problems = collect(a.month, schema)

    if problems:
        print("input warnings:")
        for p in problems:
            print("  !", p)
        print()

    adds, changes, blocked = [], [], []
    for (ch, mt), (v, src) in sorted(incoming.items()):
        cur = store.get((a.month, ch, mt))
        if cur is None:
            adds.append((ch, mt, v, src))
        elif abs(cur["value"] - v) > 0.005:
            if cur["source"] == "doc" and not a.force:
                blocked.append((ch, mt, cur["value"], v))
            else:
                changes.append((ch, mt, cur["value"], v, src))

    def show(title, rows, fmt):
        if rows:
            print(f"{title} ({len(rows)}):")
            for r in rows:
                print("   " + fmt(r))
            print()

    show("new values", adds, lambda r: f"{r[0]:<11} {r[1]:<15} {r[2]:>12,.2f}  [{r[3]}]")
    show("updated values", changes,
         lambda r: f"{r[0]:<11} {r[1]:<15} {r[2]:>12,.2f} -> {r[3]:>12,.2f}  [{r[4]}]")
    show("BLOCKED (would overwrite an original-doc figure; pass --force)", blocked,
         lambda r: f"{r[0]:<11} {r[1]:<15} doc={r[2]:>12,.2f}  new={r[3]:>12,.2f}")

    if not (adds or changes):
        print("nothing to change.")
        return

    if not a.apply:
        print("dry run -- re-run with --apply to write.")
        return

    for ch, mt, v, src in adds:
        store[(a.month, ch, mt)] = {"value": v, "source": src}
    for ch, mt, _, v, src in changes:
        store[(a.month, ch, mt)] = {"value": v, "source": src}
    n = lib.write_store(store)
    print(f"applied. store now holds {n} facts.")


if __name__ == "__main__":
    main()
