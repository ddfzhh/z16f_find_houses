#!/usr/bin/env python3
"""Turn the agent's proposed house changes into ArtifactData batch writes.

House data lives only in the app database. Each agent run:
  1. exports `houses` with ArtifactData (`list`, `out_dir`) -> EXPORT/houses/
     and records each document's version in a JSON file {id: version}
  2. copies EXPORT/houses to PROPOSED/, edits PROPOSED (new listings, updated
     facts, last_seen, active) and runs `scripts/enrich.py --houses PROPOSED`
  3. runs this script, then applies every OUT/batch_<n>.json with
     ArtifactData `action: batch` (pass the file's entries as `writes`)

Merge rules (SPEC.md §5):
- Agent fields (title, address, links, evidence, active, last_seen, location,
  metrics, questions, ...) come from PROPOSED.
- Facts merge field by field: the more trusted source wins
  (tour > landlord = person > listing = computed > inferred); on a tie the
  newer one wins. A fact someone confirmed in the app is never overwritten.
- Only documents that actually changed are written; existing ones are pinned
  with if_version, so a write never clobbers an edit made meanwhile.

Usage: python3 scripts/sync.py --export EXPORT/houses --proposed PROPOSED \
         --versions versions.json --out OUT
"""
import argparse
import json
from pathlib import Path

TRUST = {"tour": 5, "landlord": 4, "person": 4, "listing": 3, "computed": 3, "inferred": 1}
PEOPLE_FIELDS = {"added_by"}  # fields only people set; never taken from PROPOSED


def better(a, b):
    """True if fact a should replace fact b."""
    if b is None:
        return True
    ta, tb = TRUST.get(a.get("src"), 0), TRUST.get(b.get("src"), 0)
    if ta != tb:
        return ta > tb
    return str(a.get("at", "")) > str(b.get("at", ""))


def merge(cur, prop):
    m = dict(cur)
    for k, v in prop.items():
        if k not in ("facts", "first_seen") and k not in PEOPLE_FIELDS:
            m[k] = v
    facts = dict(cur.get("facts") or {})
    for k, f in (prop.get("facts") or {}).items():
        if isinstance(f, dict) and better(f, facts.get(k)):
            facts[k] = f
    m["facts"] = facts
    seen = [x for x in (cur.get("first_seen"), prop.get("first_seen")) if x]
    if seen:
        m["first_seen"] = min(seen)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="folder of exported house JSON files")
    ap.add_argument("--proposed", required=True, help="folder of proposed house JSON files")
    ap.add_argument("--versions", required=True, help="JSON file {doc_id: version} from the export")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    versions = json.loads(Path(args.versions).read_text())
    current = {f.stem: json.loads(f.read_text()) for f in Path(args.export).glob("*.json")}

    entries, created, updated = [], [], []
    for f in sorted(Path(args.proposed).glob("*.json")):
        hid, prop = f.stem, json.loads(f.read_text())
        prop["id"] = hid
        if hid in current:
            m = merge(current[hid], prop)
            if m == current[hid]:
                continue
            if hid not in versions:
                raise SystemExit(f"no version recorded for existing house {hid}")
            entry = {"op": "set", "collection": "houses", "doc_id": hid, "if_version": versions[hid]}
            updated.append(hid)
        else:
            m = prop
            entry = {"op": "set", "collection": "houses", "doc_id": hid}
            created.append(hid)
        p = out / "docs" / f"{hid}.json"
        p.write_text(json.dumps(m, ensure_ascii=False))
        entry["file_path"] = str(p.resolve())
        entries.append(entry)

    n = 0
    for i in range(0, len(entries), 40):
        n += 1
        (out / f"batch_{n}.json").write_text(json.dumps(entries[i:i + 40], indent=1))
    print(json.dumps({"create": created, "update": updated, "batches": n}))


if __name__ == "__main__":
    main()
