# -*- coding: utf-8 -*-
"""飞奔成本管理系统 · 纯函数业务内核

职责边界：只做算法与口径，不碰数据库、不碰 HTTP。
覆盖：标准成本卡 / 实际成本归集 / 约当产量 / 差异四维分解 / 阶梯分摊 / 预算与结账闸口 / 权限。
所有函数可独立单测，误差阈值统一 0.02 元。
"""

BRAND = "飞奔成本管理系统"
VERSION = "1.0.0"
TOL = 0.02


# ---------------------------------------------------------------- 基础工具

def safe_num(v, default=0.0):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def q2(v):
    """金额统一两位小数，消除 -0.0。"""
    f = round(safe_num(v), 2)
    return 0.0 if f == 0 else f


def today():
    import datetime
    return datetime.date.today().isoformat()


def now_str():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cur_period():
    return today()[:7]


def prev_period(period, n=1):
    """上月/前 N 月，period 形如 2026-10。"""
    try:
        y, m = [int(x) for x in period.split("-")[:2]]
    except (ValueError, AttributeError):
        return cur_period()
    y, m = y, m - n
    while m <= 0:
        m += 12
        y -= 1
    return "%04d-%02d" % (y, m)


def doc_no(prefix, day, seq):
    return "%s%s-%04d" % (prefix, day.replace("-", ""), int(seq))


def ok_diff(a, b, tol=TOL):
    return abs(safe_num(a) - safe_num(b)) <= tol


# ---------------------------------------------------------------- 状态机

CENTER_TYPES = ["生产", "辅助", "管理", "销售", "研发"]
WO_STATES = ["草稿", "在生产", "已完工", "已关闭"]
EXP_STATES = ["草稿", "待审批", "已批准", "已驳回"]
PERIOD_STATES = ["打开", "已结账"]
SOURCES = ["手工", "采购", "工资", "折旧", "报销", "摊销", "转入"]
SUBJECT_CATEGORIES = ["材料", "人工", "制造费用", "期间费用"]
DRIVERS = ["人工工时", "机器工时", "面积", "人数", "直接成本", "用量"]


def can_move(chain, cur, nxt):
    if cur not in chain or nxt not in chain:
        return False
    return chain.index(nxt) > chain.index(cur)


def wo_gate(cur, target, ctx):
    """工单状态闸口。ctx: qty_done, qty_plan, wip_rate, has_cost, period_closed"""
    ctx = ctx or {}
    if not can_move(WO_STATES, cur, target):
        return "工单不允许从「%s」变更为「%s」" % (cur, target)
    if ctx.get("period_closed"):
        return "期间已结账，禁止变更工单状态"
    if target == "在生产":
        if safe_num(ctx.get("qty_plan")) <= 0:
            return "工单闸口：计划数量必须大于 0"
    if target == "已完工":
        if safe_num(ctx.get("qty_done")) <= 0:
            return "完工闸口：完工数量必须大于 0"
        if safe_num(ctx.get("qty_done")) > safe_num(ctx.get("qty_plan")):
            return "完工闸口：完工数量（%.2f）超过计划数量（%.2f）" % (
                safe_num(ctx.get("qty_done")), safe_num(ctx.get("qty_plan")))
        rate = safe_num(ctx.get("wip_rate"), 1)
        if rate <= 0 or rate > 1:
            return "完工闸口：在制品完工进度必须在 (0, 1] 区间"
        if not ctx.get("has_cost"):
            return "完工闸口：尚未核算实际成本，不能完工"
    if target == "已关闭":
        if cur != "已完工":
            return "关闭闸口：必须先完工才能关闭工单"
    return None


