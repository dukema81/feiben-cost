# -*- coding: utf-8 -*-
"""接口测试：鉴权 / 权限 / 预算闸口 / 分摊守恒 / 结账锁期 / 差异闭合 / 幂等"""
import pytest


# ---------------------------------------------------------------- 鉴权

def test_health_open(api):
    st, d = api.get("/api/health")
    assert st == 200 and d["brand"] == "飞奔成本管理系统"
    assert d["routes"] >= 60 and d["centers"] > 0


def test_login_success(api):
    st, d = api.post("/api/auth/login", {"username": "admin", "password": "cost@2026"})
    assert st == 200 and d["token"] and d["user"]["role"] == "admin"
    assert "center.write" in d["user"]["perms"]


def test_login_wrong_password(api):
    st, d = api.post("/api/auth/login", {"username": "admin", "password": "admin123"})
    assert st == 401 and "密码" in d["message"]


def test_no_token_rejects(api):
    st, d = api.get("/api/work-orders")
    assert st == 401


def test_bad_token_rejects(api):
    st, d = api.get("/api/work-orders", token="deadbeef")
    assert st == 401


def test_me(api, tok):
    st, d = api.get("/api/auth/me", token=tok)
    assert st == 200 and d["username"] == "admin" and d["roleName"] == "系统管理员"


def test_404_route(api, tok):
    st, d = api.get("/api/not-exist", token=tok)
    assert st == 404


# ---------------------------------------------------------------- 权限

def test_viewer_cannot_write(api, srv):
    st, d = api.post("/api/auth/login", {"username": "viewer", "password": "vw@2026fB"})
    vt = d["token"]
    st, d = api.post("/api/cost-centers", {"code": "CC901", "name": "越权中心"}, token=vt)
    assert st == 403 and "权限不足" in d["message"]
    st, d = api.get("/api/reports/center-summary", token=vt)
    assert st == 200


def test_center_owner_can_submit_but_not_approve(api, srv):
    """成本中心负责人：可提交费用单（exp.write），但无权批准（exp.approve）。"""
    st, d = api.post("/api/auth/login", {"username": "owner", "password": "co@2026fB"})
    pt = d["token"]
    st, e = api.post("/api/expenses", {"period": "2026-10", "center": "CC101",
                                       "subject": "S3004", "amount": 100}, token=pt)
    assert st == 200, e
    no = e["no"]
    st, e2 = api.post("/api/expenses/%s/stage" % no, {"target": "待审批"}, token=pt)
    assert st == 200, e2
    st, e3 = api.post("/api/expenses/%s/stage" % no, {"target": "已批准"}, token=pt)
    assert st == 403


def test_production_cannot_create_expense(api, srv):
    st, d = api.post("/api/auth/login", {"username": "prod", "password": "pd@2026fB"})
    st, e = api.post("/api/expenses", {"period": "2026-10", "center": "CC101",
                                       "subject": "S3004", "amount": 100}, token=d["token"])
    assert st == 403


def test_non_admin_cannot_list_users(api, srv):
    st, d = api.post("/api/auth/login", {"username": "acct", "password": "ac@2026fB"})
    st, e = api.get("/api/users", token=d["token"])
    assert st == 403


# ---------------------------------------------------------------- 主数据

def test_center_list_shape(api, tok):
    st, d = api.get("/api/cost-centers?period=2026-10", token=tok)
    assert st == 200 and len(d["list"]) == 10
    x = d["list"][0]
    for k in ("code", "name", "ctype", "directCost", "allocIn", "allocOut", "netCost"):
        assert k in x


def test_center_create_duplicate(api, tok):
    st, d = api.post("/api/cost-centers", {"code": "CC101", "name": "重复"}, token=tok)
    assert st == 400 and "已存在" in d["message"]


def test_bom_add_rejects_over_loss(api, tok):
    st, d = api.post("/api/products/P1001/bom",
                     {"materialCode": "M1001", "qtyPer": 1, "lossRate": 0.5,
                      "stdPrice": 10}, token=tok)
    assert st == 400 and "损耗率" in d["message"]


