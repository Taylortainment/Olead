"""Turn a raw MCP response dump into a pull file the merger can read.

Kept separate from the skill so the transform is testable offline and the raw
platform response stays on disk as an audit trail.

Usage:
  python3 scripts/build_pull.py google 2026-08 data/raw/google-2026-08.json
  python3 scripts/build_pull.py meta   2026-08 data/raw/meta-2026-08.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

VIDEO_TYPES = {"VIDEO"}


def _money(s):
    """'NZ$33,586.34 NZD' -> 33586.34"""
    if isinstance(s, (int, float)):
        return float(s)
    m = re.sub(r"[^0-9.\-]", "", str(s).split("NZD")[0])
    return float(m) if m not in ("", "-", ".") else None


def build_google(month, raw, schema):
    """raw: {'cost': [GAQL rows], 'conversions': [GAQL rows]}"""
    amap = schema["mapping"]["google_ads"]["actions"]
    by_action = {v: k for k, v in amap.items()}
    out = {"YouTube": {}, "Google": {}}
    off_list = []

    for row in raw.get("cost", []):
        ctype = row["campaign"]["advertisingChannelType"]
        ch = "YouTube" if ctype in VIDEO_TYPES else "Google"
        cost = float(row["metrics"].get("costMicros", 0)) / 1e6
        out[ch]["spend_actual"] = out[ch].get("spend_actual", 0.0) + cost

    for row in raw.get("conversions", []):
        ctype = row["campaign"]["advertisingChannelType"]
        ch = "YouTube" if ctype in VIDEO_TYPES else "Google"
        name = row["segments"]["conversionActionName"]
        product = by_action.get(name)
        if not product:
            continue
        v = float(row["metrics"].get("allConversions", 0))
        # A channel reporting a product it is not listed under would be stored
        # but never rendered, because every total is summed over
        # product_channels. Surface it instead of dropping it silently -- it
        # means config/schema.yml needs that channel added.
        if ch not in schema["product_channels"][product]:
            off_list.append((ch, product, v))
            continue
        out[ch][product] = out[ch].get(product, 0.0) + v

    # A channel that spent but recorded no conversions of a mapped product is a
    # measured zero, not missing data -- make that explicit.
    rows = []
    for ch, fields in out.items():
        if "spend_actual" not in fields:
            continue
        for p in schema["products"]:
            if ch in schema["product_channels"][p["key"]]:
                fields.setdefault(p["key"], 0.0)
        for mt, v in fields.items():
            rows.append({"channel": ch, "metric": mt,
                         "value": round(v, 2) if mt in lib.MONEY_METRICS else round(v)})

    warnings = []
    agg = {}
    for ch, product, v in off_list:
        agg[(ch, product)] = agg.get((ch, product), 0.0) + v
    for (ch, product), v in sorted(agg.items()):
        warnings.append(f"{ch} reported {v:.2f} {product} conversions but is not "
                        f"listed under product_channels[{product}] -- not stored. "
                        f"Add it in config/schema.yml if this is real.")
    return rows, warnings


def build_meta(month, raw, schema):
    """raw: the single ad_account entity dict (spend + cost_per_conversion:*)."""
    cfg = schema["mapping"]["meta_ads"]
    ent = raw
    if isinstance(ent, dict) and "ad_entities" in ent:
        blob = ent["ad_entities"]
        ent = json.loads(blob) if isinstance(blob, str) else blob
    if isinstance(ent, list):
        ent = ent[0]

    spend = _money(ent.get("amount_spent") or ent.get("spend"))
    if spend is None:
        raise SystemExit("meta: could not read amount_spent")

    rows = [{"channel": "Meta", "metric": "spend_actual", "value": round(spend, 2)}]
    warnings = []
    for product, action in cfg["actions"].items():
        cpa = ent.get(f"cost_per_conversion:{action}")
        if cpa is None:
            rows.append({"channel": "Meta", "metric": product, "value": 0})
            warnings.append(f"no cost_per_conversion for {product} ({action}) -> recorded 0")
            continue
        n = spend / float(cpa)
        # Guard: spend/cpa must land on a whole number. If it doesn't, Meta
        # changed the field's meaning and the division is no longer valid.
        if abs(n - round(n)) > 0.02:
            warnings.append(
                f"{product}: spend/cpa = {n:.4f} is not integral -- NOT trusted, skipped")
            continue
        rows.append({"channel": "Meta", "metric": product, "value": round(n)})
    return rows, warnings


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    platform, month, path = sys.argv[1], sys.argv[2], sys.argv[3]
    schema = lib.load_schema()
    with open(path) as fh:
        raw = json.load(fh)

    if platform == "google":
        rows, warns = build_google(month, raw, schema)
        connector = "google_ads"
    elif platform == "meta":
        rows, warns = build_meta(month, raw, schema)
        connector = "meta_ads"
    else:
        sys.exit(f"unknown platform {platform!r}")

    out = os.path.join(lib.ROOT, "data", "pulls", f"{month}-{connector}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"month": month, "connector": connector,
                   "source_file": os.path.relpath(path, lib.ROOT),
                   "rows": rows}, fh, indent=2)
    print(f"wrote {out} ({len(rows)} rows)")
    for w in warns:
        print("  ! " + w)
    for r in rows:
        v = f"{r['value']:,.2f}" if r["metric"] in lib.MONEY_METRICS else f"{r['value']:,}"
        print(f"    {r['channel']:<9} {r['metric']:<15} {v:>12}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # stdout closed early (e.g. piped into `head`) -- not a failure
        os._exit(0)