def expense_gate(cur, target, ctx):
    """费用单状态闸口。

    ctx: amount, period_closed, budget_amount, used, block_rate, isApprover
    """
    ctx = ctx or {}
    if cur == target:
        return "状态未变更"
    if ctx.get("period_closed"):
        return "期间已结账，禁止变更费用单"
    if target in ("待审批", "已批准"):
        if safe_num(ctx.get("amount")) <= 0:
            return "费用闸口：金额必须大于 0"
    if target == "待审批":
        if cur not in ("草稿", "已驳回"):
            return "只有草稿或已驳回的费用单可以提交"
        amt = safe_num(ctx.get("amount"))
        budget = safe_num(ctx.get("budget_amount"))
        used = safe_num(ctx.get("used"))
        block_rate = safe_num(ctx.get("block_rate"), 1.1)
        if budget > 0 and used + amt > budget * block_rate:
            return "预算闸口：提交后将占用 %.2f 元，超出预算（%.2f）的 %.0f%%，已被阻断" % (
                used + amt, budget, (block_rate - 1) * 100)
    if target == "已批准":
        if cur != "待审批":
            return "只有待审批单可以批准"
        if not ctx.get("isApprover"):
            return "只有审批人可以批准"
    if target == "已驳回":
        if cur != "待审批":
            return "只有待审批单可以驳回"
        if not ctx.get("isApprover"):
            return "只有审批人可以驳回"
    return None


def close_gate(ctx):
    """期末结账闸口。ctx: pending_expenses, open_orders, alloc_done, period_closed"""
    ctx = ctx or {}
    if ctx.get("period_closed"):
        return "该期间已结账，无需重复结账"
    if safe_num(ctx.get("pending_expenses")) > 0:
        return "结账闸口：仍有 %d 张待审批费用单，请先处理" % safe_num(ctx.get("pending_expenses"))
    if safe_num(ctx.get("open_orders")) > 0:
        return "结账闸口：仍有 %d 张未完工工单，请先完工或关闭" % safe_num(ctx.get("open_orders"))
    if not ctx.get("alloc_done"):
        return "结账闸口：本期尚未执行成本分摊"
    return None


# ---------------------------------------------------------------- 标准成本

def std_card(bom_lines, std_hours, labor_rate, oh_rate):
    """标准成本卡（单位成本）。

    bom_lines: [{qty_per, loss_rate, std_price}]；std_hours 单件标准工时。
    返回 {matCost, laborCost, ohCost, unitCost, matDetail}
    """
    mat = 0.0
    detail = []
    for b in bom_lines or []:
        qty = safe_num(b.get("qty_per")) * (1 + safe_num(b.get("loss_rate")))
        price = safe_num(b.get("std_price"))
        amount = qty * price
        mat += amount
        detail.append({"materialCode": b.get("material_code") or b.get("materialCode", ""),
                       "materialName": b.get("material_name") or b.get("materialName", ""),
                       "qty": round(qty, 4), "price": q2(price), "amount": q2(amount)})
    hours = safe_num(std_hours)
    labor = hours * safe_num(labor_rate)
    oh = hours * safe_num(oh_rate)
    return {"matCost": q2(mat), "laborCost": q2(labor), "ohCost": q2(oh),
            "unitCost": q2(mat + labor + oh), "matDetail": detail}


# ---------------------------------------------------------------- 实际成本

def actual_cost(materials, labors, oh_rate):
    """工单实际成本归集。

    materials: [{qty, price, amount}]；labors: [{hours, rate, amount}]
    金额优先取 amount，缺失时按 量×价 计算。
    """
    mat = 0.0
    for m in materials or []:
        amt = m.get("amount")
        mat += safe_num(amt) if amt not in (None, "") else \
            safe_num(m.get("qty")) * safe_num(m.get("price"))
    labor = 0.0
    hours = 0.0
    for l in labors or []:
        h = safe_num(l.get("hours"))
        r = safe_num(l.get("rate"))
        hours += h
        amt = l.get("amount")
        labor += safe_num(amt) if amt not in (None, "") else h * r
    oh = hours * safe_num(oh_rate)
    return {"matActual": q2(mat), "laborActual": q2(labor), "ohActual": q2(oh),
            "totalActual": q2(mat + labor + oh), "laborHours": round(hours, 2)}