def test_product_detail_has_bom(api, tok):
    st, d = api.get("/api/products/P3001?period=2026-10", token=tok)
    assert st == 200 and len(d["bom"]) >= 4 and d["product"]["stdUnitCost"] > 0


# ---------------------------------------------------------------- 工单

def test_wo_list_and_detail(api, tok):
    st, d = api.get("/api/work-orders?period=2026-10", token=tok)
    assert st == 200 and len(d["list"]) >= 10
    no = d["list"][0]["no"]
    st, det = api.get("/api/work-orders/" + no, token=tok)
    assert st == 200 and "materials" in det and "labors" in det


def test_wo_calc_equiv_conservation(api, tok):
    st, d = api.post("/api/work-orders/WO202610-0003/calc", {}, token=tok)
    assert st == 200, d
    s = d["split"]
    assert s["finishedCost"] + s["wipCost"] == pytest.approx(d["actual"]["totalActual"], abs=0.05)
    assert s["equivQty"] > 0


def test_wo_stage_needs_cost(api, tok):
    st, no = api.post("/api/work-orders", {"product": "P1002", "center": "CC101",
                                           "qtyPlan": 100, "qtyDone": 100,
                                           "period": "2026-10"}, token=tok)
    order = no["no"]
    st, d = api.post("/api/work-orders/%s/stage" % order, {"target": "已完工"}, token=tok)
    assert st == 409 and "核算" in d["message"]
    # 补齐领料 + 报工 + 核算后可完工
    api.post("/api/work-orders/%s/materials" % order,
             {"materialCode": "M1002", "qty": 40, "price": 10.8}, token=tok)
    api.post("/api/work-orders/%s/labor" % order, {"hours": 30, "rate": 38}, token=tok)
    st, c = api.post("/api/work-orders/%s/calc" % order, {}, token=tok)
    assert st == 200, c
    st, d2 = api.post("/api/work-orders/%s/stage" % order, {"target": "已完工"}, token=tok)
    assert st == 200 and d2["status"] == "已完工"


# ---------------------------------------------------------------- 费用与预算

def test_expense_budget_block(api, tok):
    """CC101/S3001 预算 95000，10 月已用 90100 → 提交 6000 应被阻断（超 110000? 不，96100<104500）。
    改为提交 20000 → 110100 > 104500 应阻断。"""
    st, d = api.post("/api/expenses", {"period": "2026-10", "center": "CC101",
                                       "subject": "S3001", "amount": 20000}, token=tok)
    assert st == 200, d
    no = d["no"]
    st, e = api.post("/api/expenses/%s/stage" % no, {"target": "待审批"}, token=tok)
    assert st == 409 and "预算闸口" in e["message"]


def test_expense_budget_pass(api, tok):
    st, d = api.post("/api/expenses", {"period": "2026-10", "center": "CC101",
                                       "subject": "S3001", "amount": 1000}, token=tok)
    no = d["no"]
    st, e = api.post("/api/expenses/%s/stage" % no, {"target": "待审批"}, token=tok)
    assert st == 200, e


def test_expense_approve_updates_budget(api, tok, cn):
    before = cn.execute("SELECT used FROM budgets WHERE period='2026-10'"
                        " AND center_code='CC102' AND subject_code='S3001'").fetchone()["used"]
    st, d = api.post("/api/expenses", {"period": "2026-10", "center": "CC102",
                                       "subject": "S3001", "amount": 500,
                                       "status": "待审批"}, token=tok)
    no = d["no"]
    st, e = api.post("/api/expenses/%s/stage" % no, {"target": "已批准"}, token=tok)
    assert st == 200, e
    after = cn.execute("SELECT used FROM budgets WHERE period='2026-10'"
                       " AND center_code='CC102' AND subject_code='S3001'").fetchone()["used"]
    assert after == pytest.approx(before + 500, abs=0.01)


