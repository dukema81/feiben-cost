# -*- coding: utf-8 -*-
"""业务内核单元测试：标准成本 / 实际成本 / 约当产量 / 差异分解 / 阶梯分摊 / 闸口 / 权限"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import cost  # noqa: E402


# ---------------------------------------------------------------- 标准成本卡

def test_std_card_basic():
    bom = [{"qty_per": 0.4, "loss_rate": 0.05, "std_price": 10, "material_code": "M1"},
           {"qty_per": 2, "loss_rate": 0, "std_price": 3, "material_code": "M2"}]
    c = cost.std_card(bom, std_hours=0.5, labor_rate=38, oh_rate=26)
    # 材料 = 0.4*1.05*10 + 2*3 = 4.2 + 6 = 10.2
    assert c["matCost"] == pytest.approx(10.2, abs=0.01)
    assert c["laborCost"] == pytest.approx(19.0, abs=0.01)
    assert c["ohCost"] == pytest.approx(13.0, abs=0.01)
    assert c["unitCost"] == pytest.approx(42.2, abs=0.01)


def test_std_card_empty_bom():
    c = cost.std_card([], 1.0, 30, 20)
    assert c["matCost"] == 0 and c["unitCost"] == pytest.approx(50.0)


def test_std_card_loss_increases_material():
    a = cost.std_card([{"qty_per": 1, "loss_rate": 0, "std_price": 10}], 0, 0, 0)
    b = cost.std_card([{"qty_per": 1, "loss_rate": 0.2, "std_price": 10}], 0, 0, 0)
    assert b["matCost"] == pytest.approx(a["matCost"] * 1.2)


def test_std_card_detail_amounts():
    bom = [{"qty_per": 1, "loss_rate": 0.1, "std_price": 5, "material_code": "M9",
            "material_name": "测试料"}]
    c = cost.std_card(bom, 0, 0, 0)
    assert c["matDetail"][0]["qty"] == pytest.approx(1.1, abs=1e-6)
    assert c["matDetail"][0]["amount"] == pytest.approx(5.5, abs=0.01)
    assert c["matDetail"][0]["materialCode"] == "M9"


# ---------------------------------------------------------------- 实际成本

def test_actual_cost_amount_or_qty_price():
    mats = [{"qty": 2, "price": 10}, {"qty": 1, "price": 5, "amount": 6}]
    labs = [{"hours": 2, "rate": 30}, {"hours": 1, "rate": 50, "amount": 60}]
    a = cost.actual_cost(mats, labs, oh_rate=20)
    assert a["matActual"] == pytest.approx(26.0)
    assert a["laborActual"] == pytest.approx(120.0)
    assert a["laborHours"] == pytest.approx(3.0)
    assert a["ohActual"] == pytest.approx(60.0)
    assert a["totalActual"] == pytest.approx(206.0)


def test_actual_cost_empty():
    a = cost.actual_cost([], [], 20)
    assert a["totalActual"] == 0 and a["laborHours"] == 0


# ---------------------------------------------------------------- 约当产量

def test_equiv_units_full_completion():
    eu = cost.equivalent_units(100, 100, 1.0)
    assert eu == {"wipQty": 0.0, "equivQty": 100.0}


def test_equiv_units_partial_wip():
    eu = cost.equivalent_units(80, 100, 0.5)
    assert eu["wipQty"] == pytest.approx(20.0)
    assert eu["equivQty"] == pytest.approx(90.0)


def test_equiv_units_reject_over_done():
    assert cost.equivalent_units(120, 100, 1.0) is None


def test_equiv_units_reject_bad_rate():
    assert cost.equivalent_units(50, 100, 0) is None
    assert cost.equivalent_units(50, 100, 1.5) is None


def test_equiv_units_reject_zero_plan():
    assert cost.equivalent_units(0, 0, 1.0) is None


def test_split_cost_conservation():
    s = cost.split_cost(9000, 80, 100, 0.5)
    assert s["equivQty"] == pytest.approx(90.0)
    assert s["unitCost"] == pytest.approx(100.0)
    assert s["finishedCost"] == pytest.approx(8000.0)
    assert s["wipCost"] == pytest.approx(1000.0)
    assert s["finishedCost"] + s["wipCost"] == pytest.approx(9000.0, abs=0.01)


def test_split_cost_invalid():
    assert cost.split_cost(100, 200, 100, 1.0) is None


# ---------------------------------------------------------------- 材料差异

def test_material_variance_identity():
    v = cost.material_variance(100, 10, 110, 11)
    assert v["priceVar"] == pytest.approx(110.0)     # (11-10)*110
    assert v["qtyVar"] == pytest.approx(100.0)       # (110-100)*10
    assert v["totalVar"] == pytest.approx(210.0)     # 1210 - 1000
    assert v["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_material_variance_favorable():
    v = cost.material_variance(100, 10, 90, 9)
    assert v["totalVar"] < 0
    assert v["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_material_variance_zero():
    v = cost.material_variance(100, 10, 100, 10)
    assert v["totalVar"] == 0 and v["checkDiff"] == 0


# ---------------------------------------------------------------- 人工差异

def test_labor_variance_identity():
    v = cost.labor_variance(200, 30, 210, 33)
    assert v["rateVar"] == pytest.approx(630.0)      # (33-30)*210
    assert v["effVar"] == pytest.approx(300.0)       # (210-200)*30
    assert v["totalVar"] == pytest.approx(930.0)     # 210*33 - 200*30
    assert v["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_labor_variance_efficiency_only():
    v = cost.labor_variance(100, 30, 120, 30)
    assert v["rateVar"] == 0
    assert v["effVar"] == pytest.approx(600.0)


# ---------------------------------------------------------------- 制费差异

def test_oh_variance_identity():
    v = cost.oh_variance(26, 100, 110, 3000)
    assert v["expenseVar"] == pytest.approx(3000 - 110 * 26)
    assert v["effVar"] == pytest.approx(10 * 26)
    assert v["totalVar"] == pytest.approx(3000 - 100 * 26)
    assert v["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_oh_variance_zero_spending_under_std_rate():
    v = cost.oh_variance(26, 100, 120, 120 * 26)
    assert v["expenseVar"] == pytest.approx(0.0, abs=0.01)
    assert v["effVar"] == pytest.approx(20 * 26)


# ---------------------------------------------------------------- 差异等级与产品汇总

def test_variance_level_bands():
    assert cost.variance_level(0, 1000) == "微小"
    assert cost.variance_level(50, 1000) == "不利"
    assert cost.variance_level(150, 1000) == "重大不利"
    assert cost.variance_level(-50, 1000) == "有利"
    assert cost.variance_level(-150, 1000) == "重大有利"


def test_variance_level_zero_base_safe():
    assert cost.variance_level(0, 0) == "微小"


def test_product_variance_closes():
    mat = cost.material_variance(100, 10, 110, 11)      # +210
    lab = cost.labor_variance(200, 30, 210, 33)         # +930
    oh = cost.oh_variance(26, 200, 210, 5460)           # +260
    # 标准总额 50×100=5000，三项合计 1400 → 实际总额 6400
    pv = cost.product_variance(50, 6400, 100, mat, lab, oh)
    total = pv["priceVar"] + pv["qtyVar"] + pv["rateVar"] + pv["effVar"] + pv["expenseVar"]
    assert pv["totalVar"] == pytest.approx(1400.0)
    assert pv["totalVar"] == pytest.approx(total, abs=0.05)
    assert pv["checkDiff"] == pytest.approx(0.0, abs=0.05)
    assert pv["stdTotal"] == pytest.approx(5000.0)


# ---------------------------------------------------------------- 阶梯分摊

ORDERS = {"CC201": 1, "CC202": 2, "CC101": 5, "CC102": 5, "CC301": 6}
DIRECT = {"CC201": 60000, "CC202": 20000, "CC101": 100000, "CC301": 5000}
EDGES = [
    {"from_center": "CC201", "to_center": "CC101", "weight": 1},
    {"from_center": "CC201", "to_center": "CC102", "weight": 1},
    {"from_center": "CC202", "to_center": "CC101", "weight": 3},
    {"from_center": "CC202", "to_center": "CC102", "weight": 1},
]


def test_step_down_conservation():
    r = cost.step_down(DIRECT, ORDERS, EDGES)
    assert r["ok"] is True
    assert r["baseTotal"] == pytest.approx(80000.0)
    assert r["allocatedTotal"] == pytest.approx(80000.0, abs=0.01)
    assert r["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_step_down_two_steps_amounts():
    r = cost.step_down(DIRECT, ORDERS, EDGES)
    lines = {(x["fromCenter"], x["toCenter"]): x["amount"] for x in r["lines"]}
    assert lines[("CC201", "CC101")] == pytest.approx(30000.0)
    assert lines[("CC201", "CC102")] == pytest.approx(30000.0)
    # CC202 自身 20000 + 上游 0 = 20000，按 3:1 分
    assert lines[("CC202", "CC101")] == pytest.approx(15000.0)
    assert lines[("CC202", "CC102")] == pytest.approx(5000.0)


def test_step_down_upstream_pool_included():
    """上游分入后，下游中心的待摊金额应包含分入额。"""
    direct = {"CC201": 10000, "CC202": 0}
    edges = [
        {"from_center": "CC201", "to_center": "CC202", "weight": 1},
        {"from_center": "CC202", "to_center": "CC101", "weight": 1},
    ]
    orders = {"CC201": 1, "CC202": 2, "CC101": 5}
    r = cost.step_down(direct, orders, edges)
    assert r["ok"]
    assert r["allocatedTotal"] == pytest.approx(20000.0, abs=0.01)
    assert r["checkDiff"] == pytest.approx(0.0, abs=0.01)


def test_step_down_reject_backward():
    edges = [{"from_center": "CC301", "to_center": "CC101", "weight": 1}]
    r = cost.step_down(DIRECT, ORDERS, edges)
    assert r["ok"] is False
    assert "禁止回分" in r["error"]


def test_step_down_reject_self():
    r = cost.step_down(DIRECT, ORDERS, [{"from_center": "CC101", "to_center": "CC101"}])
    assert r["ok"] is False and "自己" in r["error"]


def test_step_down_reject_duplicate():
    e = [{"from_center": "CC201", "to_center": "CC101"},
         {"from_center": "CC201", "to_center": "CC101"}]
    assert cost.check_step_rules(ORDERS, e) is not None


def test_step_down_orphans_reported():
    direct = {"CC201": 1000, "CC999": 500}
    orders = dict(ORDERS, CC999=9)
    r = cost.step_down(direct, orders, [{"from_center": "CC201", "to_center": "CC101",
                                         "weight": 1}])
    assert "CC999" in r["orphans"]


def test_step_down_tail_absorbed():
    """不能整除时末位吸收尾差，保证守恒。"""
    direct = {"CC201": 100}
    edges = [{"from_center": "CC201", "to_center": "CC101", "weight": 1},
             {"from_center": "CC201", "to_center": "CC102", "weight": 1},
             {"from_center": "CC201", "to_center": "CC103", "weight": 1}]
    orders = dict(ORDERS, CC103=5)
    r = cost.step_down(direct, orders, edges)
    assert r["checkDiff"] == pytest.approx(0.0, abs=0.005)
    assert sum(x["amount"] for x in r["lines"]) == pytest.approx(100.0, abs=0.005)


# ---------------------------------------------------------------- 预算

def test_budget_state_levels():
    assert cost.budget_state(100, 50)["level"] == "正常"
    assert cost.budget_state(100, 92)["level"] == "预警"
    assert cost.budget_state(100, 100)["level"] == "超支"
    assert cost.budget_state(100, 115)["level"] == "阻断区"
    assert cost.budget_state(100, 115)["block"] is True


def test_budget_state_no_budget():
    s = cost.budget_state(0, 50)
    assert s["level"] == "未设预算"


def test_budget_left_negative():
    assert cost.budget_state(100, 130)["left"] == pytest.approx(-30.0)


# ---------------------------------------------------------------- 闸口

def test_expense_gate_budget_block():
    err = cost.expense_gate("草稿", "待审批", {"amount": 20000, "budget_amount": 10000,
                                              "used": 9000, "block_rate": 1.1})
    assert err and "预算闸口" in err


def test_expense_gate_budget_pass():
    err = cost.expense_gate("草稿", "待审批", {"amount": 500, "budget_amount": 10000,
                                              "used": 9000, "block_rate": 1.1})
    assert err is None


def test_expense_gate_period_closed():
    err = cost.expense_gate("草稿", "待审批", {"amount": 1, "period_closed": True})
    assert err and "已结账" in err


def test_expense_gate_approve_needs_perm():
    assert cost.expense_gate("待审批", "已批准", {"amount": 1, "isApprover": False})
    assert cost.expense_gate("待审批", "已批准", {"amount": 1, "isApprover": True}) is None


def test_expense_gate_zero_amount():
    assert cost.expense_gate("草稿", "待审批", {"amount": 0})


def test_wo_gate_requires_cost():
    err = cost.wo_gate("在生产", "已完工", {"qty_done": 10, "qty_plan": 10, "wip_rate": 1,
                                          "has_cost": False})
    assert err and "核算" in err


def test_wo_gate_over_done():
    err = cost.wo_gate("在生产", "已完工", {"qty_done": 11, "qty_plan": 10, "wip_rate": 1,
                                          "has_cost": True})
    assert err and "超过计划" in err


def test_wo_gate_ok():
    assert cost.wo_gate("在生产", "已完工", {"qty_done": 10, "qty_plan": 10, "wip_rate": 1,
                                           "has_cost": True}) is None


def test_close_gate_three_checks():
    assert "待审批" in cost.close_gate({"pending_expenses": 1, "open_orders": 0,
                                        "alloc_done": True})
    assert "未完工" in cost.close_gate({"pending_expenses": 0, "open_orders": 2,
                                        "alloc_done": True})
    assert "分摊" in cost.close_gate({"pending_expenses": 0, "open_orders": 0,
                                      "alloc_done": False})
    assert cost.close_gate({"pending_expenses": 0, "open_orders": 0, "alloc_done": True}) is None


def test_close_gate_already_closed():
    assert "已结账" in cost.close_gate({"period_closed": True})


# ---------------------------------------------------------------- 权限 / 工具

def test_admin_has_all_perms():
    for p in cost.PERMS:
        assert cost.can("admin", p)


def test_viewer_read_only():
    assert cost.can("viewer", "report.read")
    assert not cost.can("viewer", "exp.write")
    assert not cost.can("viewer", "period.close")


def test_production_cannot_approve():
    assert cost.can("production", "wo.write")
    assert not cost.can("production", "exp.approve")


def test_accountant_can_alloc_write():
    assert cost.can("accountant", "alloc.write")
    assert not cost.can("accountant", "period.close")


def test_prev_period_cross_year():
    assert cost.prev_period("2026-01", 1) == "2025-12"
    assert cost.prev_period("2026-03", 5) == "2025-10"


def test_unit_margin():
    m = cost.unit_margin(100, 70)
    assert m["grossProfit"] == pytest.approx(30.0)
    assert m["grossRate"] == pytest.approx(0.3)


def test_safe_num_and_q2():
    assert cost.safe_num("abc", 7) == 7
    assert cost.safe_num(None) == 0.0
    assert cost.q2(1.005) == pytest.approx(1.0, abs=0.02)
    assert cost.q2(-0.001) == 0.0