def equivalent_units(qty_done, qty_plan, wip_rate):
    """约当产量法。返回 {wipQty, equivQty}；非法入参返回 None 由调用方报错。"""
    done = safe_num(qty_done)
    plan = safe_num(qty_plan)
    rate = safe_num(wip_rate, 1)
    if done < 0 or plan <= 0 or done > plan:
        return None
    if rate <= 0 or rate > 1:
        return None
    wip = round(plan - done, 4)
    equiv = round(done + wip * rate, 4)
    if equiv <= 0:
        return None
    return {"wipQty": wip, "equivQty": equiv}


def split_cost(total, qty_done, qty_plan, wip_rate):
    """完工转出 / 在制成本拆分。"""
    eu = equivalent_units(qty_done, qty_plan, wip_rate)
    if eu is None:
        return None
    total = safe_num(total)
    unit = total / eu["equivQty"]
    finished = unit * safe_num(qty_done)
    wip_cost = total - finished
    return {"wipQty": eu["wipQty"], "equivQty": eu["equivQty"],
            "unitCost": round(unit, 4), "finishedCost": q2(finished), "wipCost": q2(wip_cost)}


# ---------------------------------------------------------------- 差异分解

def material_variance(std_qty, std_price, act_qty, act_price):
    """材料两因素法：价差 + 量差 = 总差异（强制校核）。"""
    sq, sp = safe_num(std_qty), safe_num(std_price)
    aq, ap = safe_num(act_qty), safe_num(act_price)
    price_var = (ap - sp) * aq
    qty_var = (aq - sq) * sp
    total = aq * ap - sq * sp
    return {"priceVar": q2(price_var), "qtyVar": q2(qty_var), "totalVar": q2(total),
            "checkDiff": q2(total - price_var - qty_var)}


def labor_variance(std_hours, std_rate, act_hours, act_rate):
    """人工：工资率差异 + 效率差异 = 总差异。"""
    sh, sr = safe_num(std_hours), safe_num(std_rate)
    ah, ar = safe_num(act_hours), safe_num(act_rate)
    rate_var = (ar - sr) * ah
    eff_var = (ah - sh) * sr
    total = ah * ar - sh * sr
    return {"rateVar": q2(rate_var), "effVar": q2(eff_var), "totalVar": q2(total),
            "checkDiff": q2(total - rate_var - eff_var)}


def oh_variance(std_rate, std_hours, act_hours, act_oh, budget_oh=None):
    """制造费用差异（预定分配率法）：

    - 耗费差异 = 实际制费 − 实际工时 × 标准分配率
    - 效率差异 = (实际工时 − 标准工时) × 标准分配率
    两项之和必须等于「实际制费 − 标准工时 × 标准分配率」，保证守恒。
    budget_oh 仅用于预算对比（budgetVar），不参与分解。
    """
    sr = safe_num(std_rate)
    sh, ah = safe_num(std_hours), safe_num(act_hours)
    ac = safe_num(act_oh)
    expense_var = ac - ah * sr
    eff_var = (ah - sh) * sr
    total = ac - sh * sr
    return {"expenseVar": q2(expense_var), "effVar": q2(eff_var), "totalVar": q2(total),
            "budgetVar": q2(ac - safe_num(budget_oh)) if budget_oh is not None else None,
            "checkDiff": q2(total - expense_var - eff_var)}


def variance_level(total_var, std_total):
    """差异等级：按差异额与标准成本的比例分档（正数为不利差异）。"""
    base = abs(safe_num(std_total)) or 1.0
    rate = safe_num(total_var) / base
    if abs(rate) < 0.01:
        return "微小"
    if rate > 0:
        return "重大不利" if rate >= 0.10 else "不利"
    return "重大有利" if rate <= -0.10 else "有利"


