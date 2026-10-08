#!/usr/bin/env python3
"""Enrich house records with location data, computed by code (SPEC.md §5-6).

Runs in GitHub Actions (open internet). Stdlib only. For each house in
data/houses/ that needs it:
  1. geocode the address (US Census geocoder; OpenStreetMap Nominatim fallback)
  2. find nearby places from OpenStreetMap (cached in data/geo/pois.json)
  3. real walking and driving times along streets (OSRM table service)
  4. distance to noise sources (Caltrain tracks, US-101, El Camino Real)
  5. FEMA flood zone
  6. a simple walkability estimate
Two modes:
  --area          build area data (needs OpenStreetMap Overpass; run in GitHub
                  Actions): data/geo/basemap.json (the app's street map) and
                  data/geo/pois.json (places + noise-source lines).
  --houses DIR    enrich house JSON files in DIR in place (run by the search
                  agent on an export of the app database). Uses the cached
                  pois.json, so it never calls Overpass.

House data is never stored in this repo; it lives in the app database.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geo"
POIS = GEO / "pois.json"
BASEMAP = GEO / "basemap.json"
PLACES = GEO / "places.json"   # fixed lists we maintain by hand

ENRICH_VERSION = 1
UA = "z16f-find-houses/1.0 (+https://github.com/ddfzhh/z16f_find_houses)"
# south, west, north, east: Redwood City, San Carlos, Menlo Park (+ margin)
BBOX = (37.425, -122.305, 37.535, -122.135)
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
OSRM = {"walk": "https://routing.openstreetmap.de/routed-foot",
        "drive": "https://routing.openstreetmap.de/routed-car"}
CITY_CENTERS = {"Redwood City": (37.4852, -122.2364), "San Carlos": (37.5072, -122.2605),
                "Menlo Park": (37.4530, -122.1817)}

# category -> how many nearest candidates to route to
CATEGORIES = {"caltrain": 2, "supermarket": 3, "post_office": 2, "shopping": 2,
              "cinema": 2, "park": 3, "gym": 3, "restaurant": 3, "hwy101": 2, "hwy280": 2}
WALK_CATEGORIES = {"caltrain", "supermarket", "post_office", "shopping", "cinema",
                   "park", "gym", "restaurant"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http(url, data=None, timeout=60, retries=3):
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log(f"  http retry {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
    return None


def overpass(query, required=True):
    """Run an Overpass query, trying each public server with patient retries
    (they are often busy). Returns [] when not required and all servers fail."""
    for rnd in range(3):
        for url in OVERPASS:
            res = http(url, {"data": query}, timeout=200, retries=2)
            if res and "elements" in res:
                return res["elements"]
        log(f"  overpass busy, waiting before round {rnd + 2}")
        time.sleep(30 * (rnd + 1))
    if required:
        raise RuntimeError("Overpass unavailable")
    return []


def meters(a, b):
    """Great-circle distance between (lat, lng) points, in meters."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def point_line_m(p, line):
    """Shortest distance (m) from point p to a polyline [(lat, lng), ...]."""
    kx = 111320 * math.cos(math.radians(p[0]))
    ky = 110540
    best = float("inf")
    px, py = p[1] * kx, p[0] * ky
    for (a, b) in zip(line, line[1:]):
        ax, ay, bx, by = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky
        dx, dy = bx - ax, by - ay
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


# ---------- places (POIs) ----------

