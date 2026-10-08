#!/usr/bin/env python3
"""Merge agent-owned house data (data/houses/*.json) with the app database.

The agent exports the app's `houses` collection with ArtifactData
(`action: list`, `out_dir`), runs this script, then applies the batch files it
writes with ArtifactData `action: batch`.

Rules (SPEC.md §5):
- Agent fields (title, address, links, evidence, active, last_seen, location,
  metrics, questions) come from the repo.
- Facts are merged field by field: the more trusted source wins
  (tour > landlord = person > listing = computed > inferred); on a tie the
  newer one wins. So a fact someone confirmed in the app is never overwritten.
- Houses that exist only in the app (pasted by a person) are copied into
  data/houses/ so the enrichment workflow can locate them.

Usage: python3 scripts/sync.py --db-dir DIR --out DIR
  DIR/houses/<id>.json  as written by ArtifactData out_dir
Writes OUT/docs/<id>.json (merged documents) and OUT/batch_<n>.json
(lists of ArtifactData batch entries, at most 40 each).
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOUSES = ROOT / "data" / "houses"
TRUST = {"tour": 5, "landlord": 4, "person": 4, "listing": 3, "computed": 3, "inferred": 1}
AGENT_FIELDS = ["title", "address", "city", "zip", "neighborhood", "links", "evidence", "active",
                "last_seen", "location", "metrics", "questions"]


def load_db(db_dir):
    out = {}
    for f in sorted((Path(db_dir) / "houses").glob("*.json")):
        raw = json.loads(f.read_text())
        # ArtifactData may wrap the document; accept both shapes
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict) and ("version" in raw or "id" in raw):
            data, version = raw["data"], raw.get("version")
        else:
            data, version = raw, raw.get("__version") if isinstance(raw, dict) else None
        out[f.stem] = (data, version)
    return out


def better(a, b):
    """True if fact a should replace fact b."""
    if b is None:
        return True
    ta, tb = TRUST.get(a.get("src"), 0), TRUST.get(b.get("src"), 0)
    if ta != tb:
        return ta > tb
    return str(a.get("at", "")) > str(b.get("at", ""))


def merge(db_doc, repo_doc):
    m = dict(db_doc)
    for k in AGENT_FIELDS:
        if k in repo_doc:
            m[k] = repo_doc[k]
    facts = dict(db_doc.get("facts") or {})
    for k, f in (repo_doc.get("facts") or {}).items():
        if better(f, facts.get(k)):
            facts[k] = f
    m["facts"] = facts
    m["first_seen"] = min(filter(None, [db_doc.get("first_seen"), repo_doc.get("first_seen")]), default=None)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    db = load_db(args.db_dir)
    repo = {f.stem: json.loads(f.read_text()) for f in HOUSES.glob("*.json")}

    entries, created, updated, copied = [], 0, 0, []
    for hid, r in sorted(repo.items()):
        if hid in db:
            cur, version = db[hid]
            m = merge(cur, r)
            if m == cur:
                continue
            entry = {"op": "update", "collection": "houses", "doc_id": hid}
            if version:
                entry["if_version"] = version
            updated += 1
        else:
            m = r
            entry = {"op": "set", "collection": "houses", "doc_id": hid}
            created += 1
        p = out / "docs" / f"{hid}.json"
        p.write_text(json.dumps(m, ensure_ascii=False))
        entry["file_path"] = str(p.resolve())
        entries.append(entry)

    # houses people pasted into the app: bring them into the repo for enrichment
    for hid, (d, _) in db.items():
        if hid not in repo:
            HOUSES.mkdir(parents=True, exist_ok=True)
            (HOUSES / f"{hid}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
            copied.append(hid)

    for i in range(0, len(entries), 40):
        (out / f"batch_{i // 40 + 1}.json").write_text(json.dumps(entries[i:i + 40], indent=1))
    print(json.dumps({"create": created, "update": updated, "copied_to_repo": copied,
                      "batches": (len(entries) + 39) // 40}))


if __name__ == "__main__":
    main()