def product_variance(std_unit_cost, act_total, qty, mat=None, labor=None, oh=None):
    """产品成本维度汇总差异。

    std_unit_cost 单位标准成本；act_total 实际总成本；qty 实际产量。
    mat/labor/oh 为三元素材明细，用于逐项分解（可缺省）。
    """
    std_total = safe_num(std_unit_cost) * safe_num(qty)
    act_total = safe_num(act_total)
    total = act_total - std_total
    price_var = qty_var = rate_var = eff_var = expense_var = 0.0
    if mat:
        price_var = safe_num(mat.get("priceVar"))
        qty_var = safe_num(mat.get("qtyVar"))
    if labor:
        rate_var = safe_num(labor.get("rateVar"))
        eff_var = safe_num(labor.get("effVar"))
    if oh:
        expense_var = safe_num(oh.get("expenseVar"))
        eff_var = safe_num(eff_var) + safe_num(oh.get("effVar"))
    decomposed = price_var + qty_var + rate_var + eff_var + expense_var
    return {"stdTotal": q2(std_total), "actTotal": q2(act_total), "totalVar": q2(total),
            "priceVar": q2(price_var), "qtyVar": q2(qty_var), "rateVar": q2(rate_var),
            "effVar": q2(eff_var), "expenseVar": q2(expense_var),
            "checkDiff": q2(total - decomposed), "level": variance_level(total, std_total)}


# ---------------------------------------------------------------- 阶梯分摊

def check_step_rules(orders, edges):
    """分摊规则合法性：禁止回分、禁止自摊、禁止重复边。

    orders: {center: alloc_order}；edges: [{from_center, to_center}]
    """
    seen = set()
    for e in edges or []:
        f, t = e.get("from_center") or e.get("from"), e.get("to_center") or e.get("to")
        if f == t:
            return "分摊规则非法：%s 不能向自己分摊" % f
        if (f, t) in seen:
            return "分摊规则重复：%s → %s" % (f, t)
        seen.add((f, t))
        of, ot = orders.get(f), orders.get(t)
        if of is None or ot is None:
            return "分摊规则引用了不存在的成本中心：%s / %s" % (f, t)
        if ot <= of:
            return "阶梯分摊禁止回分：%s（顺序 %s）→ %s（顺序 %s），只能分给顺序更大的中心" % (
                f, of, t, ot)
    return None


def step_down(direct, orders, edges):
    """阶梯分摊法（顺序法）。

    direct: {center: 直接归集金额}
    orders: {center: 分摊顺序}
    edges:  [{from_center, to_center, weight, driver}]
    返回 {ok, error, lines, baseTotal, allocatedTotal, checkDiff, orphans}
    """
    err = check_step_rules(orders, edges)
    if err:
        return {"ok": False, "error": err, "lines": [], "baseTotal": 0.0,
                "allocatedTotal": 0.0, "checkDiff": 0.0, "orphans": []}
    pool = {c: q2(v) for c, v in (direct or {}).items()}
    out_edges = {}
    for e in edges or []:
        f = e.get("from_center") or e.get("from")
        out_edges.setdefault(f, []).append(e)
    aux = sorted([c for c in out_edges], key=lambda c: orders.get(c, 9))
    orphans = [c for c in (direct or {}) if c not in out_edges and safe_num(direct.get(c)) > 0]
    lines = []
    base_total = 0.0
    allocated_total = 0.0
    for step, c in enumerate(aux, 1):
        amount = q2(pool.get(c, 0))
        base_total += amount
        targets = out_edges.get(c, [])
        total_w = sum(safe_num(t.get("weight"), 1) for t in targets) or float(len(targets) or 1)
        acc = 0.0
        for i, t in enumerate(targets):
            w = safe_num(t.get("weight"), 1)
            to = t.get("to_center") or t.get("to")
            part = q2(amount * w / total_w) if total_w else 0.0
            if i == len(targets) - 1:                      # 末位吸收尾差，保证守恒
                part = q2(amount - acc)
            acc = q2(acc + part)
            pool[to] = q2(pool.get(to, 0) + part)
            allocated_total = q2(allocated_total + part)
            lines.append({"step": step, "fromCenter": c, "toCenter": to,
                          "driver": t.get("driver") or "", "weight": round(w, 4),
                          "baseAmount": amount, "amount": part})
        pool[c] = 0.0
    return {"ok": True, "error": None, "lines": lines, "baseTotal": q2(base_total),
            "allocatedTotal": q2(allocated_total),
            "checkDiff": q2(base_total - allocated_total), "orphans": orphans}


# ---------------------------------------------------------------- 预算 / 毛利