def fetch_pois():
    s, w, n, e = BBOX
    b = f"({s - 0.03},{w - 0.03},{n + 0.03},{e + 0.03})"
    q = f"""[out:json][timeout:180];
(
  nwr["shop"="supermarket"]{b};
  nwr["amenity"="post_office"]{b};
  nwr["amenity"="cinema"]{b};
  nwr["leisure"="park"]["name"]{b};
  nwr["leisure"="fitness_centre"]{b};
  nwr["amenity"="restaurant"]{b};
  node["railway"="station"]{b};
);
out center tags;"""
    pois = {k: [] for k in ("supermarket", "post_office", "cinema", "park", "gym", "restaurant", "caltrain")}
    for el in overpass(q):
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        name = t.get("name") or t.get("brand") or ""
        if t.get("shop") == "supermarket":
            cat = "supermarket"
        elif t.get("amenity") == "post_office":
            cat = "post_office"
        elif t.get("amenity") == "cinema":
            cat = "cinema"
        elif t.get("leisure") == "park":
            cat = "park"
        elif t.get("leisure") == "fitness_centre":
            cat = "gym"
        elif t.get("amenity") == "restaurant":
            cat = "restaurant"
        elif t.get("railway") == "station" and "caltrain" in " ".join(
                [t.get("network", ""), t.get("operator", ""), t.get("name", "")]).lower():
            cat = "caltrain"
            name = re.sub(r"\s*(Caltrain|Station)\s*", " ", name).strip() or name
        else:
            continue
        pois[cat].append({"name": name or cat.replace("_", " "), "lat": round(lat, 6), "lng": round(lng, 6)})

    # highway on-ramps: junction nodes that sit on each freeway
    for key, ref in (("hwy101", "US 101"), ("hwy280", "I 280")):
        q = f"""[out:json][timeout:120];
way["highway"="motorway"]["ref"~"{ref}"]({s - 0.05},{w - 0.05},{n + 0.05},{e + 0.05});
node(w)["highway"="motorway_junction"];
out;"""
        pois[key] = [{"name": f"{ref} exit {el.get('tags', {}).get('ref', '')}".strip()
                      + (f" ({el['tags']['exit_to']})" if el.get("tags", {}).get("exit_to") else ""),
                      "lat": el["lat"], "lng": el["lon"]} for el in overpass(q, required=False) if "lat" in el]
    log("pois:", {k: len(v) for k, v in pois.items()})
    return pois


def fetch_noise_lines():
    s, w, n, e = BBOX
    b = f"({s - 0.02},{w - 0.02},{n + 0.02},{e + 0.02})"
    q = f"""[out:json][timeout:180];
(
  way["railway"="rail"]["service"!~"."]{b};
  way["highway"="motorway"]["ref"~"US 101"]{b};
  way["name"="El Camino Real"]{b};
);
out geom tags;"""
    lines = {"caltrain_tracks": [], "us101": [], "el_camino": []}
    for el in overpass(q, required=False):
        t = el.get("tags", {})
        geom = [(p["lat"], p["lon"]) for p in el.get("geometry", [])]
        if len(geom) < 2:
            continue
        if t.get("railway") == "rail":
            lines["caltrain_tracks"].append(geom)
        elif t.get("highway") == "motorway":
            lines["us101"].append(geom)
        else:
            lines["el_camino"].append(geom)
    return lines


def build_pois():
    data = {"fetched": dt.date.today().isoformat(), "pois": fetch_pois(), "noise": fetch_noise_lines()}
    GEO.mkdir(parents=True, exist_ok=True)
    POIS.write_text(json.dumps(data, separators=(",", ":")))
    log("pois.json written", f"{POIS.stat().st_size / 1e6:.1f} MB")


def load_pois():
    if not POIS.exists():
        raise SystemExit("data/geo/pois.json is missing: run the 'Build map data' GitHub workflow first")
    data = json.loads(POIS.read_text())
    places = json.loads(PLACES.read_text())
    data["pois"]["shopping"] = places["shopping_districts"]
    # hand-kept fallbacks when OpenStreetMap lookups came back empty
    for key, fb in (("caltrain", "caltrain_fallback"), ("hwy101", "hwy101_fallback"), ("hwy280", "hwy280_fallback")):
        if not data["pois"].get(key):
            data["pois"][key] = places.get(fb, [])
    return data


# ---------- geocoding ----------

def clean_address(addr):
    return re.sub(r"\s*(#|unit|apt|suite)\s*\w+$", "", addr, flags=re.I).strip()


def geocode(house):
    addr = house.get("address")
    city = house["city"]
    if not addr:
        lat, lng = CITY_CENTERS.get(city, CITY_CENTERS["Redwood City"])
        return {"lat": lat, "lng": lng, "approx": True, "method": "city-center",
                "query": city}
    one = f"{clean_address(addr)}, {city}, CA {house.get('zip') or ''}".strip()
    res = http("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + urllib.parse.urlencode(
        {"address": one, "benchmark": "Public_AR_Current", "format": "json"}))
    matches = (res or {}).get("result", {}).get("addressMatches") or []
    if matches:
        c = matches[0]["coordinates"]
        return {"lat": round(c["y"], 6), "lng": round(c["x"], 6), "approx": False,
                "method": "census", "query": one, "matched": matches[0].get("matchedAddress")}
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    res = http("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": one, "format": "json", "limit": 1, "countrycodes": "us"}))
    if res:
        return {"lat": round(float(res[0]["lat"]), 6), "lng": round(float(res[0]["lon"]), 6),
                "approx": res[0].get("addresstype") not in ("building", "house", "place"),
                "method": "nominatim", "query": one, "matched": res[0].get("display_name")}
    lat, lng = CITY_CENTERS.get(city, CITY_CENTERS["Redwood City"])
    return {"lat": lat, "lng": lng, "approx": True, "method": "city-center", "query": one}


