# -*- coding: utf-8 -*-
"""冒烟测试：全量 GET 路由 + 主流程写入链路（独立临时库，不污染演示数据）"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

TMP = tempfile.mkdtemp(prefix="feiben_smoke_")
os.environ["FEIBEN_DB"] = os.path.join(TMP, "smoke.db")
os.environ["PORT"] = "8919"
os.environ["FEIBEN_PREFIX"] = ""

import db  # noqa: E402
import seed  # noqa: E402
import server  # noqa: E402

PORT = 8919
PASS, FAIL = [], []


def http(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  " + str(extra)) if not cond else ""))


def main():
    db.init()
    seed.seed()
    s = server.ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    time.sleep(0.6)
    print("=" * 74)
    print("飞奔成本管理系统 · 冒烟测试  (routes=%d)" % len(server.ROUTES))
    print("=" * 74)

    st, d = http("GET", "/api/health")
    check("GET /api/health", st == 200 and d["routes"] == len(server.ROUTES), d)
    st, d = http("POST", "/api/auth/login", {"username": "admin", "password": "cost@2026"})
    check("POST /api/auth/login", st == 200 and d.get("token"), d)
    t = d["token"]

    # ---- 全量 GET 路由
    gets = [
        "/api/auth/me", "/api/board?period=2026-10", "/api/cost-centers?period=2026-10",
        "/api/subjects", "/api/products?period=2026-10", "/api/products/P1001?period=2026-10",
        "/api/products/P1001/bom", "/api/std-costs?period=2026-10",
        "/api/work-orders?period=2026-10", "/api/work-orders/WO202610-0001",
        "/api/expenses?period=2026-10", "/api/expenses/summary?period=2026-10",
        "/api/allocation-rules", "/api/allocations", "/api/budgets?period=2026-10",
        "/api/budgets/exec?period=2026-10", "/api/variances?period=2026-10",
        "/api/reports/center-summary?period=2026-10",
        "/api/reports/product-cost?period=2026-10",
        "/api/reports/variance-top?period=2026-10&n=5",
        "/api/reports/trend?months=6&period=2026-10",
        "/api/periods", "/api/rules", "/api/users", "/api/logs?limit=20",
        "/api/keys", "/api/webhooks", "/api/webhooks/deliveries",
        "/api/sync/changes", "/api/openapi.json",
    ]
    for g in gets:
        st, d = http("GET", g, token=t)
        check("GET " + g, st == 200, d if st != 200 else "")

    # ---- 写入链路
    st, d = http("POST", "/api/std-costs/calc", {"period": "2026-10"}, token=t)
    check("POST /api/std-costs/calc", st == 200 and d["count"] >= 6, d)

    st, d = http("POST", "/api/work-orders", {"product": "P1001", "center": "CC101",
                                              "qtyPlan": 500, "qtyDone": 500,
                                              "period": "2026-10"}, token=t)
    wo = d.get("no")
    check("POST /api/work-orders", st == 200 and wo, d)
    st, d = http("POST", "/api/work-orders/%s/materials" % wo,
                 {"materialCode": "M1001", "qty": 220, "price": 12.9}, token=t)
    check("POST 工单领料", st == 200 and d["amount"] > 0, d)
    st, d = http("POST", "/api/work-orders/%s/labor" % wo,
                 {"hours": 180, "rate": 38.5}, token=t)
    check("POST 工时报工", st == 200 and d["amount"] > 0, d)
    st, d = http("POST", "/api/work-orders/%s/calc" % wo, {}, token=t)
    check("POST 工单核算", st == 200 and d["actual"]["totalActual"] > 0, d)
    st, e = http("POST", "/api/work-orders/%s/stage" % wo, {"target": "已完工"}, token=t)
    check("POST 工单完工", st == 200 and e["status"] == "已完工", e)

    st, d = http("POST", "/api/expenses", {"period": "2026-10", "center": "CC103",
                                           "subject": "S3005", "amount": 800,
                                           "summary": "冒烟测试费用"}, token=t)
    exp = d.get("no")
    check("POST /api/expenses", st == 200 and exp, d)
    st, d = http("POST", "/api/expenses/%s/stage" % exp, {"target": "待审批"}, token=t)
    check("POST 费用提交", st == 200, d)
    st, d = http("POST", "/api/expenses/%s/stage" % exp, {"target": "已批准"}, token=t)
    check("POST 费用批准", st == 200, d)

    st, d = http("POST", "/api/allocations/run", {"period": "2026-10"}, token=t)
    check("POST 分摊执行", st == 200 and abs(d["checkDiff"]) < 0.02, d)
    run = d.get("no")
    st, d = http("GET", "/api/allocations/" + run, token=t)
    check("GET 分摊明细", st == 200 and len(d["lines"]) >= 6, d)

    st, d = http("POST", "/api/variances/calc", {"period": "2026-10"}, token=t)
    check("POST 差异计算", st == 200 and d["count"] >= 4, d)
    st, lst = http("GET", "/api/variances?period=2026-10", token=t)
    closed = all(abs(x["checkDiff"]) < 0.02 for x in lst["list"])
    check("差异分解全部闭合", closed, [x["product"] for x in lst["list"] if abs(x["checkDiff"]) >= 0.02])

    st, d = http("POST", "/api/budgets", {"period": "2026-10", "center": "CC102",
                                          "subject": "S3004", "amount": 5000}, token=t)
    check("POST 预算设定", st == 200, d)
    st, d = http("GET", "/api/budgets/exec?period=2026-10", token=t)
    check("GET 预算执行", st == 200 and d["total"]["amount"] > 0, d)

    # 闸口负例
    st, d = http("POST", "/api/allocations/run", {"period": "2026-13"}, token=t)
    check("负例：无归集期间分摊被拒", st == 400, d)
    st, d = http("POST", "/api/expenses", {"period": "2026-10", "center": "CC101",
                                           "subject": "S3001", "amount": 99999,
                                           "status": "待审批"}, token=t)
    check("负例：超预算提交被阻断", st == 409 and "预算" in d.get("message", ""), d)
    st, d = http("POST", "/api/periods/2026-10/close", {}, token=t)
    check("负例：有待审批单据时不可结账", st == 409, d)

    st, d = http("POST", "/api/auth/logout", {}, token=t)
    check("POST /api/auth/logout", st == 200, d)
    st, d = http("GET", "/api/board", token=t)
    check("负例：注销后令牌失效", st == 401, d)

    print("-" * 74)
    print("通过 %d / %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("失败：", FAIL)
    s.shutdown()
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