def budget_state(amount, used, warn_rate=0.9, block_rate=1.1):
    """预算执行状态：{rate, level, left, block}"""
    amt, usd = safe_num(amount), safe_num(used)
    if amt <= 0:
        return {"rate": 0.0, "level": "未设预算", "left": 0.0, "block": False}
    rate = usd / amt
    if rate >= block_rate:
        level = "阻断区"
    elif rate >= 1:
        level = "超支"
    elif rate >= warn_rate:
        level = "预警"
    else:
        level = "正常"
    return {"rate": round(rate, 4), "level": level, "left": q2(amt - usd),
            "block": used > amt * block_rate}


def unit_margin(list_price, unit_cost):
    """单位毛利与毛利率。"""
    p, c = safe_num(list_price), safe_num(unit_cost)
    gross = p - c
    return {"grossProfit": q2(gross), "grossRate": round(gross / p, 4) if p else 0.0}


# ---------------------------------------------------------------- 权限

PERMS = ["center.read", "center.write", "subject.read", "subject.write",
         "product.read", "product.write", "std.read", "std.write",
         "wo.read", "wo.write", "exp.read", "exp.write", "exp.approve",
         "alloc.read", "alloc.write", "budget.read", "budget.write",
         "report.read", "period.close", "admin"]

ROLES = {
    "admin": {"name": "系统管理员", "perms": PERMS},
    "cost_manager": {"name": "成本经理", "perms": [
        "center.read", "center.write", "subject.read", "subject.write",
        "product.read", "product.write", "std.read", "std.write", "wo.read", "wo.write",
        "exp.read", "exp.write", "exp.approve", "alloc.read", "alloc.write",
        "budget.read", "budget.write", "report.read", "period.close"]},
    "accountant": {"name": "成本会计", "perms": [
        "center.read", "subject.read", "product.read", "std.read", "std.write",
        "wo.read", "exp.read", "exp.write", "exp.approve", "alloc.read", "alloc.write",
        "budget.read", "report.read"]},
    "center_owner": {"name": "成本中心负责人", "perms": [
        "center.read", "subject.read", "product.read", "std.read", "wo.read",
        "exp.read", "exp.write", "alloc.read", "budget.read", "report.read"]},
    "production": {"name": "生产统计", "perms": [
        "center.read", "subject.read", "product.read", "std.read",
        "wo.read", "wo.write", "exp.read", "report.read"]},
    "viewer": {"name": "只读用户", "perms": [
        "center.read", "subject.read", "product.read", "std.read", "wo.read",
        "exp.read", "alloc.read", "budget.read", "report.read"]},
    "auditor": {"name": "审计", "perms": [
        "center.read", "subject.read", "product.read", "std.read", "wo.read",
        "exp.read", "alloc.read", "budget.read", "report.read"]},
}


def perms_of(role):
    return ROLES.get(role, {}).get("perms", [])


def can(role, perm):
    return perm in perms_of(role)


# ---------------------------------------------------------------- 业务规则

DEFAULT_RULES = [
    ("warn_rate", "预算预警线", "预算", "0.9", "比例", "执行率达 90% 提示预警"),
    ("block_rate", "预算阻断倍率", "预算", "1.1", "倍数", "超出预算 10% 阻断费用提交"),
    ("variance_alert", "差异重大线", "差异", "0.10", "比例", "差异/标准成本 ≥10% 判重大"),
    ("wip_default", "默认在制完工进度", "工单", "1.0", "比例", "在制品按 100% 约当"),
    ("oh_base", "制造费用分配基础", "核算", "人工工时", "", "预定分配率口径"),
    ("std_version_policy", "标准成本版本策略", "核算", "按月版本", "", "每期可多版本，仅一个生效"),
    ("loss_limit", "综合损耗率上限", "主数据", "0.2", "比例", "BOM 损耗超限提示复核"),
    ("close_day", "期末结账日", "期间", "5", "日", "次月 5 日前完成结账"),
    ("alloc_method", "默认分摊方法", "分摊", "阶梯法", "", "辅助中心单向顺序分摊"),
    ("round_unit", "金额小数位", "核算", "2", "位", "统一两位小数，尾差由末位吸收"),
]
