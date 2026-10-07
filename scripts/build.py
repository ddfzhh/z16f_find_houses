#!/usr/bin/env python3
"""Build the house-search dashboard from data/listings.json.

Stdlib only. Steps (each optional step is skipped quietly if it can't run):
  --geocode      fill missing lat/lng via the US Census geocoder (needs internet)
  --sync-issues  create a GitHub issue per listing and read status labels back
                 (needs GITHUB_TOKEN and GITHUB_REPOSITORY env vars)
Always: enrich listings (Caltrain distance, value score, match flags) and
write docs/listings.json (for docs/index.html) and README.md.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "search.json"
DATA = ROOT / "data" / "listings.json"
DOCS_JSON = ROOT / "docs" / "listings.json"
README = ROOT / "README.md"

STATUSES = ["new", "interested", "touring", "applied", "rejected"]
STATUS_COLORS = {
    "interested": "0e8a16",
    "touring": "1d76db",
    "applied": "5319e7",
    "rejected": "b60205",
}
MARKER = re.compile(r"<!--\s*listing-id:\s*([\w.-]+)\s*-->")


# ---------- helpers ----------

def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text() or "null") or default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def listing_id(item):
    if item.get("address"):
        return slug(f"{item.get('city', '')} {item['address']}")
    return "l-" + hashlib.sha1(item["url"].encode()).hexdigest()[:10]


def miles_between(lat1, lng1, lat2, lng2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clamp01(x):
    return max(0.0, min(1.0, x))


def http_json(url, token=None, method="GET", body=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "house-search"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


# ---------- optional: geocoding ----------

def geocode(listings):
    changed = False
    for item in listings:
        if item.get("lat") is not None or not item.get("address"):
            continue
        q = f"{item['address']}, {item.get('city', '')}, CA {item.get('zip') or ''}"
        url = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?"
               + urllib.parse.urlencode({"address": q, "benchmark": "Public_AR_Current", "format": "json"}))
        try:
            matches = http_json(url)["result"]["addressMatches"]
        except Exception as e:  # network blocked, timeout, bad response
            print(f"geocode skipped ({e.__class__.__name__}); stopping geocoding", file=sys.stderr)
            return changed
        if matches:
            c = matches[0]["coordinates"]
            item["lat"], item["lng"] = round(c["y"], 6), round(c["x"], 6)
            changed = True
        else:
            print(f"geocode: no match for {q}", file=sys.stderr)
    return changed


# ---------- optional: GitHub issue sync ----------

def issue_body(item):
    lines = [
        f"**{item.get('title') or item.get('address') or 'Listing'}**",
        "",
        f"- Price: {fmt_money(item.get('price'))}/mo",
        f"- Beds / baths: {item.get('beds') or '?'} / {item.get('baths') or '?'}",
        f"- Size: {item.get('sqft') or '?'} sqft",
        f"- Type: {item.get('type') or '?'}",
        f"- Address: {item.get('address') or '?'}, {item.get('city') or ''}",
        f"- Available: {item.get('available') or '?'}",
        f"- Listing: {item['url']}",
        "",
        "Discuss this place in the comments. React 👍 / 👎 on this issue to vote.",
        "Set the status with a label: `status: interested`, `status: touring`, "
        "`status: applied`, `status: rejected` (closing the issue also counts as rejected).",
        "",
        f"<!-- listing-id: {item['id']} -->",
    ]
    return "\n".join(lines)


def sync_issues(listings):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("issue sync skipped (no GITHUB_TOKEN/GITHUB_REPOSITORY)", file=sys.stderr)
        return False
    api = f"https://api.github.com/repos/{repo}"

    for name, color in [("listing", "c5def5"), *[(f"status: {s}", c) for s, c in STATUS_COLORS.items()]]:
        try:
            http_json(f"{api}/labels", token, "POST", {"name": name, "color": color})
        except urllib.error.HTTPError as e:
            if e.code != 422:  # 422 = already exists
                raise

    issues, page = [], 1
    while True:
        batch = http_json(f"{api}/issues?labels=listing&state=all&per_page=100&page={page}", token)
        issues += batch
        if len(batch) < 100:
            break
        page += 1
    by_id = {}
    for iss in issues:
        m = MARKER.search(iss.get("body") or "")
        if m:
            by_id[m.group(1)] = iss

    changed = False
    for item in listings:
        iss = by_id.get(item["id"])
        if iss is None:
            title = f"{fmt_money(item.get('price'))} · {item.get('beds') or '?'}bd · " \
                    f"{item.get('address') or item.get('title') or 'listing'}, {item.get('city', '')}"
            iss = http_json(f"{api}/issues", token, "POST",
                            {"title": title[:200], "body": issue_body(item), "labels": ["listing"]})
            print(f"created issue #{iss['number']} for {item['id']}")
        if item.get("issue") != iss["number"]:
            item["issue"] = iss["number"]
            changed = True

        labels = {l["name"] for l in iss.get("labels", [])}
        status = "new"
        for s in STATUSES[1:]:
            if f"status: {s}" in labels:
                status = s
        if iss["state"] == "closed" and status not in ("applied",):
            status = "rejected"
        if item.get("status") != status:
            item["status"] = status
            changed = True

        if item.get("active") is False and iss["state"] == "open" and status == "new":
            http_json(f"{api}/issues/{iss['number']}/comments", token, "POST",
                      {"body": "This listing looks off the market (no longer found by the search). Closing."})
            http_json(f"{api}/issues/{iss['number']}", token, "PATCH",
                      {"state": "closed", "state_reason": "not_planned"})
    return changed


# ---------- enrichment ----------

def enrich(item, cfg, today):
    sc = cfg["scoring"]
    out = dict(item)
    out.setdefault("status", "new")
    out.setdefault("active", True)

    # nearest Caltrain station
    if item.get("lat") is not None and item.get("lng") is not None:
        best = min(cfg["caltrain_stations"],
                   key=lambda s: miles_between(item["lat"], item["lng"], s["lat"], s["lng"]))
        mi = miles_between(item["lat"], item["lng"], best["lat"], best["lng"])
        out["caltrain"] = best["name"]
        out["caltrain_miles"] = round(mi, 2)
        out["caltrain_walk_min"] = round(mi * 1.25 / 3.0 * 60)  # 1.25 street factor, 3 mph
    else:
        out["caltrain"] = out["caltrain_miles"] = out["caltrain_walk_min"] = None

    price, beds, sqft = item.get("price"), item.get("beds"), item.get("sqft")
    out["price_per_person"] = round(price / 2) if price else None
    out["price_per_bed"] = round(price / beds) if price and beds else None
    out["price_per_sqft"] = round(price / sqft, 2) if price and sqft else None

    # value score (0-100)
    w = sc["weights"]
    s_price = (clamp01((sc["price_per_bed_poor"] - out["price_per_bed"])
                       / (sc["price_per_bed_poor"] - sc["price_per_bed_great"]))
               if out["price_per_bed"] else 0.3)
    s_size = clamp01((sqft - sc["sqft_poor"]) / (sc["sqft_great"] - sc["sqft_poor"])) if sqft else 0.5
    s_transit = (clamp01((sc["caltrain_miles_poor"] - out["caltrain_miles"])
                         / (sc["caltrain_miles_poor"] - sc["caltrain_miles_great"]))
                 if out["caltrain_miles"] is not None else 0.4)
    s_type = sc["type_scores"].get(item.get("type") or "other", 0.5)
    out["score"] = round(100 * (w["price"] * s_price + w["transit"] * s_transit
                                + w["size"] * s_size + w["type"] * s_type))

    # match flags
    avail = item.get("available")
    out["beds_ok"] = beds is not None and cfg["beds_min"] <= beds <= cfg["beds_max"]
    out["avail_ok"] = avail in (None, "now") or avail <= cfg["available_by"]
    out["price_ok"] = cfg.get("soft_max_price") is None or (price or 0) <= cfg["soft_max_price"]
    out["match"] = bool(out["active"] and out["beds_ok"] and out["avail_ok"] and out["price_ok"]
                        and out["status"] != "rejected")
    first = item.get("first_seen")
    out["is_new"] = bool(first and (today - dt.date.fromisoformat(first)).days <= 2)
    return out


# ---------- README ----------

def fmt_money(v):
    return f"${v:,.0f}" if v else "?"


def readme_row(x, repo):
    where = x.get("address") or x.get("title") or "listing"
    where = f"[{where}]({x['url']}), {x.get('city', '')}"
    if x.get("neighborhood"):
        where += f" ({x['neighborhood']})"
    ct = (f"{x['caltrain_miles']} mi to {x['caltrain']} (~{x['caltrain_walk_min']} min walk)"
          if x.get("caltrain_miles") is not None else "?")
    talk = f"[#{x['issue']}](https://github.com/{repo}/issues/{x['issue']})" if x.get("issue") else "—"
    new = " 🆕" if x.get("is_new") else ""
    return (f"| **{x['score']}**{new} | {fmt_money(x.get('price'))} ({fmt_money(x.get('price_per_person'))}/pp) "
            f"| {x.get('beds') or '?'} / {x.get('baths') or '?'} | {x.get('sqft') or '?'} "
            f"| {x.get('type') or '?'} | {where} | {ct} | {x.get('available') or '?'} "
            f"| {x.get('status', 'new')} | {talk} |")


def render_readme(rows, cfg, now):
    repo = cfg["repo"]
    owner, name = repo.split("/")
    head = ("| Score | Rent (per person, 2 ppl) | Beds / Baths | Sqft | Type | Where | Caltrain "
            "| Available | Status | Discuss |\n|---|---|---|---|---|---|---|---|---|---|")
    matches = [r for r in rows if r["match"]]
    others = [r for r in rows if not r["match"] and r["active"] and r["status"] != "rejected"]
    closed = [r for r in rows if not r["active"] or r["status"] == "rejected"]

    def table(rs):
        return head + "\n" + "\n".join(readme_row(r, repo) for r in rs) if rs else "_None right now._"

    return f"""# 🏡 House Search — Redwood City, San Carlos & Menlo Park

