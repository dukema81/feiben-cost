# -*- coding: utf-8 -*-
"""从线上实例抓取真实数据，生成单文件离线 DEMO（可双击打开、无需服务端）。"""
import json
import os
import urllib.request
import zipfile

BASE = "http://42.193.158.63/cost"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo")
TOK = open(os.path.join(ROOT, "Temp_tok.txt"), encoding="utf-8").read().strip()


def get(path):
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", "Bearer " + TOK)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print("  !! %s -> %s" % (path, e))
        return {}


periods = get("/api/periods").get("list", [])
P = periods[0]["period"] if periods else "2026-10"
print("period:", P)

SNAP = {
    "board": get("/api/board?period=%s" % P),
    "centers": get("/api/cost-centers"),
    "subjects": get("/api/subjects"),
    "products": get("/api/products"),
    "std": get("/api/std-costs?period=%s" % P),
    "orders": get("/api/work-orders?period=%s" % P),
    "expenses": get("/api/expenses?period=%s" % P),
    "budgets": get("/api/budgets?period=%s" % P),
    "vars": get("/api/variances?period=%s" % P),
    "alloc": get("/api/allocations?period=%s" % P),
    "rules": get("/api/allocation-rules"),
    "rep_center": get("/api/reports/center-summary?period=%s" % P),
    "rep_prod": get("/api/reports/product-cost?period=%s" % P),
    "rep_top": get("/api/reports/variance-top?period=%s" % P),
    "rep_trend": get("/api/reports/trend"),
    "periods": {"list": periods},
}

for k, v in SNAP.items():
    n = len(v["list"]) if isinstance(v, dict) and isinstance(v.get("list"), list) else ("dict" if isinstance(v, dict) else len(v))
    print("  %-12s %s" % (k, n))

os.makedirs(OUT, exist_ok=True)
data = json.dumps(SNAP, ensure_ascii=False, separators=(",", ":"))
tpl = open(os.path.join(ROOT, "tools", "demo_template.html"), encoding="utf-8").read()
html = tpl.replace("__DATA__", data)
out_html = os.path.join(OUT, "feiben-cost-demo.html")
open(out_html, "w", encoding="utf-8").write(html)
print("html: %d bytes -> %s" % (len(html), out_html))

out_zip = os.path.join(OUT, "feiben-cost-demo.zip")
with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(out_html, "feiben-cost-demo.html")
print("zip: %d bytes" % os.path.getsize(out_zip))