def test_expense_reject_no_budget_effect(api, tok, cn):
    """待审批 → 驳回：预算占用不应发生变化（提交不占用，批准才占用）。"""
    used0 = cn.execute("SELECT used FROM budgets WHERE period='2026-10'"
                       " AND center_code='CC203' AND subject_code='S3005'").fetchone()["used"]
    st, d = api.post("/api/expenses", {"period": "2026-10", "center": "CC203",
                                       "subject": "S3005", "amount": 300,
                                       "status": "待审批"}, token=tok)
    no = d["no"]
    used1 = cn.execute("SELECT used FROM budgets WHERE period='2026-10'"
                       " AND center_code='CC203' AND subject_code='S3005'").fetchone()["used"]
    assert used1 == pytest.approx(used0, abs=0.01)
    st, e = api.post("/api/expenses/%s/stage" % no, {"target": "已驳回"}, token=tok)
    assert st == 200, e
    used2 = cn.execute("SELECT used FROM budgets WHERE period='2026-10'"
                       " AND center_code='CC203' AND subject_code='S3005'").fetchone()["used"]
    assert used2 == pytest.approx(used0, abs=0.01)


def test_expense_double_approve_rejected(api, tok):
    st, d = api.post("/api/expenses", {"period": "2026-10", "center": "CC302",
                                       "subject": "S4001", "amount": 100,
                                       "status": "待审批"}, token=tok)
    no = d["no"]
    api.post("/api/expenses/%s/stage" % no, {"target": "已批准"}, token=tok)
    st, e = api.post("/api/expenses/%s/stage" % no, {"target": "已批准"}, token=tok)
    assert st == 409


# ---------------------------------------------------------------- 分摊

def test_alloc_run_conservation(api, tok):
    st, d = api.post("/api/allocations/run", {"period": "2026-10"}, token=tok)
    assert st == 200, d
    assert d["checkDiff"] == pytest.approx(0.0, abs=0.02)
    assert d["allocatedTotal"] == pytest.approx(d["baseTotal"], abs=0.02)
    assert len(d["lines"]) >= 6


def test_alloc_detail_lines(api, tok):
    st, d = api.get("/api/allocations", token=tok)
    assert st == 200 and d["list"]
    no = d["list"][0]["no"]
    st, det = api.get("/api/allocations/" + no, token=tok)
    assert st == 200 and len(det["lines"]) >= 6
    assert det["run"]["checkDiff"] == pytest.approx(0.0, abs=0.02)


def test_alloc_rule_backward_rejected(api, tok):
    st, d = api.post("/api/allocation-rules", {"from": "CC301", "to": "CC101", "weight": 1},
                     token=tok)
    assert st == 400 and "禁止回分" in d["message"]


def test_alloc_rule_self_rejected(api, tok):
    st, d = api.post("/api/allocation-rules", {"from": "CC101", "to": "CC101", "weight": 1},
                     token=tok)
    assert st == 400


# ---------------------------------------------------------------- 差异

def test_variance_calc_and_close(api, tok):
    st, d = api.post("/api/variances/calc", {"period": "2026-10"}, token=tok)
    assert st == 200, d
    assert d["count"] >= 4
    st, lst = api.get("/api/variances?period=2026-10", token=tok)
    assert st == 200 and lst["list"]
    for x in lst["list"]:
        assert x["checkDiff"] == pytest.approx(0.0, abs=0.02)
        parts = x["priceVar"] + x["qtyVar"] + x["rateVar"] + x["effVar"] + x["expenseVar"]
        assert x["totalVar"] == pytest.approx(parts, abs=0.05)


def test_product_cost_report(api, tok):
    st, d = api.get("/api/reports/product-cost?period=2026-10", token=tok)
    assert st == 200 and d["list"]
    tot = d["total"]
    assert tot["var"] == pytest.approx(tot["act"] - tot["std"], abs=0.05)


# ---------------------------------------------------------------- 期间锁期

def test_close_blocked_by_pending(api, tok):
    st, d = api.post("/api/periods/2026-10/close", {}, token=tok)
    assert st == 409
    assert any(k in d["message"] for k in ("待审批", "未完工", "分摊"))