Two friends looking for a **cheap, big, comfortable 2–3 bedroom place near Caltrain**,
available **now or by {cfg['available_by']}**. This page is generated automatically —
don't edit it by hand (see [`CLAUDE.md`](CLAUDE.md)).

**📊 Interactive dashboard (filters, map):** https://{owner}.github.io/{name}/ ·
**💬 Talk about a house:** open its issue in the *Discuss* column (or
[all listings](https://github.com/{repo}/issues?q=label%3Alisting)) and comment / react 👍 👎.

_Last updated: {now} · {len(matches)} matching · {len(others)} near-misses · {len(closed)} rejected/gone_

## ✅ Matching listings (best value first)

{table(matches)}

<details><summary>🤔 Near-misses ({len(others)}) — wrong bed count, later availability, or over budget</summary>

{table(others)}

</details>

<details><summary>🗑️ Rejected or off the market ({len(closed)})</summary>

{table(closed)}

</details>

### How the score works (0–100)
{int(cfg['scoring']['weights']['price']*100)}% price per bedroom · {int(cfg['scoring']['weights']['transit']*100)}% distance to the nearest Caltrain station ·
{int(cfg['scoring']['weights']['size']*100)}% square footage · {int(cfg['scoring']['weights']['type']*100)}% property type (houses/townhouses rank higher).
Tune it in [`config/search.json`](config/search.json). Distances are straight-line estimates.
"""


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geocode", action="store_true")
    ap.add_argument("--sync-issues", action="store_true")
    args = ap.parse_args()

    cfg = load_json(CONFIG, {})
    listings = load_json(DATA, [])
    today = dt.date.today()

    changed = False
    seen = set()
    for item in listings:
        if not item.get("id"):
            item["id"] = listing_id(item)
            changed = True
        if item["id"] in seen:
            sys.exit(f"duplicate listing id: {item['id']}")
        seen.add(item["id"])
        if not item.get("first_seen"):
            item["first_seen"] = today.isoformat()
            changed = True

    if args.geocode:
        changed |= geocode(listings)
    if args.sync_issues:
        changed |= sync_issues(listings)
    if changed:
        save_json(DATA, listings)

    rows = sorted((enrich(x, cfg, today) for x in listings), key=lambda r: -r["score"])
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    save_json(DOCS_JSON, {"generated": now, "config": cfg, "listings": rows})
    README.write_text(render_readme(rows, cfg, now))
    print(f"built {len(rows)} listings ({sum(r['match'] for r in rows)} matching)")


if __name__ == "__main__":
    main()