# ---------- routing ----------

def osrm_table(mode, origin, dests):
    coords = ";".join(f"{lng},{lat}" for lat, lng in [origin, *dests])
    url = (f"{OSRM[mode]}/table/v1/driving/{coords}?sources=0"
           "&annotations=duration,distance")
    time.sleep(1.1)  # be polite to the free public server
    res = http(url, timeout=60)
    if not res or res.get("code") != "Ok":
        return None
    return list(zip(res["durations"][0][1:], res["distances"][0][1:]))


def metrics_for(loc, data):
    origin = (loc["lat"], loc["lng"])
    pois = data["pois"]
    picks = []  # (category, poi)
    for cat, n in CATEGORIES.items():
        cands = sorted(pois.get(cat, []), key=lambda p: meters(origin, (p["lat"], p["lng"])))[:n]
        picks += [(cat, p) for p in cands]
    dests = [(p["lat"], p["lng"]) for _, p in picks]
    walk = osrm_table("walk", origin, dests) if dests else None
    drive = osrm_table("drive", origin, dests) if dests else None

    out = {}
    for i, (cat, p) in enumerate(picks):
        straight = meters(origin, (p["lat"], p["lng"]))
        w = walk[i] if walk else (None, None)
        d = drive[i] if drive else (None, None)
        row = {"name": p["name"], "lat": p["lat"], "lng": p["lng"], "straight_m": round(straight),
               "walk_min": round(w[0] / 60) if w[0] is not None and cat in WALK_CATEGORIES else None,
               "walk_m": round(w[1]) if w[1] is not None and cat in WALK_CATEGORIES else None,
               "drive_min": round(d[0] / 60) if d[0] is not None else None}
        key = "walk_min" if cat in WALK_CATEGORIES else "drive_min"
        best = out.get(cat)
        score = row[key] if row[key] is not None else straight / 80  # ~80 m/min fallback
        best_score = None if best is None else (best[key] if best[key] is not None else best["straight_m"] / 80)
        if best is None or score < best_score:
            out[cat] = row

    noise = {}
    for key, lines in data["noise"].items():
        if lines:
            noise[key + "_m"] = round(min(point_line_m(origin, ln) for ln in lines))
    out["noise"] = noise

    near = lambda cat, r: sum(1 for p in pois.get(cat, []) if meters(origin, (p["lat"], p["lng"])) <= r)
    walk_score = (min(near("supermarket", 800), 2) * 15 + min(near("restaurant", 800), 10) * 3
                  + min(near("park", 800), 3) * 5 + min(near("caltrain", 1000), 1) * 15
                  + min(near("post_office", 1000), 1) * 5 + min(near("cinema", 1500), 1) * 5
                  + min(near("gym", 1000), 1) * 5)
    out["walkability"] = min(100, walk_score)
    out["flood_zone"] = flood_zone(origin)
    return out


def flood_zone(origin):
    url = ("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query?"
           + urllib.parse.urlencode({"geometry": f"{origin[1]},{origin[0]}", "geometryType": "esriGeometryPoint",
                                     "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                     "outFields": "FLD_ZONE,ZONE_SUBTY", "returnGeometry": "false",
                                     "f": "json"}))
    res = http(url, timeout=15, retries=1)
    if not res or "features" not in res:
        return {"zone": None, "high_risk": None}
    if not res["features"]:
        return {"zone": "none mapped", "high_risk": False}
    z = res["features"][0]["attributes"].get("FLD_ZONE") or ""
    return {"zone": z, "high_risk": z.startswith(("A", "V"))}


# ---------- basemap ----------

