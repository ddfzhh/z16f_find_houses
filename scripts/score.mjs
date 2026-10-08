// Score houses exactly as the web app does, by running app/index.html's own
// scoring code in Node. Used by the search agent for alert emails.
//
// Usage: node scripts/score.mjs DB_DIR
//   DB_DIR/houses/*.json, DB_DIR/status/*.json, DB_DIR/unified/current.json
//   (as exported by ArtifactData out_dir; missing folders are fine)
// Prints JSON: [{id, title, city, rent, score, fails_must, status, first_seen}]
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "app/index.html"), "utf8");
const start = html.indexOf('<script>\n"use strict"');
const code = html.slice(start + 8, html.lastIndexOf("</script>"));

const el = () => new Proxy({ style: {}, dataset: {}, querySelectorAll: () => [], querySelector: () => null, contains: () => false, addEventListener() {}, focus() {} },
  { get: (t, k) => (k in t ? t[k] : k === "hidden" ? true : undefined), set: (t, k, v) => ((t[k] = v), true) });
const ctx = { console, URL, Date, Math, JSON, setTimeout, clearTimeout, requestAnimationFrame: () => 0,
  document: { getElementById: el, addEventListener() {}, querySelectorAll: () => [], activeElement: null, documentElement: {}, body: { style: {} } },
  localStorage: { getItem: () => null, setItem() {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }) };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(code + "\n;globalThis.__api = { S, evaluate, cityMedians, statusOf };", ctx);
const { S, evaluate, cityMedians, statusOf } = ctx.__api;

const dir = process.argv[2];
const read = f => { const raw = JSON.parse(fs.readFileSync(f, "utf8")); return raw && raw.data && (raw.version || raw.id) ? raw.data : raw; };
const each = sub => { const d = path.join(dir, sub); return fs.existsSync(d) ? fs.readdirSync(d).filter(f => f.endsWith(".json")).map(f => [f.slice(0, -5), read(path.join(d, f))]) : []; };
for (const [id, h] of each("houses")) S.houses.set(id, { id, ...h });
for (const [id, s] of each("status")) S.status.set(id, s);
const uf = path.join(dir, "unified", "current.json");
if (fs.existsSync(uf)) S.unified = read(uf);

const med = cityMedians();
const out = [...S.houses.values()].map(h => {
  const ev = evaluate(h, med);
  return { id: h.id, title: h.address || h.title, city: h.city, rent: h.facts?.rent?.v ?? null, score: ev.score,
    fails_must: ev.failsMust, status: statusOf(h), first_seen: h.first_seen, active: h.active !== false };
}).sort((a, b) => b.score - a.score);
console.log(JSON.stringify(out, null, 1));
