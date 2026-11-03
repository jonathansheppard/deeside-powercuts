#!/opt/homebrew/bin/python3.11
"""Builds data/powercuts.json for the public power cuts page, from the feed's JSON and its permanent history.
Run after powercuts.py. Usage: build_data.py [output path]"""
import datetime, json, sqlite3, sys, zoneinfo
from pathlib import Path

FEEDS = Path.home() / "emergency-feeds"
CURRENT = FEEDS / "public" / "powercuts.json"
HISTORY = FEEDS / "powercuts_history.db"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data" / "powercuts.json"
LONDON = zoneinfo.ZoneInfo("Europe/London")
# Public wording, kept here because the feed's area names put Buckley under CH5.
AREAS = {
    "CH4": "Saltney, Broughton and Penyffordd",
    "CH5": "Queensferry, Connah's Quay, Shotton and Hawarden",
    "CH6": "Flint and Bagillt",
    "CH7": "Mold, Buckley and nearby villages",
    "CH8": "Holywell and the coast",
}
BANDS = [("Under 1 hour", 0, 60), ("1 to 3 hours", 60, 180), ("3 to 6 hours", 180, 360),
         ("6 to 12 hours", 360, 720), ("Over 12 hours", 720, None)]
PUBLIC_FIELDS = ("ref", "outcodes", "town", "postcodes", "postcode_list", "started", "eta", "message", "planned", "link", "restored_at")


def public(item):
    out = {k: item.get(k, "") for k in PUBLIC_FIELDS}
    ocs = [o for o in (item.get("outcodes") or "").split(", ") if o in AREAS]
    out["area"] = "; ".join(AREAS[o] for o in ocs)
    return out


def timeline(rows, now):
    """Cuts per day, then per week and per month as the record grows. Empty periods stay in, as zeros."""
    if not rows:
        return {"unit": "day", "buckets": []}
    first = min(r["start"] for r in rows).date()
    today = now.date()
    days = (today - first).days + 1
    if days <= 45:
        unit, start, step = "day", first, lambda d: d + datetime.timedelta(days=1)
        key, label = (lambda d: d), (lambda d: d.strftime("%-d %b"))
    elif days <= 182:
        unit, start, step = "week", first - datetime.timedelta(days=first.weekday()), lambda d: d + datetime.timedelta(days=7)
        key, label = (lambda d: d - datetime.timedelta(days=d.weekday())), (lambda d: "w/c " + d.strftime("%-d %b"))
    else:
        unit, start, step = "month", first.replace(day=1), lambda d: (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        key, label = (lambda d: d.replace(day=1)), (lambda d: d.strftime("%b %Y"))
    counts = {}
    for r in rows:
        k = key(r["start"].date())
        counts[k] = counts.get(k, 0) + 1
    buckets, d = [], start
    while d <= today:
        buckets.append({"label": label(d), "count": counts.get(d, 0)})
        d = step(d)
    return {"unit": unit, "buckets": buckets}


def stats(now):
    con = sqlite3.connect(f"file:{HISTORY}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM incidents WHERE planned=0")]
    con.close()
    local = lambda iso: datetime.datetime.fromisoformat(iso).astimezone(LONDON)
    show = lambda dt: dt.strftime("%a %-d %b, %H:%M")
    for r in rows:
        r["start"] = local(r["started_at"] or r["first_seen"])
    rows.sort(key=lambda r: r["start"], reverse=True)
    year = [r for r in rows if r["start"].year == now.year]
    month = [r for r in year if r["start"].month == now.month]
    done = [r for r in year if r["duration_minutes"] is not None]
    longest = max(done, key=lambda r: r["duration_minutes"], default=None)

    by_area = []
    for oc, name in AREAS.items():
        has = lambda r: oc in (r["outcodes"] or "").split(", ")
        mins = [r["duration_minutes"] for r in done if has(r)]
        by_area.append({"outcode": oc, "area": name, "this_year": sum(map(has, year)), "this_month": sum(map(has, month)),
                        "average_minutes": round(sum(mins) / len(mins)) if mins else None, "longest_minutes": max(mins, default=None)})
    bands = [{"label": label, "count": sum(1 for r in done if r["duration_minutes"] >= lo and (hi is None or r["duration_minutes"] < hi))}
             for label, lo, hi in BANDS]
    return {
        "since": min(r["start"] for r in rows).strftime("%-d %B %Y") if rows else None,
        "month_label": now.strftime("%B"), "year_label": now.strftime("%Y"),
        "this_month": len(month), "this_year": len(year),
        "average_minutes": round(sum(r["duration_minutes"] for r in done) / len(done)) if done else None,
        "longest": {"minutes": longest["duration_minutes"], "town": longest["town"], "outcodes": longest["outcodes"],
                    "date": longest["start"].strftime("%-d %B")} if longest else None,
        "by_area": by_area, "bands": bands, "timeline": timeline(rows, now),
        "recent": [{"start": show(r["start"]), "end": show(local(r["restored_at"])) if r["restored_at"] else None,
                    "duration_minutes": r["duration_minutes"], "outcodes": r["outcodes"], "town": r["town"]} for r in rows[:20]],
    }


def main():
    now = datetime.datetime.now(LONDON)
    current = json.loads(CURRENT.read_text())
    payload = {"checked_at": current["checked_at"], "live": [public(i) for i in current["live"]],
               "planned": [public(i) for i in current["planned"]], "restored": [public(i) for i in current["restored"]],
               "stats": stats(now)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name(OUT.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(OUT)


if __name__ == "__main__":
    main()
