#!/usr/bin/env python3
"""One-off: turn data/seed/listings.json into data/houses/<id>.json records.

Each fact is stored with provenance: {"v": value, "src", "conf", "stage", "at"}.
Missing facts are simply absent (= unknown). See SPEC.md section 5.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed" / "listings.json"
OUT = ROOT / "data" / "houses"
FOUND = "2026-10-07"

TYPE_MAP = {"house": "house", "townhouse": "townhouse", "duplex": "duplex",
            "condo": "condo", "apartment": "apartment", "adu": "adu", "other": "other"}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70]


def fact(v, conf, stage="D"):
    return {"v": v, "src": "listing", "conf": conf, "stage": stage, "at": FOUND}


def washer_dryer(text):
    t = text.lower()
    if "in-unit" in t or "in unit" in t or "included" in t or t in ("washer/dryer", "washer and dryer"):
        return "in-unit"
    if "coin" in t or "on site" in t or "on-site" in t or "shared" in t:
        return "shared"
    if "garage" in t or "hookup" in t:
        return "in-garage"
    return text


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    for item in json.loads(SEED.read_text()):
        hid = item.get("id") or slug(f"{item['city']} {item.get('address') or item['url']}")
        if hid in seen:
            raise SystemExit(f"duplicate id {hid}")
        seen.add(hid)
        conf = {"high": 0.9, "medium": 0.6, "low": 0.3}[item.get("confidence", "low")]
        facts = {}
        if item.get("price"):
            facts["rent"] = fact(item["price"], conf)
        for key in ("beds", "baths", "sqft"):
            if item.get(key) is not None:
                facts[key] = fact(item[key], conf)
        if item.get("type"):
            facts["property_type"] = fact(TYPE_MAP.get(item["type"], "other"), conf)
        if item.get("available"):
            facts["available"] = fact(item["available"], conf)
        if item.get("laundry"):
            facts["washer_dryer"] = fact(washer_dryer(item["laundry"]), conf)
        if item.get("parking"):
            facts["parking"] = fact(item["parking"], conf)
        if item.get("pets"):
            facts["pets"] = fact(item["pets"], conf)
        if item.get("listed_date"):
            facts["listed_date"] = fact(item["listed_date"], conf)
        if "furnished" in item["title"].lower():
            facts["furnished"] = fact("yes", conf)
        facts["listing_verified"] = {"v": "partly" if conf >= 0.6 else "unverified",
                                     "src": "computed", "conf": 1.0, "stage": "E", "at": FOUND}
        house = {
            "id": hid,
            "title": item["title"],
            "address": item.get("address"),
            "city": item["city"],
            "zip": item.get("zip"),
            "neighborhood": item.get("neighborhood"),
            "links": [item["url"], *item.get("other_urls", [])],
            "evidence": item.get("evidence"),
            "origin": "web-search",
            "active": True,
            "first_seen": FOUND,
            "last_seen": FOUND,
            "facts": facts,
            "location": None,
            "metrics": None,
        }
        (OUT / f"{hid}.json").write_text(json.dumps(house, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(seen)} houses")


if __name__ == "__main__":
    main()