def simplify(pts, tol=0.00003):
    """Douglas-Peucker on [lng, lat] points (tolerance in degrees, ~3 m)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-12
        idx, dmax = None, tol
        for k in range(i + 1, j):
            x, y = pts[k]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if d > dmax:
                idx, dmax = k, d
        if idx is not None:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def build_basemap():
    s, w, n, e = BBOX
    b = f"({s},{w},{n},{e})"
    q = f"""[out:json][timeout:240];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]{b};
  way["railway"="rail"]{b};
  way["leisure"~"^(park|golf_course|nature_reserve)$"]{b};
  way["natural"~"^(water|wetland|coastline)$"]{b};
  way["waterway"~"^(river|stream|canal)$"]{b};
  way["landuse"="reservoir"]{b};
);
out geom tags;"""
    layers = {k: [] for k in ("motorway", "major", "minor", "rail", "park", "water", "waterline", "coast")}
    labels = []
    for el in overpass(q):
        t = el.get("tags", {})
        pts = [[round(p["lon"], 5), round(p["lat"], 5)] for p in el.get("geometry", [])]
        if len(pts) < 2:
            continue
        pts = simplify(pts)
        hw = t.get("highway", "")
        if hw:
            if hw.startswith(("motorway", "trunk")):
                layer = "motorway"
            elif hw.startswith(("primary", "secondary")):
                layer = "major"
            else:
                layer = "minor"
            layers[layer].append(pts)
            if layer in ("motorway", "major") and t.get("name") and len(pts) > 4:
                mid = pts[len(pts) // 2]
                labels.append([t["name"], mid[0], mid[1], layer])
        elif t.get("railway") == "rail":
            layers["rail"].append(pts)
        elif t.get("leisure") or t.get("landuse"):
            layers["park"].append(pts)
        elif t.get("natural") == "coastline":
            layers["coast"].append(pts)
        elif t.get("natural") in ("water", "wetland"):
            layers["water"].append(pts)
        elif t.get("waterway"):
            layers["waterline"].append(pts)
    # keep one label per street name
    seen, uniq = set(), []
    for lab in labels:
        if lab[0] not in seen:
            seen.add(lab[0])
            uniq.append(lab)
    out = {"bbox": [w, s, e, n], "built": dt.date.today().isoformat(),
           "attribution": "© OpenStreetMap contributors (ODbL)", "layers": layers, "labels": uniq}
    BASEMAP.write_text(json.dumps(out, separators=(",", ":")))
    log("basemap:", {k: len(v) for k, v in layers.items()}, f"{BASEMAP.stat().st_size / 1e6:.1f} MB")


# ---------- main ----------

def needs_enrich(h, force):
    if force or not h.get("location") or not h.get("metrics"):
        return True
    loc = h["location"]
    return loc.get("version") != ENRICH_VERSION or loc.get("address") != h.get("address")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", action="store_true", help="rebuild street map and places cache")
    ap.add_argument("--houses", metavar="DIR", help="enrich house JSON files in DIR in place")
    ap.add_argument("--all", action="store_true", help="with --houses: re-enrich every house")
    args = ap.parse_args()

    if args.area:
        failed = []
        for step in (build_basemap, build_pois):
            try:
                step()
            except Exception as e:  # keep whatever succeeded
                log(f"{step.__name__} failed: {e}")
                failed.append(step.__name__)
        if failed and not POIS.exists() and not BASEMAP.exists():
            raise SystemExit(f"map data build failed: {failed}")
    if not args.houses:
        return

    todo = []
    for f in sorted(Path(args.houses).glob("*.json")):
        h = json.loads(f.read_text())
        h.setdefault("id", f.stem)
        if h.get("active", True) and needs_enrich(h, args.all):
            todo.append((f, h))
    log(f"{len(todo)} houses to enrich")
    if not todo:
        return
    data = load_pois()
    today = dt.date.today().isoformat()
    changed = []
    for i, (f, h) in enumerate(todo, 1):
        log(f"[{i}/{len(todo)}] {h['id']}")
        loc = geocode(h)
        loc.update({"version": ENRICH_VERSION, "address": h.get("address"), "at": today})
        h["location"] = loc
        h["metrics"] = metrics_for(loc, data)
        h["metrics"]["at"] = today
        f.write_text(json.dumps(h, indent=2, ensure_ascii=False) + "\n")
        changed.append(h["id"])
    print(json.dumps({"enriched": changed}))


if __name__ == "__main__":
    main()