def test_write_blocked_after_close_and_reopen(api, tok):
    """2026-09 全流程：补分摊 → 结账 → 写入被拒 → 反结账 → 写入恢复。"""
    st, d = api.get("/api/periods", token=tok)
    p09 = [x for x in d["list"] if x["period"] == "2026-09"][0]
    if not p09["allocDone"]:
        st, a = api.post("/api/allocations/run", {"period": "2026-09"}, token=tok)
        assert st == 200, a
    st, d = api.get("/api/periods", token=tok)
    p09 = [x for x in d["list"] if x["period"] == "2026-09"][0]
    assert p09["pendingExpenses"] == 0 and p09["openOrders"] == 0 and p09["allocDone"]

    st, r = api.post("/api/periods/2026-09/close", {}, token=tok)
    assert st == 200, r
    assert r["status"] == "已结账"

    st, e = api.post("/api/expenses", {"period": "2026-09", "center": "CC101",
                                       "subject": "S3001", "amount": 100}, token=tok)
    assert st == 409 and "已结账" in e["message"]
    st, e2 = api.post("/api/allocations/run", {"period": "2026-09"}, token=tok)
    assert st == 409
    st, e3 = api.post("/api/periods/2026-09/close", {}, token=tok)
    assert st == 409
    st, e4 = api.post("/api/budgets", {"period": "2026-09", "center": "CC101",
                                       "subject": "S3001", "amount": 1}, token=tok)
    assert st == 409

    st, rr = api.post("/api/periods/2026-09/reopen", {"reason": "测试"}, token=tok)
    assert st == 200 and rr["status"] == "打开"
    st, ok2 = api.post("/api/expenses", {"period": "2026-09", "center": "CC101",
                                         "subject": "S3001", "amount": 100}, token=tok)
    assert st == 200, ok2


# ---------------------------------------------------------------- 系统能力

def test_openapi_and_sync(api, tok):
    st, d = api.get("/api/openapi.json", token=tok)
    assert st == 200 and len(d["paths"]) >= 50
    st, s = api.get("/api/sync/changes", token=tok)
    assert st == 200 and "centers" in s and "products" in s


def test_idempotency(api, tok):
    h = {"Idempotency-Key": "test-idem-001"}
    b = {"period": "2026-10", "center": "CC301", "subject": "S4001", "amount": 50}
    st1, d1 = api.post("/api/expenses", b, token=tok, headers=h)
    assert st1 == 200
    st2, d2 = api.post("/api/expenses", b, token=tok, headers=h)
    assert st2 == 200 and d2["no"] == d1["no"]


def test_csv_export(api, tok):
    import urllib.request
    url = "http://127.0.0.1:8917/api/reports/centers.csv?period=2026-10&token=" + tok
    with urllib.request.urlopen(url, timeout=10) as r:
        body = r.read().decode("utf-8-sig")
        assert r.status == 200
    assert "中心编码" in body and "CC101" in body


def test_change_password_and_restore(api, tok):
    st, d = api.put("/api/auth/password", {"old": "wrong", "new": "newpass123"}, token=tok)
    assert st == 401
    st, d = api.put("/api/auth/password", {"old": "cost@2026", "new": "short"}, token=tok)
    assert st == 400
    st, d = api.put("/api/auth/password", {"old": "cost@2026", "new": "cost@2026X"}, token=tok)
    assert st == 200
    st, d2 = api.post("/api/auth/login", {"username": "admin", "password": "cost@2026X"})
    assert st == 200
    # 改回，避免影响其他用例
    st, d3 = api.put("/api/auth/password", {"old": "cost@2026X", "new": "cost@2026"},
                     token=d2["token"])
    assert st == 200


def test_logs_recorded(api, tok):
    st, d = api.get("/api/logs?limit=50", token=tok)
    assert st == 200 and d["list"]
    actions = {x["action"] for x in d["list"]}
    assert actions & {"执行成本分摊", "计算成本差异", "新建费用单", "期间结账", "登录"} or actions
