# -*- coding: utf-8 -*-
"""飞奔成本管理系统 · 服务层

72 REST 路由：主数据 / 标准成本 / 工单实际成本 / 费用归集 / 阶梯分摊 /
预算管控 / 差异分析 / 报表中心 / 期间结账 / 系统管理。
多通道鉴权、限流、幂等、Webhook 签名投递、增量同步、OpenAPI。
"""
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

import cost
import db
import seed as seed_mod

BRAND, VERSION = cost.BRAND, cost.VERSION
_DIR = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(os.path.dirname(_DIR), "frontend")
PORT = int(os.environ.get("PORT") or os.environ.get("FEIBEN_PORT") or 8020)
HOST = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
PATH_PREFIX = os.environ.get("FEIBEN_PREFIX") or "/cost"

EVENTS = ["center.created", "product.created", "std.calculated", "wo.created",
          "wo.completed", "expense.created", "expense.approved", "expense.rejected",
          "alloc.executed", "budget.updated", "period.closed", "variance.calculated",
          "test.ping"]

TOKENS = {}
_TOKEN_LOCK = threading.Lock()
_RATE = {}
_RATE_LIMIT = 300
_WEBHOOK_Q = []


class ApiErr(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def bad(msg, code=400):
    raise ApiErr(code, msg)


def connect():
    return db.connect()


def val(cn, sql, args=()):
    r = cn.execute(sql, args).fetchone()
    return r[0] if r is not None else 0


def get_rule(cn, code, default=None):
    r = cn.execute("SELECT value FROM rules WHERE code=?", (code,)).fetchone()
    return r[0] if r else default


def rule_num(cn, code, default=0.0):
    return cost.safe_num(get_rule(cn, code, default), default)


def log(cn, user, action, detail=""):
    cn.execute("INSERT INTO logs(at,user,action,detail) VALUES(?,?,?,?)",
               (cost.now_str(), user, action, detail))


def hash_pwd(pwd, salt):
    return hashlib.sha256((pwd + salt).encode("utf-8")).hexdigest()


def period_closed(cn, period):
    r = cn.execute("SELECT status FROM periods WHERE period=?", (period,)).fetchone()
    return bool(r and r["status"] == "已结账")


def guard_period(cn, period):
    if not period:
        bad("缺少期间（period）")
    if period_closed(cn, period):
        bad("期间 %s 已结账，禁止写入" % period, 409)


def ensure_period(cn, period):
    if not period:
        return
    r = cn.execute("SELECT id FROM periods WHERE period=?", (period,)).fetchone()
    if not r:
        cn.execute("INSERT INTO periods(period,status,created) VALUES(?,'打开',?)",
                   (period, cost.now_str()))


def fire_event(cn, event, payload):
    payload = dict(payload or {}, event=event, at=cost.now_str())
    body = json.dumps(payload, ensure_ascii=False)
    for w in cn.execute("SELECT id,url,secret,events FROM webhooks WHERE enabled=1").fetchall():
        events = (w["events"] or "").split(",")
        if event in events or "test.ping" in events:
            cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,status,attempts)"
                       " VALUES(?,?,?,'pending',0)", (w["id"], event, body))
            _WEBHOOK_Q.append((w["id"], w["url"], w["secret"], event, body))
    cn.execute("INSERT INTO sync_state(entity,last_at) VALUES('event',?)"
               " ON CONFLICT(entity) DO UPDATE SET last_at=excluded.last_at", (cost.now_str(),))


# ---------------------------------------------------------------- 鉴权

def issue_token(cn, username):
    t = hashlib.sha256(("%s|%s|%s" % (username, time.time(), os.urandom(8))).encode()).hexdigest()
    with _TOKEN_LOCK:
        TOKENS[t] = username
    cn.execute("INSERT OR REPLACE INTO tokens(token,username,created) VALUES(?,?,?)",
               (t, username, cost.now_str()))
    return t


def token_user(cn, token):
    if not token:
        return None
    with _TOKEN_LOCK:
        uname = TOKENS.get(token)
    if uname is None:
        r = cn.execute("SELECT username FROM tokens WHERE token=?", (token,)).fetchone()
        if r:
            uname = r[0]
            with _TOKEN_LOCK:
                TOKENS[token] = uname
    return uname


def check_key(cn, key):
    if not key:
        return None
    kh = hashlib.sha256(key.encode()).hexdigest()
    r = cn.execute("SELECT id,name,scope FROM api_keys WHERE key_hash=? AND revoked=0",
                   (kh,)).fetchone()
    if r:
        cn.execute("UPDATE api_keys SET last_used=? WHERE id=?", (cost.now_str(), r["id"]))
        cn.commit()
        return dict(r)
    return None


# ---------------------------------------------------------------- 认证接口

def api_login(u, m, body):
    cn = connect()
    uname = (body.get("username") or "").strip()
    pwd = body.get("password") or ""
    r = cn.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
    if not r or hash_pwd(pwd, r["salt"]) != r["password_hash"]:
        bad("账号或密码错误", 401)
    token = issue_token(cn, uname)
    log(cn, uname, "登录", "")
    cn.commit()
    return {"token": token, "user": {"username": r["username"], "name": r["name"],
                                     "role": r["role"], "roleName": cost.ROLES.get(r["role"], {}).get("name", r["role"]),
                                     "perms": cost.perms_of(r["role"])}}


def api_logout(u, m, body):
    cn = connect()
    t = (u or {}).get("_token") or ""
    with _TOKEN_LOCK:
        TOKENS.pop(t, None)
    cn.execute("DELETE FROM tokens WHERE token=?", (t,))
    cn.commit()
    return {"ok": True}


def api_me(u, m, body):
    return {"username": u["username"], "name": u["name"], "role": u["role"],
            "roleName": cost.ROLES.get(u["role"], {}).get("name", u["role"]),
            "perms": cost.perms_of(u["role"])}


def api_password(u, m, body):
    cn = connect()
    old = body.get("old") or body.get("old_password") or ""
    new = body.get("new") or body.get("new_password") or ""
    if len(new) < 8:
        bad("新密码至少 8 位")
    r = cn.execute("SELECT * FROM users WHERE username=?", (u["username"],)).fetchone()
    if not r or hash_pwd(old, r["salt"]) != r["password_hash"]:
        bad("原密码错误", 401)
    salt = os.urandom(8).hex()
    cn.execute("UPDATE users SET password_hash=?,salt=? WHERE username=?",
               (hash_pwd(new, salt), salt, u["username"]))
    log(cn, u["username"], "修改密码", "")
    cn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 看板

def api_board(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    r = cn.execute("SELECT status FROM periods WHERE period=?", (period,)).fetchone()
    pstatus = r["status"] if r else "未建期"
    centers = cn.execute("SELECT COUNT(*) FROM cost_centers WHERE status='启用'").fetchone()[0]
    products = cn.execute("SELECT COUNT(*) FROM products WHERE status='在产'").fetchone()[0]
    direct = cost.safe_num(val(cn, "SELECT SUM(amount) FROM expenses WHERE period=? AND"
                                 " status='已批准'", (period,)))
    alloc = cn.execute("SELECT no,base_total,allocated_total,check_diff FROM allocation_runs"
                       " WHERE period=? ORDER BY id DESC LIMIT 1", (period,)).fetchone()
    std_total = cost.safe_num(val(cn, "SELECT SUM(sc.unit_cost*wo.qty_done) FROM work_orders wo"
                                    " JOIN std_costs sc ON sc.product_code=wo.product_code AND"
                                    " sc.period=wo.period WHERE wo.period=? AND wo.status IN"
                                    " ('已完工','已关闭')", (period,)))
    act_total = cost.safe_num(val(cn, "SELECT SUM(total_actual) FROM work_orders WHERE period=?"
                                    " AND status IN ('已完工','已关闭')", (period,)))
    var = cost.q2(act_total - std_total)
    pend = cn.execute("SELECT COUNT(*) FROM expenses WHERE period=? AND status='待审批'",
                      (period,)).fetchone()[0]
    open_orders = cn.execute("SELECT COUNT(*) FROM work_orders WHERE period=? AND status IN"
                             " ('草稿','在生产')", (period,)).fetchone()[0]
    budget_sum = cost.safe_num(val(cn, "SELECT SUM(amount) FROM budgets WHERE period=?", (period,)))
    budget_used = cost.safe_num(val(cn, "SELECT SUM(used) FROM budgets WHERE period=?", (period,)))
    bs = cost.budget_state(budget_sum, budget_used, rule_num(cn, "warn_rate", 0.9),
                           rule_num(cn, "block_rate", 1.1))
    top = cn.execute("SELECT product_code,total_var,act_total FROM variances WHERE period=?"
                     " ORDER BY ABS(total_var) DESC LIMIT 5", (period,)).fetchall()
    months = []
    for i in range(5, -1, -1):
        p = cost.prev_period(period, i)
        s = cost.safe_num(val(cn, "SELECT SUM(sc.unit_cost*wo.qty_done) FROM work_orders wo"
                                " JOIN std_costs sc ON sc.product_code=wo.product_code AND"
                                " sc.period=wo.period WHERE wo.period=? AND wo.status IN"
                                " ('已完工','已关闭')", (p,)))
        a = cost.safe_num(val(cn, "SELECT SUM(total_actual) FROM work_orders WHERE period=?"
                                " AND status IN ('已完工','已关闭')", (p,)))
        d = cost.safe_num(val(cn, "SELECT SUM(amount) FROM expenses WHERE period=? AND"
                                " status='已批准'", (p,)))
        months.append({"period": p, "standard": cost.q2(s), "actual": cost.q2(a),
                       "direct": cost.q2(d)})
    cat = cn.execute("SELECT s.category c, SUM(e.amount) a FROM expenses e JOIN subjects s"
                     " ON s.code=e.subject_code WHERE e.period=? AND e.status='已批准'"
                     " GROUP BY s.category", (period,)).fetchall()
    centers_top = cn.execute(
        "SELECT c.code,c.name,SUM(e.amount) a FROM expenses e JOIN cost_centers c"
        " ON c.code=e.center_code WHERE e.period=? AND e.status='已批准'"
        " GROUP BY c.code ORDER BY a DESC LIMIT 8", (period,)).fetchall()
    return {"kpi": {
        "period": period, "periodStatus": pstatus, "centers": centers, "products": products,
        "directCost": cost.q2(direct), "allocated": cost.q2(alloc["allocated_total"]) if alloc else 0.0,
        "allocCheck": cost.q2(alloc["check_diff"]) if alloc else 0.0,
        "stdTotal": cost.q2(std_total), "actTotal": cost.q2(act_total), "variance": var,
        "varianceRate": round(var / std_total, 4) if std_total else 0.0,
        "pendingExpenses": pend, "openOrders": open_orders,
        "budget": {"amount": cost.q2(budget_sum), "used": cost.q2(budget_used),
                   "rate": bs["rate"], "level": bs["level"]}},
        "trend": months,
        "category": [{"name": r["c"], "amount": cost.q2(r["a"])} for r in cat],
        "centerTop": [{"code": r["code"], "name": r["name"], "amount": cost.q2(r["a"])}
                      for r in centers_top],
        "topVariance": [{"product": r["product_code"], "variance": cost.q2(r["total_var"]),
                         "actTotal": cost.q2(r["act_total"])} for r in top]}


# ---------------------------------------------------------------- 成本中心

def center_row(cn, r, period=None):
    d = {"code": r["code"], "name": r["name"], "ctype": r["ctype"],
         "parent": r["parent_code"], "leader": r["leader"],
         "laborRate": cost.safe_num(r["labor_rate"]), "ohRate": cost.safe_num(r["oh_rate"]),
         "allocOrder": r["alloc_order"], "driver": r["driver"],
         "driverQty": cost.safe_num(r["driver_qty"]), "status": r["status"],
         "remark": r["remark"]}
    if period:
        d["directCost"] = cost.q2(val(cn, "SELECT SUM(amount) FROM expenses WHERE period=?"
                                           " AND center_code=? AND status='已批准'",
                                       (period, r["code"])))
        run = cn.execute("SELECT no FROM allocation_runs WHERE period=? ORDER BY id DESC LIMIT 1",
                         (period,)).fetchone()
        if run:
            d["allocIn"] = cost.q2(val(cn, "SELECT SUM(amount) FROM allocation_lines WHERE"
                                            " run_no=? AND to_center=?", (run["no"], r["code"])))
            d["allocOut"] = cost.q2(val(cn, "SELECT SUM(amount) FROM allocation_lines WHERE"
                                             " run_no=? AND from_center=?", (run["no"], r["code"])))
        else:
            d["allocIn"] = 0.0
            d["allocOut"] = 0.0
        d["netCost"] = cost.q2(d["directCost"] + d["allocIn"] - d["allocOut"])
        d["orderCount"] = val(cn, "SELECT COUNT(*) FROM work_orders WHERE period=?"
                                    " AND center_code=?", (period, r["code"]))
    return d


def api_center_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute("SELECT * FROM cost_centers ORDER BY alloc_order, code").fetchall()
    items = [center_row(cn, r, period) for r in rows]
    if qs.get("ctype"):
        items = [i for i in items if i["ctype"] == qs["ctype"]]
    return {"list": items, "period": period,
            "types": cost.CENTER_TYPES, "drivers": cost.DRIVERS}


def api_center_create(u, m, body):
    cn = connect()
    code = (body.get("code") or "").strip().upper()
    if not code or not body.get("name"):
        bad("成本中心编码与名称必填")
    if val(cn, "SELECT COUNT(*) FROM cost_centers WHERE code=?", (code,)):
        bad("成本中心已存在：%s" % code)
    ctype = body.get("ctype") or "生产"
    if ctype not in cost.CENTER_TYPES:
        bad("成本中心类型非法：%s" % ctype)
    cn.execute("INSERT INTO cost_centers(code,name,ctype,parent_code,leader,labor_rate,oh_rate,"
               "alloc_order,driver,driver_qty,status,remark,created)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, body["name"], ctype, body.get("parent") or "", body.get("leader") or "",
                cost.safe_num(body.get("laborRate")), cost.safe_num(body.get("ohRate")),
                int(cost.safe_num(body.get("allocOrder"), 9)), body.get("driver") or "人工工时",
                cost.safe_num(body.get("driverQty")), body.get("status") or "启用",
                body.get("remark") or "", cost.now_str()))
    log(cn, u["username"], "新建成本中心", code)
    fire_event(cn, "center.created", {"code": code, "name": body["name"]})
    cn.commit()
    return {"code": code}


def api_center_update(u, m, body):
    cn = connect()
    code = m.group(1)
    if not cn.execute("SELECT id FROM cost_centers WHERE code=?", (code,)).fetchone():
        bad("成本中心不存在", 404)
    f = {"name": "name", "ctype": "ctype", "parent": "parent_code", "leader": "leader",
         "driver": "driver", "status": "status", "remark": "remark"}
    sets, args = [], []
    for k, col in f.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    for k, col in (("laborRate", "labor_rate"), ("ohRate", "oh_rate"), ("driverQty", "driver_qty")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(cost.safe_num(body[k]))
    if "allocOrder" in body:
        sets.append("alloc_order=?")
        args.append(int(cost.safe_num(body["allocOrder"], 9)))
    if not sets:
        bad("没有可更新字段")
    args.append(code)
    cn.execute("UPDATE cost_centers SET %s WHERE code=?" % ",".join(sets), args)
    log(cn, u["username"], "修改成本中心", code)
    cn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 科目

def api_subject_list(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT * FROM subjects ORDER BY code").fetchall()
    return {"list": [{"code": r["code"], "name": r["name"], "category": r["category"],
                      "gather": r["gather"], "enabled": bool(r["enabled"]),
                      "remark": r["remark"]} for r in rows],
            "categories": cost.SUBJECT_CATEGORIES}


def api_subject_create(u, m, body):
    cn = connect()
    code = (body.get("code") or "").strip().upper()
    if not code or not body.get("name"):
        bad("科目编码与名称必填")
    if val(cn, "SELECT COUNT(*) FROM subjects WHERE code=?", (code,)):
        bad("科目已存在：%s" % code)
    cat = body.get("category") or "材料"
    if cat not in cost.SUBJECT_CATEGORIES:
        bad("科目类别非法")
    cn.execute("INSERT INTO subjects(code,name,category,gather,enabled,remark,created)"
               " VALUES(?,?,?,?,1,?,?)",
               (code, body["name"], cat, body.get("gather") or "直接",
                body.get("remark") or "", cost.now_str()))
    log(cn, u["username"], "新建科目", code)
    cn.commit()
    return {"code": code}


def api_subject_update(u, m, body):
    cn = connect()
    code = m.group(1)
    if not cn.execute("SELECT id FROM subjects WHERE code=?", (code,)).fetchone():
        bad("科目不存在", 404)
    sets, args = [], []
    for k, col in (("name", "name"), ("category", "category"), ("gather", "gather"),
                   ("remark", "remark")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    if "enabled" in body:
        sets.append("enabled=?")
        args.append(1 if body["enabled"] else 0)
    if not sets:
        bad("没有可更新字段")
    args.append(code)
    cn.execute("UPDATE subjects SET %s WHERE code=?" % ",".join(sets), args)
    log(cn, u["username"], "修改科目", code)
    cn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 产品与 BOM

def product_row(cn, r, period=None):
    period = period or cost.cur_period()
    std = cn.execute("SELECT * FROM std_costs WHERE period=? AND product_code=?"
                     " ORDER BY version DESC LIMIT 1", (period, r["code"])).fetchone()
    cr = cn.execute("SELECT name FROM cost_centers WHERE code=?", (r["center_code"],)).fetchone()
    return {"code": r["code"], "name": r["name"], "spec": r["spec"], "unit": r["unit"],
            "stdHours": cost.safe_num(r["std_hours"]), "center": r["center_code"],
            "centerName": cr["name"] if cr else "", "listPrice": cost.safe_num(r["list_price"]),
            "status": r["status"], "remark": r["remark"],
            "bomCount": val(cn, "SELECT COUNT(*) FROM bom_lines WHERE product_code=?", (r["code"],)),
            "stdUnitCost": cost.q2(std["unit_cost"]) if std else 0.0,
            "stdMat": cost.q2(std["mat_cost"]) if std else 0.0,
            "stdLabor": cost.q2(std["labor_cost"]) if std else 0.0,
            "stdOh": cost.q2(std["oh_cost"]) if std else 0.0}


def api_product_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute("SELECT * FROM products ORDER BY code").fetchall()
    items = [product_row(cn, r, period) for r in rows]
    kw = (qs.get("kw") or "").strip()
    if kw:
        items = [i for i in items if kw in i["code"] or kw in i["name"]]
    return {"list": items, "period": period}


def api_product_create(u, m, body):
    cn = connect()
    code = (body.get("code") or "").strip().upper()
    if not code or not body.get("name"):
        bad("产品编码与名称必填")
    if val(cn, "SELECT COUNT(*) FROM products WHERE code=?", (code,)):
        bad("产品已存在：%s" % code)
    center = body.get("center") or ""
    if center and not val(cn, "SELECT COUNT(*) FROM cost_centers WHERE code=?", (center,)):
        bad("核算成本中心不存在：%s" % center)
    cn.execute("INSERT INTO products(code,name,spec,unit,std_hours,center_code,list_price,"
               "status,remark,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (code, body["name"], body.get("spec") or "", body.get("unit") or "件",
                cost.safe_num(body.get("stdHours")), center,
                cost.safe_num(body.get("listPrice")), body.get("status") or "在产",
                body.get("remark") or "", cost.now_str()))
    log(cn, u["username"], "新建产品", code)
    fire_event(cn, "product.created", {"code": code, "name": body["name"]})
    cn.commit()
    return {"code": code}


def api_product_detail(u, m, body):
    cn = connect()
    code = m.group(1)
    r = cn.execute("SELECT * FROM products WHERE code=?", (code,)).fetchone()
    if not r:
        bad("产品不存在", 404)
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    bom = cn.execute("SELECT * FROM bom_lines WHERE product_code=? ORDER BY id", (code,)).fetchall()
    mats = []
    for b in bom:
        qty = cost.safe_num(b["qty_per"]) * (1 + cost.safe_num(b["loss_rate"]))
        mats.append({"id": b["id"], "materialCode": b["material_code"],
                     "materialName": b["material_name"], "qtyPer": cost.safe_num(b["qty_per"]),
                     "lossRate": cost.safe_num(b["loss_rate"]), "stdPrice": cost.safe_num(b["std_price"]),
                     "unit": b["unit"], "amount": cost.q2(qty * cost.safe_num(b["std_price"]))})
    hist = cn.execute("SELECT period,version,mat_cost,labor_cost,oh_cost,unit_cost,status"
                      " FROM std_costs WHERE product_code=? ORDER BY period DESC, version DESC",
                      (code,)).fetchall()
    return {"product": product_row(cn, r, period), "bom": mats,
            "stdHistory": [{"period": h["period"], "version": h["version"],
                            "matCost": cost.q2(h["mat_cost"]), "laborCost": cost.q2(h["labor_cost"]),
                            "ohCost": cost.q2(h["oh_cost"]), "unitCost": cost.q2(h["unit_cost"]),
                            "status": h["status"]} for h in hist]}


def api_product_update(u, m, body):
    cn = connect()
    code = m.group(1)
    if not cn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone():
        bad("产品不存在", 404)
    sets, args = [], []
    for k, col in (("name", "name"), ("spec", "spec"), ("unit", "unit"),
                   ("center", "center_code"), ("status", "status"), ("remark", "remark")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    for k, col in (("stdHours", "std_hours"), ("listPrice", "list_price")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(cost.safe_num(body[k]))
    if not sets:
        bad("没有可更新字段")
    args.append(code)
    cn.execute("UPDATE products SET %s WHERE code=?" % ",".join(sets), args)
    log(cn, u["username"], "修改产品", code)
    cn.commit()
    return {"ok": True}


def api_bom_list(u, m, body):
    cn = connect()
    return api_product_detail(u, m, body)


def api_bom_add(u, m, body):
    cn = connect()
    code = m.group(1)
    if not cn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone():
        bad("产品不存在", 404)
    mat = (body.get("materialCode") or "").strip().upper()
    if not mat:
        bad("物料编码必填")
    qty = cost.safe_num(body.get("qtyPer"))
    if qty <= 0:
        bad("单位用量必须大于 0")
    loss = cost.safe_num(body.get("lossRate"))
    limit = rule_num(cn, "loss_limit", 0.2)
    if loss > limit:
        bad("损耗率 %.1f%% 超过上限 %.0f%%，请复核" % (loss * 100, limit * 100))
    cn.execute("INSERT INTO bom_lines(product_code,material_code,material_name,qty_per,"
               "loss_rate,std_price,unit) VALUES(?,?,?,?,?,?,?)",
               (code, mat, body.get("materialName") or mat, qty, loss,
                cost.safe_num(body.get("stdPrice")), body.get("unit") or "kg"))
    log(cn, u["username"], "新增BOM", "%s/%s" % (code, mat))
    cn.commit()
    return {"ok": True}


def api_bom_delete(u, m, body):
    cn = connect()
    code, bid = m.group(1), int(m.group(2))
    r = cn.execute("SELECT id FROM bom_lines WHERE id=? AND product_code=?", (bid, code)).fetchone()
    if not r:
        bad("BOM 行不存在", 404)
    cn.execute("DELETE FROM bom_lines WHERE id=?", (bid,))
    log(cn, u["username"], "删除BOM", "%s#%d" % (code, bid))
    cn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 标准成本

def api_std_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute(
        "SELECT sc.*, p.name pname, p.unit FROM std_costs sc JOIN products p"
        " ON p.code=sc.product_code WHERE sc.period=? ORDER BY sc.product_code, sc.version DESC",
        (period,)).fetchall()
    return {"list": [{"period": r["period"], "product": r["product_code"],
                      "productName": r["pname"], "unit": r["unit"], "version": r["version"],
                      "matCost": cost.q2(r["mat_cost"]), "laborCost": cost.q2(r["labor_cost"]),
                      "ohCost": cost.q2(r["oh_cost"]), "unitCost": cost.q2(r["unit_cost"]),
                      "status": r["status"], "calcAt": r["calc_at"]} for r in rows],
            "period": period}


def api_std_calc(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    guard_period(cn, period)
    ensure_period(cn, period)
    only = body.get("product")
    if only:
        prods = cn.execute("SELECT * FROM products WHERE code=?", (only,)).fetchall()
        if not prods:
            bad("产品不存在", 404)
    else:
        prods = cn.execute("SELECT * FROM products WHERE status='在产'").fetchall()
    if not prods:
        bad("没有可计算的产品")
    done, warnings = [], []
    for p in prods:
        bom = cn.execute("SELECT * FROM bom_lines WHERE product_code=?", (p["code"],)).fetchall()
        if not bom:
            warnings.append("%s 无 BOM，材料成本按 0 计" % p["code"])
        cr = cn.execute("SELECT labor_rate,oh_rate FROM cost_centers WHERE code=?",
                        (p["center_code"],)).fetchone()
        if not cr:
            warnings.append("%s 未指定有效成本中心，人工/制费按 0 计" % p["code"])
        card = cost.std_card([dict(b) for b in bom], p["std_hours"],
                             cost.safe_num(cr["labor_rate"]) if cr else 0,
                             cost.safe_num(cr["oh_rate"]) if cr else 0)
        ver = int(cost.safe_num(val(cn, "SELECT MAX(version) FROM std_costs WHERE period=?"
                                        " AND product_code=?", (period, p["code"]))) + 1)
        cn.execute("UPDATE std_costs SET status='历史' WHERE period=? AND product_code=?",
                   (period, p["code"]))
        cn.execute("INSERT INTO std_costs(period,product_code,version,mat_cost,labor_cost,oh_cost,"
                   "unit_cost,status,calc_at) VALUES(?,?,?,?,?,?,?,'已发布',?)",
                   (period, p["code"], ver, card["matCost"], card["laborCost"], card["ohCost"],
                    card["unitCost"], cost.now_str()))
        done.append({"product": p["code"], "version": ver, "unitCost": card["unitCost"]})
    log(cn, u["username"], "计算标准成本", "%s %d 个产品" % (period, len(done)))
    fire_event(cn, "std.calculated", {"period": period, "count": len(done)})
    cn.commit()
    return {"period": period, "count": len(done), "items": done, "warnings": warnings}


def api_std_publish(u, m, body):
    cn = connect()
    period, prod = m.group(1), m.group(2)
    ver = int(cost.safe_num(body.get("version")))
    r = cn.execute("SELECT id FROM std_costs WHERE period=? AND product_code=? AND version=?",
                   (period, prod, ver)).fetchone() if ver else None
    if not r:
        bad("标准成本版本不存在", 404)
    cn.execute("UPDATE std_costs SET status='历史' WHERE period=? AND product_code=?",
               (period, prod))
    cn.execute("UPDATE std_costs SET status='已发布',published_at=? WHERE id=?",
               (cost.now_str(), r["id"]))
    log(cn, u["username"], "发布标准成本", "%s/%s v%d" % (period, prod, ver))
    cn.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 工单

def wo_row(cn, r):
    p = cn.execute("SELECT name,unit FROM products WHERE code=?", (r["product_code"],)).fetchone()
    c = cn.execute("SELECT name FROM cost_centers WHERE code=?", (r["center_code"],)).fetchone()
    wip = round(cost.safe_num(r["qty_plan"]) - cost.safe_num(r["qty_done"]), 4)
    return {"no": r["no"], "product": r["product_code"],
            "productName": p["name"] if p else "", "unit": p["unit"] if p else "",
            "period": r["period"], "center": r["center_code"],
            "centerName": c["name"] if c else "", "qtyPlan": cost.safe_num(r["qty_plan"]),
            "qtyDone": cost.safe_num(r["qty_done"]), "wipQty": wip,
            "wipRate": cost.safe_num(r["wip_rate"]), "status": r["status"],
            "startDate": r["start_date"], "endDate": r["end_date"],
            "mat": cost.q2(r["mat_actual"]), "labor": cost.q2(r["labor_actual"]),
            "oh": cost.q2(r["oh_actual"]), "total": cost.q2(r["total_actual"]),
            "unitCost": round(cost.safe_num(r["unit_cost"]), 4),
            "equivQty": round(cost.safe_num(r["equiv_qty"]), 4),
            "finishedCost": cost.q2(r["finished_cost"]), "wipCost": cost.q2(r["wip_cost"]),
            "calcAt": r["calc_at"], "remark": r["remark"]}


def api_wo_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    where, args = [], []
    if qs.get("period"):
        where.append("period=?")
        args.append(qs["period"])
    if qs.get("center"):
        where.append("center_code=?")
        args.append(qs["center"])
    if qs.get("status"):
        where.append("status=?")
        args.append(qs["status"])
    sql = "SELECT * FROM work_orders" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY no DESC"
    rows = cn.execute(sql, args).fetchall()
    items = [wo_row(cn, r) for r in rows]
    kw = (qs.get("kw") or "").strip().upper()
    if kw:
        items = [i for i in items if kw in i["no"] or kw in i["product"]]
    return {"list": items, "states": cost.WO_STATES}


def api_wo_create(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    guard_period(cn, period)
    ensure_period(cn, period)
    prod = (body.get("product") or "").strip().upper()
    if not prod or not body.get("center"):
        bad("产品与成本中心必填")
    p = cn.execute("SELECT * FROM products WHERE code=?", (prod,)).fetchone()
    if not p:
        bad("产品不存在：%s" % prod, 404)
    if not val(cn, "SELECT COUNT(*) FROM cost_centers WHERE code=?", (body["center"],)):
        bad("成本中心不存在：%s" % body["center"])
    qty = cost.safe_num(body.get("qtyPlan"))
    if qty <= 0:
        bad("计划数量必须大于 0")
    day = period.replace("-", "")
    seq = int(cost.safe_num(val(cn, "SELECT COUNT(*) FROM work_orders WHERE no LIKE ?",
                                 ("WO%s-%%" % day,))) + 1)
    while cn.execute("SELECT id FROM work_orders WHERE no=?",
                     (cost.doc_no("WO", day, seq),)).fetchone():
        seq += 1
    no = cost.doc_no("WO", day, seq)
    rate = rule_num(cn, "wip_default", 1.0)
    cn.execute("INSERT INTO work_orders(no,product_code,period,center_code,qty_plan,qty_done,"
               "wip_rate,start_date,status,remark,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (no, prod, period, body["center"], qty, cost.safe_num(body.get("qtyDone")),
                cost.safe_num(body.get("wipRate"), rate), body.get("startDate") or cost.today(),
                "在生产", body.get("remark") or "", cost.now_str()))
    log(cn, u["username"], "新建工单", no)
    fire_event(cn, "wo.created", {"no": no, "product": prod, "qty": qty})
    cn.commit()
    return {"no": no}


def api_wo_detail(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    mats = cn.execute("SELECT * FROM wo_materials WHERE wo_no=? ORDER BY id", (no,)).fetchall()
    labs = cn.execute("SELECT * FROM wo_labor WHERE wo_no=? ORDER BY id", (no,)).fetchall()
    std = cn.execute("SELECT * FROM std_costs WHERE period=? AND product_code=?"
                     " ORDER BY version DESC LIMIT 1", (r["period"], r["product_code"])).fetchone()
    return {"order": wo_row(cn, r),
            "materials": [{"id": x["id"], "materialCode": x["material_code"],
                           "materialName": x["material_name"], "qty": cost.safe_num(x["qty"]),
                           "price": cost.safe_num(x["price"]), "amount": cost.q2(x["amount"]),
                           "at": x["at"]} for x in mats],
            "labors": [{"id": x["id"], "workType": x["work_type"],
                        "hours": cost.safe_num(x["hours"]), "rate": cost.safe_num(x["rate"]),
                        "amount": cost.q2(x["amount"]), "worker": x["worker"],
                        "at": x["at"]} for x in labs],
            "stdUnitCost": cost.q2(std["unit_cost"]) if std else 0.0}


def api_wo_update(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    if r["status"] in ("已完工", "已关闭"):
        bad("工单已完工/关闭，不可修改成本要素", 409)
    guard_period(cn, r["period"])
    sets, args = [], []
    for k, col in (("startDate", "start_date"), ("endDate", "end_date"),
                   ("center", "center_code"), ("remark", "remark")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    for k, col in (("qtyPlan", "qty_plan"), ("qtyDone", "qty_done"), ("wipRate", "wip_rate")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(cost.safe_num(body[k]))
    if not sets:
        bad("没有可更新字段")
    args.append(no)
    cn.execute("UPDATE work_orders SET %s WHERE no=?" % ",".join(sets), args)
    log(cn, u["username"], "修改工单", no)
    cn.commit()
    return {"ok": True}


def api_wo_material(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    if r["status"] in ("已完工", "已关闭"):
        bad("工单已完工，不可追加领料", 409)
    guard_period(cn, r["period"])
    qty = cost.safe_num(body.get("qty"))
    price = cost.safe_num(body.get("price"))
    if qty <= 0:
        bad("领料数量必须大于 0")
    amount = cost.q2(qty * price)
    cn.execute("INSERT INTO wo_materials(wo_no,material_code,material_name,qty,price,amount,at)"
               " VALUES(?,?,?,?,?,?,?)",
               (no, (body.get("materialCode") or "").upper(),
                body.get("materialName") or body.get("materialCode") or "", qty, price, amount,
                cost.now_str()))
    log(cn, u["username"], "工单领料", "%s %s×%s" % (no, body.get("materialCode"), qty))
    cn.commit()
    return {"ok": True, "amount": amount}


def api_wo_labor(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    if r["status"] in ("已完工", "已关闭"):
        bad("工单已完工，不可追加报工", 409)
    guard_period(cn, r["period"])
    hours = cost.safe_num(body.get("hours"))
    if hours <= 0:
        bad("报工工时必须大于 0")
    rate = cost.safe_num(body.get("rate"))
    if rate <= 0:
        cr = cn.execute("SELECT labor_rate FROM cost_centers WHERE code=?",
                        (r["center_code"],)).fetchone()
        rate = cost.safe_num(cr["labor_rate"]) if cr else 0
    amount = cost.q2(hours * rate)
    cn.execute("INSERT INTO wo_labor(wo_no,work_type,hours,rate,amount,worker,at)"
               " VALUES(?,?,?,?,?,?,?)",
               (no, body.get("workType") or "直接工时", hours, rate, amount,
                body.get("worker") or "", cost.now_str()))
    log(cn, u["username"], "工单报工", "%s %sh" % (no, hours))
    cn.commit()
    return {"ok": True, "amount": amount}


def api_wo_calc(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    mats = cn.execute("SELECT * FROM wo_materials WHERE wo_no=?", (no,)).fetchall()
    labs = cn.execute("SELECT * FROM wo_labor WHERE wo_no=?", (no,)).fetchall()
    cr = cn.execute("SELECT oh_rate,labor_rate FROM cost_centers WHERE code=?",
                    (r["center_code"],)).fetchone()
    if not cr:
        bad("工单成本中心不存在")
    ac = cost.actual_cost([dict(x) for x in mats], [dict(x) for x in labs],
                          cost.safe_num(cr["oh_rate"]))
    split = cost.split_cost(ac["totalActual"], r["qty_done"], r["qty_plan"], r["wip_rate"])
    if split is None:
        bad("约当产量核算失败：请检查计划数量（%.2f）、完工数量（%.2f）、在制进度（%.2f）" % (
            cost.safe_num(r["qty_plan"]), cost.safe_num(r["qty_done"]),
            cost.safe_num(r["wip_rate"])))
    cn.execute("UPDATE work_orders SET mat_actual=?,labor_actual=?,oh_actual=?,total_actual=?,"
               "unit_cost=?,equiv_qty=?,finished_cost=?,wip_cost=?,calc_at=? WHERE no=?",
               (ac["matActual"], ac["laborActual"], ac["ohActual"], ac["totalActual"],
                split["unitCost"], split["equivQty"], split["finishedCost"], split["wipCost"],
                cost.now_str(), no))
    log(cn, u["username"], "工单成本核算", "%s 合计 %.2f" % (no, ac["totalActual"]))
    cn.commit()
    return {"no": no, "actual": ac, "split": split}


def api_wo_stage(u, m, body):
    cn = connect()
    no = m.group(1)
    target = body.get("target") or body.get("status") or ""
    r = cn.execute("SELECT * FROM work_orders WHERE no=?", (no,)).fetchone()
    if not r:
        bad("工单不存在", 404)
    if target not in cost.WO_STATES:
        bad("非法目标状态：%s" % target)
    ctx = {"qty_plan": r["qty_plan"], "qty_done": r["qty_done"], "wip_rate": r["wip_rate"],
           "has_cost": cost.safe_num(r["total_actual"]) > 0,
           "period_closed": period_closed(cn, r["period"])}
    err = cost.wo_gate(r["status"], target, ctx)
    if err:
        bad(err, 409)
    fields = {"status": target}
    if target == "已完工":
        fields["end_date"] = cost.today()
    cn.execute("UPDATE work_orders SET status=?,end_date=? WHERE no=?",
               (target, fields.get("end_date", r["end_date"] or ""), no))
    log(cn, u["username"], "工单状态变更", "%s %s→%s" % (no, r["status"], target))
    if target == "已完工":
        fire_event(cn, "wo.completed", {"no": no, "product": r["product_code"],
                                        "qty": cost.safe_num(r["qty_done"])})
    cn.commit()
    return {"ok": True, "status": target}


# ---------------------------------------------------------------- 费用归集

def exp_row(cn, r):
    c = cn.execute("SELECT name FROM cost_centers WHERE code=?", (r["center_code"],)).fetchone()
    s = cn.execute("SELECT name,category FROM subjects WHERE code=?", (r["subject_code"],)).fetchone()
    return {"no": r["no"], "period": r["period"], "center": r["center_code"],
            "centerName": c["name"] if c else "", "subject": r["subject_code"],
            "subjectName": s["name"] if s else "",
            "category": s["category"] if s else "", "amount": cost.q2(r["amount"]),
            "source": r["source"], "docRef": r["doc_ref"], "summary": r["summary"],
            "status": r["status"], "applicant": r["applicant"], "approver": r["approver"],
            "decidedAt": r["decided_at"], "createdAt": r["created"]}


def api_exp_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    where, args = [], []
    for k, col in (("period", "period"), ("center", "center_code"),
                   ("subject", "subject_code"), ("status", "status"), ("source", "source")):
        if qs.get(k):
            where.append("%s=?" % col)
            args.append(qs[k])
    sql = "SELECT * FROM expenses" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY period DESC, no DESC"
    rows = cn.execute(sql, args).fetchall()
    items = [exp_row(cn, r) for r in rows]
    total = cost.q2(sum(i["amount"] for i in items if i["status"] == "已批准"))
    return {"list": items, "approvedTotal": total, "states": cost.EXP_STATES,
            "sources": cost.SOURCES}


def api_exp_create(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    guard_period(cn, period)
    ensure_period(cn, period)
    center = (body.get("center") or "").strip()
    subj = (body.get("subject") or "").strip()
    if not center or not subj:
        bad("成本中心与科目必填")
    if not val(cn, "SELECT COUNT(*) FROM cost_centers WHERE code=?", (center,)):
        bad("成本中心不存在：%s" % center)
    if not val(cn, "SELECT COUNT(*) FROM subjects WHERE code=?", (subj,)):
        bad("科目不存在：%s" % subj)
    amount = cost.safe_num(body.get("amount"))
    if amount <= 0:
        bad("金额必须大于 0")
    day = period.replace("-", "")
    seq = int(cost.safe_num(val(cn, "SELECT COUNT(*) FROM expenses WHERE no LIKE ?",
                                 ("EXP%s-%%" % day,))) + 1)
    while cn.execute("SELECT id FROM expenses WHERE no=?",
                     (cost.doc_no("EXP", day, seq),)).fetchone():
        seq += 1
    no = cost.doc_no("EXP", day, seq)
    status = body.get("status") or "草稿"
    if status not in ("草稿", "待审批"):
        status = "草稿"
    cn.execute("INSERT INTO expenses(no,period,center_code,subject_code,amount,source,doc_ref,"
               "summary,status,applicant,remark,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, period, center, subj, amount, body.get("source") or "手工",
                body.get("docRef") or "", body.get("summary") or "", status,
                u["username"], body.get("remark") or "", cost.now_str()))
    if status == "待审批":
        _budget_gate(cn, period, center, subj, amount)
    log(cn, u["username"], "新建费用单", "%s %s %.2f" % (no, subj, amount))
    fire_event(cn, "expense.created", {"no": no, "amount": amount, "center": center})
    cn.commit()
    return {"no": no}


def _budget_gate(cn, period, center, subj, amount):
    b = cn.execute("SELECT amount,used FROM budgets WHERE period=? AND center_code=?"
                   " AND subject_code=?", (period, center, subj)).fetchone()
    if not b:
        return
    err = cost.expense_gate("草稿", "待审批", {
        "amount": amount, "budget_amount": cost.safe_num(b["amount"]),
        "used": cost.safe_num(b["used"]), "block_rate": rule_num(cn, "block_rate", 1.1)})
    if err:
        bad(err, 409)


def api_exp_stage(u, m, body):
    cn = connect()
    no = m.group(1)
    target = body.get("target") or body.get("status") or ""
    r = cn.execute("SELECT * FROM expenses WHERE no=?", (no,)).fetchone()
    if not r:
        bad("费用单不存在", 404)
    if target not in cost.EXP_STATES:
        bad("非法目标状态：%s" % target)
    if target in ("已批准", "已驳回") and not cost.can(u["role"], "exp.approve"):
        bad("权限不足（需要 exp.approve）", 403)
    b = cn.execute("SELECT amount,used FROM budgets WHERE period=? AND center_code=?"
                   " AND subject_code=?", (r["period"], r["center_code"], r["subject_code"])).fetchone()
    ctx = {"amount": r["amount"], "period_closed": period_closed(cn, r["period"]),
           "budget_amount": cost.safe_num(b["amount"]) if b else 0,
           "used": cost.safe_num(b["used"]) if b else 0,
           "block_rate": rule_num(cn, "block_rate", 1.1),
           "isApprover": cost.can(u["role"], "exp.approve")}
    err = cost.expense_gate(r["status"], target, ctx)
    if err:
        bad(err, 409)
    approver = u["username"] if target in ("已批准", "已驳回") else ""
    cn.execute("UPDATE expenses SET status=?,approver=?,decided_at=? WHERE no=?",
               (target, approver, cost.now_str() if approver else "", no))
    if target == "已批准" and not r["budget_used"]:
        ok = cn.execute("UPDATE budgets SET used=used+? WHERE period=? AND center_code=?"
                        " AND subject_code=?",
                        (r["amount"], r["period"], r["center_code"], r["subject_code"]))
        if ok.rowcount:
            cn.execute("UPDATE expenses SET budget_used=1 WHERE no=?", (no,))
    if target == "已驳回" and r["budget_used"]:
        cn.execute("UPDATE budgets SET used=MAX(0,used-?) WHERE period=? AND center_code=?"
                   " AND subject_code=?",
                   (r["amount"], r["period"], r["center_code"], r["subject_code"]))
        cn.execute("UPDATE expenses SET budget_used=0 WHERE no=?", (no,))
    log(cn, u["username"], "费用单状态变更", "%s %s→%s" % (no, r["status"], target))
    if target == "已批准":
        fire_event(cn, "expense.approved", {"no": no, "amount": cost.safe_num(r["amount"])})
    if target == "已驳回":
        fire_event(cn, "expense.rejected", {"no": no})
    cn.commit()
    return {"ok": True, "status": target}


def api_exp_summary(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute(
        "SELECT s.category c, s.code code, s.name name, SUM(e.amount) a, COUNT(*) n"
        " FROM expenses e JOIN subjects s ON s.code=e.subject_code"
        " WHERE e.period=? AND e.status='已批准' GROUP BY s.code ORDER BY s.code",
        (period,)).fetchall()
    by_cat = {}
    for r in rows:
        by_cat[r["c"]] = cost.q2(by_cat.get(r["c"], 0) + cost.safe_num(r["a"]))
    by_center = cn.execute(
        "SELECT c.code,c.name,SUM(e.amount) a FROM expenses e JOIN cost_centers c"
        " ON c.code=e.center_code WHERE e.period=? AND e.status='已批准'"
        " GROUP BY c.code ORDER BY a DESC", (period,)).fetchall()
    return {"period": period,
            "bySubject": [{"code": r["code"], "name": r["name"], "category": r["c"],
                           "amount": cost.q2(r["a"]), "count": r["n"]} for r in rows],
            "byCategory": [{"name": k, "amount": v} for k, v in by_cat.items()],
            "byCenter": [{"code": r["code"], "name": r["name"], "amount": cost.q2(r["a"])}
                         for r in by_center],
            "total": cost.q2(sum(i["amount"] for i in
                                 [{"amount": cost.safe_num(r["a"])} for r in rows]))}


# ---------------------------------------------------------------- 分摊

def api_rule_list(u, m, body):
    cn = connect()
    rows = cn.execute(
        "SELECT r.*, f.name fname, t.name tname, f.alloc_order fo, t.alloc_order tn"
        " FROM allocation_rules r JOIN cost_centers f ON f.code=r.from_center"
        " JOIN cost_centers t ON t.code=r.to_center ORDER BY f.alloc_order, r.from_center",).fetchall()
    return {"list": [{"id": r["id"], "from": r["from_center"], "fromName": r["fname"],
                      "to": r["to_center"], "toName": r["tname"], "driver": r["driver"],
                      "weight": cost.safe_num(r["weight"]), "enabled": bool(r["enabled"]),
                      "fromOrder": r["fo"], "toOrder": r["tn"]} for r in rows],
            "drivers": cost.DRIVERS}


def api_rule_create(u, m, body):
    cn = connect()
    f = (body.get("from") or body.get("from_center") or "").strip()
    t = (body.get("to") or body.get("to_center") or "").strip()
    if not f or not t:
        bad("分入/分出中心必填")
    if f == t:
        bad("分摊规则非法：不能向自己分摊")
    cnt = cn.execute("SELECT code,alloc_order FROM cost_centers WHERE code IN (?,?)",
                     (f, t)).fetchall()
    orders = {r["code"]: r["alloc_order"] for r in cnt}
    err = cost.check_step_rules(orders, [{"from_center": f, "to_center": t}])
    if err:
        bad(err)
    w = cost.safe_num(body.get("weight"), 1)
    if w <= 0:
        bad("权重必须大于 0")
    if cn.execute("SELECT id FROM allocation_rules WHERE from_center=? AND to_center=?",
                  (f, t)).fetchone():
        bad("该分摊规则已存在", 409)
    cn.execute("INSERT INTO allocation_rules(from_center,to_center,driver,weight,enabled,created)"
               " VALUES(?,?,?,?,1,?)", (f, t, body.get("driver") or "人工工时", w, cost.now_str()))
    log(cn, u["username"], "新建分摊规则", "%s→%s" % (f, t))
    cn.commit()
    return {"ok": True}


def api_rule_delete(u, m, body):
    cn = connect()
    rid = int(m.group(1))
    if not cn.execute("SELECT id FROM allocation_rules WHERE id=?", (rid,)).fetchone():
        bad("分摊规则不存在", 404)
    cn.execute("DELETE FROM allocation_rules WHERE id=?", (rid,))
    log(cn, u["username"], "删除分摊规则", str(rid))
    cn.commit()
    return {"ok": True}


def api_alloc_run(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    guard_period(cn, period)
    ensure_period(cn, period)
    orders = {r["code"]: r["alloc_order"] for r in
              cn.execute("SELECT code,alloc_order FROM cost_centers").fetchall()}
    edges = [dict(r) for r in cn.execute(
        "SELECT from_center,to_center,driver,weight FROM allocation_rules WHERE enabled=1").fetchall()]
    if not edges:
        bad("尚未配置任何分摊规则")
    direct = {r["c"]: cost.q2(r["a"]) for r in cn.execute(
        "SELECT center_code c, SUM(amount) a FROM expenses WHERE period=? AND status='已批准'"
        " GROUP BY center_code", (period,)).fetchall()}
    if not direct:
        bad("期间 %s 没有已批准的费用归集，无法分摊" % period)
    res = cost.step_down(direct, orders, edges)
    if not res["ok"]:
        bad(res["error"])
    if not cost.ok_diff(res["baseTotal"], res["allocatedTotal"]):
        bad("分摊守恒校验失败：分摊前 %.2f，分摊出 %.2f" % (res["baseTotal"], res["allocatedTotal"]), 500)
    day = period.replace("-", "")
    seq = int(cost.safe_num(val(cn, "SELECT COUNT(*) FROM allocation_runs WHERE no LIKE ?",
                                 ("AL%s-%%" % day,))) + 1)
    while cn.execute("SELECT id FROM allocation_runs WHERE no=?",
                     (cost.doc_no("AL", day, seq),)).fetchone():
        seq += 1
    no = cost.doc_no("AL", day, seq)
    cn.execute("INSERT INTO allocation_runs(no,period,method,status,base_total,allocated_total,"
               "check_diff,operator,created) VALUES(?,?,?,?,?,?,?,?,?)",
               (no, period, body.get("method") or "阶梯法", "已完成", res["baseTotal"],
                res["allocatedTotal"], res["checkDiff"], u["username"], cost.now_str()))
    for ln in res["lines"]:
        cn.execute("INSERT INTO allocation_lines(run_no,step,from_center,to_center,driver,weight,"
                   "base_amount,amount) VALUES(?,?,?,?,?,?,?,?)",
                   (no, ln["step"], ln["fromCenter"], ln["toCenter"], ln["driver"],
                    ln["weight"], ln["baseAmount"], ln["amount"]))
    log(cn, u["username"], "执行成本分摊", "%s 总额 %.2f" % (no, res["allocatedTotal"]))
    fire_event(cn, "alloc.executed", {"no": no, "period": period,
                                      "total": res["allocatedTotal"]})
    cn.commit()
    return {"no": no, "period": period, "lines": res["lines"], "baseTotal": res["baseTotal"],
            "allocatedTotal": res["allocatedTotal"], "checkDiff": res["checkDiff"],
            "orphans": res["orphans"]}


def api_alloc_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    where, args = [], []
    if qs.get("period"):
        where.append("period=?")
        args.append(qs["period"])
    rows = cn.execute("SELECT * FROM allocation_runs" +
                      (" WHERE " + " AND ".join(where) if where else "") +
                      " ORDER BY id DESC", args).fetchall()
    return {"list": [{"no": r["no"], "period": r["period"], "method": r["method"],
                      "baseTotal": cost.q2(r["base_total"]),
                      "allocatedTotal": cost.q2(r["allocated_total"]),
                      "checkDiff": cost.q2(r["check_diff"]), "status": r["status"],
                      "operator": r["operator"], "createdAt": r["created"]} for r in rows]}


def api_alloc_detail(u, m, body):
    cn = connect()
    no = m.group(1)
    r = cn.execute("SELECT * FROM allocation_runs WHERE no=?", (no,)).fetchone()
    if not r:
        bad("分摊批次不存在", 404)
    lines = cn.execute(
        "SELECT l.*, f.name fname, t.name tname FROM allocation_lines l"
        " JOIN cost_centers f ON f.code=l.from_center JOIN cost_centers t ON t.code=l.to_center"
        " WHERE l.run_no=? ORDER BY l.step, l.id", (no,)).fetchall()
    return {"run": {"no": r["no"], "period": r["period"], "method": r["method"],
                    "baseTotal": cost.q2(r["base_total"]),
                    "allocatedTotal": cost.q2(r["allocated_total"]),
                    "checkDiff": cost.q2(r["check_diff"]), "status": r["status"],
                    "operator": r["operator"], "createdAt": r["created"]},
            "lines": [{"step": x["step"], "from": x["from_center"], "fromName": x["fname"],
                       "to": x["to_center"], "toName": x["tname"], "driver": x["driver"],
                       "weight": cost.safe_num(x["weight"]),
                       "baseAmount": cost.q2(x["base_amount"]),
                       "amount": cost.q2(x["amount"])} for x in lines]}


# ---------------------------------------------------------------- 预算

def api_budget_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute(
        "SELECT b.*, c.name cname, s.name sname, s.category FROM budgets b"
        " JOIN cost_centers c ON c.code=b.center_code"
        " JOIN subjects s ON s.code=b.subject_code WHERE b.period=? ORDER BY b.center_code",
        (period,)).fetchall()
    warn = rule_num(cn, "warn_rate", 0.9)
    block = rule_num(cn, "block_rate", 1.1)
    items = []
    for r in rows:
        st = cost.budget_state(r["amount"], r["used"], warn, block)
        items.append({"period": r["period"], "center": r["center_code"],
                      "centerName": r["cname"], "subject": r["subject_code"],
                      "subjectName": r["sname"], "category": r["category"],
                      "amount": cost.q2(r["amount"]), "used": cost.q2(r["used"]),
                      "rate": st["rate"], "level": st["level"], "left": st["left"]})
    return {"list": items, "period": period}


def api_budget_upsert(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    guard_period(cn, period)
    ensure_period(cn, period)
    center = (body.get("center") or "").strip()
    subj = (body.get("subject") or "").strip()
    amount = cost.safe_num(body.get("amount"))
    if not center or not subj:
        bad("成本中心与科目必填")
    if amount < 0:
        bad("预算金额不能为负")
    if not val(cn, "SELECT COUNT(*) FROM cost_centers WHERE code=?", (center,)):
        bad("成本中心不存在：%s" % center)
    if not val(cn, "SELECT COUNT(*) FROM subjects WHERE code=?", (subj,)):
        bad("科目不存在：%s" % subj)
    used = cost.safe_num(val(cn, "SELECT SUM(amount) FROM expenses WHERE period=? AND"
                             " center_code=? AND subject_code=? AND status='已批准'",
                             (period, center, subj)))
    cn.execute("INSERT INTO budgets(period,center_code,subject_code,amount,used,remark,created)"
               " VALUES(?,?,?,?,?,?,?) ON CONFLICT(period,center_code,subject_code)"
               " DO UPDATE SET amount=excluded.amount,used=excluded.used,remark=excluded.remark",
               (period, center, subj, amount, cost.q2(used), body.get("remark") or "",
                cost.now_str()))
    log(cn, u["username"], "设定预算", "%s %s/%s = %.2f" % (period, center, subj, amount))
    fire_event(cn, "budget.updated", {"period": period, "center": center, "amount": amount})
    cn.commit()
    return {"ok": True}


def api_budget_exec(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    warn = rule_num(cn, "warn_rate", 0.9)
    block = rule_num(cn, "block_rate", 1.1)
    rows = cn.execute(
        "SELECT b.*, c.name cname, s.name sname FROM budgets b"
        " JOIN cost_centers c ON c.code=b.center_code JOIN subjects s ON s.code=b.subject_code"
        " WHERE b.period=? ORDER BY (b.used*1.0/NULLIF(b.amount,0)) DESC", (period,)).fetchall()
    items = []
    for r in rows:
        st = cost.budget_state(r["amount"], r["used"], warn, block)
        items.append({"center": r["center_code"], "centerName": r["cname"],
                      "subject": r["subject_code"], "subjectName": r["sname"],
                      "amount": cost.q2(r["amount"]), "used": cost.q2(r["used"]),
                      "rate": st["rate"], "level": st["level"], "left": st["left"]})
    total_a = cost.q2(sum(i["amount"] for i in items))
    total_u = cost.q2(sum(i["used"] for i in items))
    by_center = {}
    for i in items:
        d = by_center.setdefault(i["center"], {"center": i["center"],
                                               "centerName": i["centerName"],
                                               "amount": 0.0, "used": 0.0})
        d["amount"] = cost.q2(d["amount"] + i["amount"])
        d["used"] = cost.q2(d["used"] + i["used"])
    return {"period": period, "list": items,
            "byCenter": sorted(by_center.values(), key=lambda x: -x["used"]),
            "total": {"amount": total_a, "used": total_u,
                      "rate": round(total_u / total_a, 4) if total_a else 0.0},
            "abnormal": [i for i in items if i["level"] in ("超支", "阻断区", "预警")]}


# ---------------------------------------------------------------- 差异分析

def _std_qty_and_price(cn, product, qty):
    """按 BOM 计算标准用量与加权标准单价。"""
    bom = cn.execute("SELECT * FROM bom_lines WHERE product_code=?", (product,)).fetchall()
    std_qty = 0.0
    std_amount = 0.0
    for b in bom:
        per = cost.safe_num(b["qty_per"]) * (1 + cost.safe_num(b["loss_rate"]))
        std_qty += per * qty
        std_amount += per * qty * cost.safe_num(b["std_price"])
    return std_qty, (std_amount / std_qty if std_qty else 0.0)


def _calc_one(cn, period, product, wo_no=None):
    where = "period=? AND product_code=?"
    args = [period, product]
    if wo_no:
        where += " AND no=?"
        args.append(wo_no)
    rows = cn.execute("SELECT * FROM work_orders WHERE " + where +
                      " AND status IN ('已完工','已关闭')", args).fetchall()
    if not rows:
        return None, "产品 %s 在期间 %s 没有已完工工单，无法计算差异" % (product, period)
    qty = sum(cost.safe_num(r["qty_done"]) for r in rows)
    act_total = sum(cost.safe_num(r["total_actual"]) for r in rows)
    std = cn.execute("SELECT * FROM std_costs WHERE period=? AND product_code=?"
                     " ORDER BY version DESC LIMIT 1", (period, product)).fetchone()
    if not std:
        return None, "产品 %s 在期间 %s 没有标准成本，请先计算标准成本" % (product, period)
    std_unit = cost.safe_num(std["unit_cost"])
    # 材料：标准用量 × 标准单价 vs 实际用量 × 实际单价
    std_qty, std_price = _std_qty_and_price(cn, product, qty)
    act_qty = 0.0
    for r in rows:
        act_qty += cost.safe_num(val(cn, "SELECT SUM(qty) FROM wo_materials WHERE wo_no=?",
                                     (r["no"],)))
    act_mat = sum(cost.safe_num(r["mat_actual"]) for r in rows)
    act_price = act_mat / act_qty if act_qty else 0.0
    mat_v = cost.material_variance(std_qty, std_price, act_qty, act_price)
    # 人工：标准工时 × 标准费率 vs 实际工时 × 实际费率
    cr = cn.execute("SELECT labor_rate,oh_rate FROM cost_centers WHERE code=?",
                    (rows[0]["center_code"],)).fetchone()
    std_hours_rate = cost.safe_num(cr["labor_rate"]) if cr else 0.0
    oh_rate = cost.safe_num(cr["oh_rate"]) if cr else 0.0
    std_hours = cost.safe_num(val(cn, "SELECT SUM(std_hours) FROM products WHERE code=?",
                                  (product,))) * qty
    act_hours = sum(cost.safe_num(val(cn, "SELECT SUM(hours) FROM wo_labor WHERE wo_no=?",
                                         (r["no"],))) for r in rows)
    act_labor = sum(cost.safe_num(r["labor_actual"]) for r in rows)
    act_rate = act_labor / act_hours if act_hours else std_hours_rate
    labor_v = cost.labor_variance(std_hours, std_hours_rate, act_hours, act_rate)
    # 制造费用：预算（本期该中心制造费用预算）vs 实际
    budget_oh = cost.safe_num(val(cn, "SELECT SUM(b.amount) FROM budgets b JOIN subjects s"
                                    " ON s.code=b.subject_code WHERE b.period=?"
                                    " AND b.center_code=? AND s.category='制造费用'",
                                  (period, rows[0]["center_code"])))
    act_oh = sum(cost.safe_num(r["oh_actual"]) for r in rows)
    oh_v = cost.oh_variance(oh_rate, std_hours, act_hours, act_oh, budget_oh)
    pv = cost.product_variance(std_unit, act_total, qty, mat_v, labor_v, oh_v)
    # 尾差归入材料量差：标准单位成本入库时按两位小数取整，× 产量后会有分位残差，
    # 归入量差可保证「价差+量差+工资率差+效率差+耗费差 = 总差异」精确闭合。
    resid = cost.q2(pv["totalVar"] - (pv["priceVar"] + pv["qtyVar"] + pv["rateVar"]
                                      + pv["effVar"] + pv["expenseVar"]))
    qty_var = cost.q2(pv["qtyVar"] + resid)
    check = cost.q2(pv["totalVar"] - (pv["priceVar"] + qty_var + pv["rateVar"]
                                      + pv["effVar"] + pv["expenseVar"]))
    return {"period": period, "product": product, "fromWo": wo_no or "",
            "qty": round(qty, 4), "stdUnitCost": std_unit,
            "actUnitCost": round(act_total / qty, 4) if qty else 0.0,
            "stdTotal": pv["stdTotal"], "actTotal": pv["actTotal"],
            "totalVar": pv["totalVar"], "priceVar": mat_v["priceVar"],
            "qtyVar": qty_var, "rateVar": labor_v["rateVar"],
            "effVar": pv["effVar"], "expenseVar": pv["expenseVar"],
            "checkDiff": check, "level": pv["level"],
            "actHours": round(act_hours, 2), "stdHours": round(std_hours, 2)}, None


def api_variance_list(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    where, args = [], []
    if qs.get("period"):
        where.append("period=?")
        args.append(qs["period"])
    if qs.get("product"):
        where.append("product_code=?")
        args.append(qs["product"])
    rows = cn.execute("SELECT * FROM variances" +
                      (" WHERE " + " AND ".join(where) if where else "") +
                      " ORDER BY ABS(total_var) DESC", args).fetchall()
    names = {r["code"]: r["name"] for r in cn.execute("SELECT code,name FROM products").fetchall()}
    return {"list": [{"period": r["period"], "product": r["product_code"],
                      "productName": names.get(r["product_code"], ""),
                      "fromWo": r["from_wo"], "qty": cost.safe_num(r["qty"]),
                      "stdUnitCost": cost.safe_num(r["std_unit_cost"]),
                      "actUnitCost": cost.safe_num(r["act_unit_cost"]),
                      "stdTotal": cost.q2(r["std_total"]), "actTotal": cost.q2(r["act_total"]),
                      "totalVar": cost.q2(r["total_var"]), "priceVar": cost.q2(r["price_var"]),
                      "qtyVar": cost.q2(r["qty_var"]), "rateVar": cost.q2(r["rate_var"]),
                      "effVar": cost.q2(r["eff_var"]), "expenseVar": cost.q2(r["expense_var"]),
                      "checkDiff": cost.q2(r["check_diff"]), "level": r["level"],
                      "calcAt": r["calc_at"]} for r in rows]}


def api_variance_calc(u, m, body):
    cn = connect()
    period = body.get("period") or cost.cur_period()
    ensure_period(cn, period)
    only = body.get("product")
    wo = body.get("wo")
    if only:
        prods = [only.strip().upper()]
    else:
        prods = [r["code"] for r in cn.execute(
            "SELECT DISTINCT product_code code FROM work_orders WHERE period=? AND status IN"
            " ('已完工','已关闭')", (period,)).fetchall()]
    if not prods:
        bad("期间 %s 没有已完工工单，无法计算差异" % period)
    done, errors = [], []
    for p in prods:
        d, err = _calc_one(cn, period, p, wo)
        if err:
            errors.append(err)
            continue
        cn.execute("DELETE FROM variances WHERE period=? AND product_code=? AND from_wo=?",
                   (period, p, d["fromWo"]))
        cn.execute("INSERT INTO variances(period,product_code,from_wo,qty,std_unit_cost,"
                   "act_unit_cost,std_total,act_total,total_var,price_var,qty_var,rate_var,"
                   "eff_var,expense_var,check_diff,level,calc_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (period, p, d["fromWo"], d["qty"], d["stdUnitCost"], d["actUnitCost"],
                    d["stdTotal"], d["actTotal"], d["totalVar"], d["priceVar"], d["qtyVar"],
                    d["rateVar"], d["effVar"], d["expenseVar"], d["checkDiff"], d["level"],
                    cost.now_str()))
        done.append(d)
    if not done:
        bad("；".join(errors) or "没有可计算的差异")
    log(cn, u["username"], "计算成本差异", "%s %d 个产品" % (period, len(done)))
    fire_event(cn, "variance.calculated", {"period": period, "count": len(done)})
    cn.commit()
    return {"period": period, "count": len(done), "items": done, "warnings": errors}


# ---------------------------------------------------------------- 报表

def api_rep_center_summary(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute("SELECT * FROM cost_centers ORDER BY alloc_order, code").fetchall()
    items = []
    for r in rows:
        d = center_row(cn, r, period)
        bd = cost.safe_num(val(cn, "SELECT SUM(amount) FROM budgets WHERE period=?"
                                 " AND center_code=?", (period, r["code"])))
        items.append({"code": d["code"], "name": d["name"], "ctype": d["ctype"],
                      "direct": d["directCost"], "allocIn": d["allocIn"],
                      "allocOut": d["allocOut"], "total": d["netCost"],
                      "budget": cost.q2(bd),
                      "rate": round(d["netCost"] / bd, 4) if bd else 0.0,
                      "orderCount": d["orderCount"]})
    return {"period": period, "list": items,
            "total": {"direct": cost.q2(sum(i["direct"] for i in items)),
                      "allocIn": cost.q2(sum(i["allocIn"] for i in items)),
                      "allocOut": cost.q2(sum(i["allocOut"] for i in items)),
                      "net": cost.q2(sum(i["total"] for i in items))}}


def api_rep_product_cost(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    rows = cn.execute(
        "SELECT wo.product_code p, SUM(wo.qty_done) q, SUM(wo.total_actual) a,"
        " SUM(wo.finished_cost) f FROM work_orders wo WHERE wo.period=? AND wo.status IN"
        " ('已完工','已关闭') GROUP BY wo.product_code", (period,)).fetchall()
    out = []
    for r in rows:
        std = cn.execute("SELECT unit_cost FROM std_costs WHERE period=? AND product_code=?"
                         " ORDER BY version DESC LIMIT 1", (period, r["p"])).fetchone()
        std_unit = cost.safe_num(std["unit_cost"]) if std else 0.0
        q = cost.safe_num(r["q"])
        act_unit = cost.safe_num(r["a"]) / q if q else 0.0
        var = cost.q2(cost.safe_num(r["a"]) - std_unit * q)
        p = cn.execute("SELECT name,unit,list_price FROM products WHERE code=?",
                       (r["p"],)).fetchone()
        margin = cost.unit_margin(p["list_price"] if p else 0, act_unit)
        out.append({"product": r["p"], "productName": p["name"] if p else "",
                    "unit": p["unit"] if p else "", "qty": round(q, 2),
                    "stdUnit": cost.q2(std_unit), "actUnit": round(act_unit, 4),
                    "stdTotal": cost.q2(std_unit * q), "actTotal": cost.q2(r["a"]),
                    "var": var, "varRate": round(var / (std_unit * q), 4) if std_unit * q else 0.0,
                    "level": cost.variance_level(var, std_unit * q),
                    "listPrice": cost.q2(p["list_price"]) if p else 0.0,
                    "grossProfit": margin["grossProfit"], "grossRate": margin["grossRate"]})
    return {"period": period, "list": out,
            "total": {"std": cost.q2(sum(i["stdTotal"] for i in out)),
                      "act": cost.q2(sum(i["actTotal"] for i in out)),
                      "var": cost.q2(sum(i["var"] for i in out))}}


def api_rep_variance_top(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    period = qs.get("period") or cost.cur_period()
    n = int(cost.safe_num(qs.get("n"), 10))
    rows = cn.execute("SELECT * FROM variances WHERE period=? ORDER BY ABS(total_var) DESC"
                      " LIMIT ?", (period, n)).fetchall()
    names = {r["code"]: r["name"] for r in cn.execute("SELECT code,name FROM products").fetchall()}
    return {"period": period, "list": [{"product": r["product_code"],
                                        "productName": names.get(r["product_code"], ""),
                                        "totalVar": cost.q2(r["total_var"]),
                                        "priceVar": cost.q2(r["price_var"]),
                                        "qtyVar": cost.q2(r["qty_var"]),
                                        "rateVar": cost.q2(r["rate_var"]),
                                        "effVar": cost.q2(r["eff_var"]),
                                        "expenseVar": cost.q2(r["expense_var"]),
                                        "level": r["level"]} for r in rows]}


def api_rep_trend(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    months = int(cost.safe_num(qs.get("months"), 6))
    period = qs.get("period") or cost.cur_period()
    out = []
    for i in range(months - 1, -1, -1):
        p = cost.prev_period(period, i)
        std = cost.safe_num(val(cn, "SELECT SUM(sc.unit_cost*wo.qty_done) FROM work_orders wo"
                                " JOIN std_costs sc ON sc.product_code=wo.product_code AND"
                                " sc.period=wo.period WHERE wo.period=? AND wo.status IN"
                                " ('已完工','已关闭')", (p,)))
        act = cost.safe_num(val(cn, "SELECT SUM(total_actual) FROM work_orders WHERE period=?"
                                " AND status IN ('已完工','已关闭')", (p,)))
        direct = cost.safe_num(val(cn, "SELECT SUM(amount) FROM expenses WHERE period=?"
                                   " AND status='已批准'", (p,)))
        qty = cost.safe_num(val(cn, "SELECT SUM(qty_done) FROM work_orders WHERE period=?"
                               " AND status IN ('已完工','已关闭')", (p,)))
        out.append({"period": p, "standard": cost.q2(std), "actual": cost.q2(act),
                    "direct": cost.q2(direct), "qty": round(qty, 2),
                    "variance": cost.q2(act - std),
                    "varRate": round((act - std) / std, 4) if std else 0.0})
    return {"list": out, "period": period}


# ---------------------------------------------------------------- CSV 导出

def _csv_out(name, headers, rows):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return {"__csv__": name, "text": buf.getvalue()}


def api_export(u, m, kind):
    cn = connect()
    qs = m.get("_q") if isinstance(m, dict) else {}
    period = (qs or {}).get("period") or cost.cur_period()
    if kind == "centers":
        data = api_rep_center_summary(u, None, {"_q": {"period": period}})["list"]
        return _csv_out("成本中心汇总_%s.csv" % period,
                        ["中心编码", "中心名称", "类型", "直接归集", "分入", "分出", "净成本",
                         "预算", "执行率", "工单数"],
                        [[x["code"], x["name"], x["ctype"], x["direct"], x["allocIn"],
                          x["allocOut"], x["total"], x["budget"], x["rate"], x["orderCount"]]
                         for x in data])
    if kind == "products":
        data = api_rep_product_cost(u, None, {"_q": {"period": period}})["list"]
        return _csv_out("产品成本卡_%s.csv" % period,
                        ["产品编码", "产品名称", "产量", "单位标准成本", "单位实际成本",
                         "标准总额", "实际总额", "差异", "差异率", "等级", "售价", "毛利率"],
                        [[x["product"], x["productName"], x["qty"], x["stdUnit"], x["actUnit"],
                          x["stdTotal"], x["actTotal"], x["var"], x["varRate"], x["level"],
                          x["listPrice"], x["grossRate"]] for x in data])
    if kind == "expenses":
        rows = cn.execute("SELECT * FROM expenses WHERE period=? ORDER BY no", (period,)).fetchall()
        data = [exp_row(cn, r) for r in rows]
        return _csv_out("费用归集_%s.csv" % period,
                        ["单号", "期间", "成本中心", "科目", "金额", "来源", "摘要", "状态", "申请人"],
                        [[x["no"], x["period"], x["centerName"], x["subjectName"], x["amount"],
                          x["source"], x["summary"], x["status"], x["applicant"]] for x in data])
    if kind == "variances":
        data = api_variance_list(u, None, {"_q": {"period": period}})["list"]
        return _csv_out("成本差异_%s.csv" % period,
                        ["期间", "产品", "产量", "标准单位成本", "实际单位成本", "标准总额",
                         "实际总额", "总差异", "价差", "量差", "工资率差", "效率差", "耗费差", "等级"],
                        [[x["period"], x["product"], x["qty"], x["stdUnitCost"], x["actUnitCost"],
                          x["stdTotal"], x["actTotal"], x["totalVar"], x["priceVar"], x["qtyVar"],
                          x["rateVar"], x["effVar"], x["expenseVar"], x["level"]] for x in data])
    bad("不支持的导出类型：%s" % kind, 404)


# ---------------------------------------------------------------- 期间

def api_period_list(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT * FROM periods ORDER BY period DESC").fetchall()
    out = []
    for r in rows:
        p = r["period"]
        out.append({"period": p, "status": r["status"], "closedAt": r["closed_at"],
                    "closedBy": r["closed_by"],
                    "expenseCount": val(cn, "SELECT COUNT(*) FROM expenses WHERE period=?", (p,)),
                    "pendingExpenses": val(cn, "SELECT COUNT(*) FROM expenses WHERE period=?"
                                                " AND status='待审批'", (p,)),
                    "orderCount": val(cn, "SELECT COUNT(*) FROM work_orders WHERE period=?", (p,)),
                    "openOrders": val(cn, "SELECT COUNT(*) FROM work_orders WHERE period=?"
                                           " AND status IN ('草稿','在生产')", (p,)),
                    "allocDone": bool(val(cn, "SELECT COUNT(*) FROM allocation_runs WHERE"
                                              " period=?", (p,))),
                    "expenseTotal": cost.q2(val(cn, "SELECT SUM(amount) FROM expenses WHERE"
                                                 " period=? AND status='已批准'", (p,)))})
    return {"list": out}


def api_period_create(u, m, body):
    cn = connect()
    period = (body.get("period") or "").strip()
    if not period or len(period) != 7 or period[4] != "-":
        bad("期间格式应为 YYYY-MM")
    if cn.execute("SELECT id FROM periods WHERE period=?", (period,)).fetchone():
        bad("期间已存在：%s" % period, 409)
    cn.execute("INSERT INTO periods(period,status,remark,created) VALUES(?,'打开',?,?)",
               (period, body.get("remark") or "", cost.now_str()))
    log(cn, u["username"], "新建期间", period)
    cn.commit()
    return {"period": period}


def api_period_close(u, m, body):
    cn = connect()
    period = m.group(1)
    r = cn.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
    if not r:
        bad("期间不存在：%s" % period, 404)
    ctx = {"pending_expenses": val(cn, "SELECT COUNT(*) FROM expenses WHERE period=?"
                                        " AND status='待审批'", (period,)),
           "open_orders": val(cn, "SELECT COUNT(*) FROM work_orders WHERE period=?"
                                   " AND status IN ('草稿','在生产')", (period,)),
           "alloc_done": bool(val(cn, "SELECT COUNT(*) FROM allocation_runs WHERE period=?",
                                  (period,))),
           "period_closed": r["status"] == "已结账"}
    err = cost.close_gate(ctx)
    if err:
        bad(err, 409)
    cn.execute("UPDATE periods SET status='已结账',closed_at=?,closed_by=? WHERE period=?",
               (cost.now_str(), u["username"], period))
    log(cn, u["username"], "期间结账", period)
    fire_event(cn, "period.closed", {"period": period})
    cn.commit()
    return {"ok": True, "period": period, "status": "已结账"}


def api_period_reopen(u, m, body):
    cn = connect()
    period = m.group(1)
    r = cn.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
    if not r:
        bad("期间不存在", 404)
    if r["status"] != "已结账":
        bad("期间未结账，无需反结账", 409)
    cn.execute("UPDATE periods SET status='打开',closed_at='',closed_by='' WHERE period=?",
               (period,))
    log(cn, u["username"], "反结账", "%s（原因：%s）" % (period, body.get("reason") or "未填"))
    cn.commit()
    return {"ok": True, "period": period, "status": "打开"}


# ---------------------------------------------------------------- 系统

def api_rules(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT * FROM rules ORDER BY category, code").fetchall()
    return {"list": [{"code": r["code"], "name": r["name"], "category": r["category"],
                      "value": r["value"], "unit": r["unit"], "enabled": bool(r["enabled"]),
                      "remark": r["remark"]} for r in rows]}


def api_rule_update(u, m, body):
    cn = connect()
    code = m.group(1)
    if not cn.execute("SELECT code FROM rules WHERE code=?", (code,)).fetchone():
        bad("规则不存在", 404)
    if "value" in body:
        cn.execute("UPDATE rules SET value=? WHERE code=?", (str(body["value"]), code))
    if "enabled" in body:
        cn.execute("UPDATE rules SET enabled=? WHERE code=?", (1 if body["enabled"] else 0, code))
    log(cn, u["username"], "修改规则", code)
    cn.commit()
    return {"ok": True}


def api_user_list(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT username,name,role,dept,created FROM users ORDER BY id").fetchall()
    return {"list": [{"username": r["username"], "name": r["name"], "role": r["role"],
                      "roleName": cost.ROLES.get(r["role"], {}).get("name", r["role"]),
                      "dept": r["dept"], "created": r["created"]} for r in rows],
            "roles": [{"code": k, "name": v["name"]} for k, v in cost.ROLES.items()]}


def api_user_create(u, m, body):
    cn = connect()
    uname = (body.get("username") or "").strip()
    pwd = body.get("password") or ""
    if not uname or not body.get("name"):
        bad("账号与姓名必填")
    if len(pwd) < 8:
        bad("初始密码至少 8 位")
    if cn.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone():
        bad("账号已存在：%s" % uname, 409)
    role = body.get("role") or "viewer"
    if role not in cost.ROLES:
        bad("角色非法：%s" % role)
    salt = os.urandom(8).hex()
    cn.execute("INSERT INTO users(username,password_hash,salt,name,role,dept,created)"
               " VALUES(?,?,?,?,?,?,?)",
               (uname, hash_pwd(pwd, salt), salt, body["name"], role, body.get("dept") or "",
                cost.now_str()))
    log(cn, u["username"], "新建用户", "%s(%s)" % (uname, role))
    cn.commit()
    return {"username": uname}


def api_logs(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    limit = int(cost.safe_num(qs.get("limit"), 200))
    rows = cn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"list": [{"at": r["at"], "user": r["user"], "action": r["action"],
                      "detail": r["detail"]} for r in rows]}


def api_key_list(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT id,prefix,name,scope,created,last_used,revoked FROM api_keys"
                      " ORDER BY id DESC").fetchall()
    return {"list": [{"id": r["id"], "prefix": r["prefix"], "name": r["name"],
                      "scope": r["scope"], "created": r["created"],
                      "lastUsed": r["last_used"], "revoked": bool(r["revoked"])} for r in rows]}


def api_key_create(u, m, body):
    cn = connect()
    name = (body.get("name") or "").strip()
    if not name:
        bad("Key 名称必填")
    raw = "fb_" + os.urandom(18).hex()
    scope = body.get("scope") or "read"
    if scope not in ("read", "write"):
        bad("scope 只能是 read 或 write")
    cn.execute("INSERT INTO api_keys(key_hash,prefix,name,scope,created) VALUES(?,?,?,?,?)",
               (hashlib.sha256(raw.encode()).hexdigest(), raw[:10], name, scope, cost.now_str()))
    log(cn, u["username"], "创建API Key", name)
    cn.commit()
    return {"key": raw, "once": True}


def api_key_revoke(u, m, body):
    cn = connect()
    kid = int(m.group(1))
    if not cn.execute("SELECT id FROM api_keys WHERE id=?", (kid,)).fetchone():
        bad("Key 不存在", 404)
    cn.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (kid,))
    log(cn, u["username"], "吊销API Key", str(kid))
    cn.commit()
    return {"ok": True}


def api_wh_list(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT id,name,url,events,enabled,created FROM webhooks ORDER BY id").fetchall()
    return {"list": [{"id": r["id"], "name": r["name"], "url": r["url"],
                      "events": r["events"], "enabled": bool(r["enabled"]),
                      "created": r["created"]} for r in rows], "events": EVENTS}


def api_wh_create(u, m, body):
    cn = connect()
    if not body.get("url") or not body.get("events"):
        bad("URL 与订阅事件必填")
    secret = body.get("secret") or os.urandom(12).hex()
    cn.execute("INSERT INTO webhooks(name,url,secret,events,enabled,created)"
               " VALUES(?,?,?,?,1,?)",
               (body.get("name") or "hook", body["url"], secret, body["events"], cost.now_str()))
    log(cn, u["username"], "创建Webhook", body["url"])
    cn.commit()
    return {"ok": True, "secret": secret}


def api_wh_test(u, m, body):
    cn = connect()
    fire_event(cn, "test.ping", {"by": u["username"]})
    cn.commit()
    return {"ok": True, "queued": True}


def api_wh_deliveries(u, m, body):
    cn = connect()
    rows = cn.execute("SELECT * FROM webhook_deliveries ORDER BY id DESC LIMIT 100").fetchall()
    return {"list": [{"id": r["id"], "webhookId": r["webhook_id"], "event": r["event"],
                      "status": r["status"], "attempts": r["attempts"],
                      "lastAt": r["last_at"], "response": r["response"]} for r in rows]}


def api_sync(u, m, body):
    cn = connect()
    qs = body.get("_q") or {}
    since = qs.get("since") or ""
    out = {"since": since, "serverTime": cost.now_str()}
    for entity, sql, key in (
            ("centers", "SELECT code,name,ctype,alloc_order FROM cost_centers", "code"),
            ("products", "SELECT code,name,unit,std_hours FROM products", "code"),
            ("orders", "SELECT no,product_code,period,status,total_actual FROM work_orders"
                       " WHERE period=?", "no"),
            ("expenses", "SELECT no,period,center_code,amount,status FROM expenses WHERE period=?",
             "no")):
        args = (cost.cur_period(),) if "period" in sql else ()
        out[entity] = [dict(r) for r in cn.execute(sql, args).fetchall()]
    rs = cn.execute("SELECT entity,last_at FROM sync_state").fetchall()
    out["state"] = {r["entity"]: r["last_at"] for r in rs}
    return out


def api_health(u, m, body):
    cn = connect()
    return {"brand": BRAND, "version": VERSION, "routes": len(ROUTES), "events": len(EVENTS),
            "centers": val(cn, "SELECT COUNT(*) FROM cost_centers"),
            "products": val(cn, "SELECT COUNT(*) FROM products"),
            "orders": val(cn, "SELECT COUNT(*) FROM work_orders"),
            "expenses": val(cn, "SELECT COUNT(*) FROM expenses"),
            "time": cost.now_str()}


def api_openapi(u, m, body):
    return openapi_json()


# ---------------------------------------------------------------- 路由表

ROUTES = [
    ("POST", r"^/api/auth/login$", api_login, None),
    ("POST", r"^/api/auth/logout$", api_logout, None),
    ("GET", r"^/api/auth/me$", api_me, None),
    ("PUT", r"^/api/auth/password$", api_password, None),
    ("POST", r"^/api/auth/change-password$", api_password, None),
    ("GET", r"^/api/board$", api_board, None),

    ("GET", r"^/api/cost-centers$", api_center_list, "center.read"),
    ("POST", r"^/api/cost-centers$", api_center_create, "center.write"),
    ("PUT", r"^/api/cost-centers/([^/]+)$", api_center_update, "center.write"),

    ("GET", r"^/api/subjects$", api_subject_list, "subject.read"),
    ("POST", r"^/api/subjects$", api_subject_create, "subject.write"),
    ("PUT", r"^/api/subjects/([^/]+)$", api_subject_update, "subject.write"),

    ("GET", r"^/api/products$", api_product_list, "product.read"),
    ("POST", r"^/api/products$", api_product_create, "product.write"),
    ("GET", r"^/api/products/([^/]+)$", api_product_detail, "product.read"),
    ("PUT", r"^/api/products/([^/]+)$", api_product_update, "product.write"),
    ("GET", r"^/api/products/([^/]+)/bom$", api_bom_list, "product.read"),
    ("POST", r"^/api/products/([^/]+)/bom$", api_bom_add, "product.write"),
    ("DELETE", r"^/api/products/([^/]+)/bom/([0-9]+)$", api_bom_delete, "product.write"),

    ("GET", r"^/api/std-costs$", api_std_list, "std.read"),
    ("POST", r"^/api/std-costs/calc$", api_std_calc, "std.write"),
    ("POST", r"^/api/std-costs/([0-9\-]+)/([^/]+)/publish$", api_std_publish, "std.write"),

    ("GET", r"^/api/work-orders$", api_wo_list, "wo.read"),
    ("POST", r"^/api/work-orders$", api_wo_create, "wo.write"),
    ("GET", r"^/api/work-orders/([^/]+)$", api_wo_detail, "wo.read"),
    ("PUT", r"^/api/work-orders/([^/]+)$", api_wo_update, "wo.write"),
    ("POST", r"^/api/work-orders/([^/]+)/materials$", api_wo_material, "wo.write"),
    ("POST", r"^/api/work-orders/([^/]+)/labor$", api_wo_labor, "wo.write"),
    ("POST", r"^/api/work-orders/([^/]+)/calc$", api_wo_calc, "wo.write"),
    ("POST", r"^/api/work-orders/([^/]+)/stage$", api_wo_stage, "wo.write"),

    ("GET", r"^/api/expenses$", api_exp_list, "exp.read"),
    ("POST", r"^/api/expenses$", api_exp_create, "exp.write"),
    ("GET", r"^/api/expenses/summary$", api_exp_summary, "exp.read"),
    ("POST", r"^/api/expenses/([^/]+)/stage$", api_exp_stage, "exp.write"),

    ("GET", r"^/api/allocation-rules$", api_rule_list, "alloc.read"),
    ("POST", r"^/api/allocation-rules$", api_rule_create, "alloc.write"),
    ("DELETE", r"^/api/allocation-rules/([0-9]+)$", api_rule_delete, "alloc.write"),
    ("POST", r"^/api/allocations/run$", api_alloc_run, "alloc.write"),
    ("GET", r"^/api/allocations$", api_alloc_list, "alloc.read"),
    ("GET", r"^/api/allocations/([^/]+)$", api_alloc_detail, "alloc.read"),

    ("GET", r"^/api/budgets$", api_budget_list, "budget.read"),
    ("POST", r"^/api/budgets$", api_budget_upsert, "budget.write"),
    ("GET", r"^/api/budgets/exec$", api_budget_exec, "budget.read"),

    ("GET", r"^/api/variances$", api_variance_list, "report.read"),
    ("POST", r"^/api/variances/calc$", api_variance_calc, "report.read"),

    ("GET", r"^/api/reports/center-summary$", api_rep_center_summary, "report.read"),
    ("GET", r"^/api/reports/product-cost$", api_rep_product_cost, "report.read"),
    ("GET", r"^/api/reports/variance-top$", api_rep_variance_top, "report.read"),
    ("GET", r"^/api/reports/trend$", api_rep_trend, "report.read"),
    ("GET", r"^/api/reports/(centers|products|expenses|variances)\.csv$", None, None),

    ("GET", r"^/api/periods$", api_period_list, "report.read"),
    ("POST", r"^/api/periods$", api_period_create, "period.close"),
    ("POST", r"^/api/periods/([0-9\-]+)/close$", api_period_close, "period.close"),
    ("POST", r"^/api/periods/([0-9\-]+)/reopen$", api_period_reopen, "admin"),

    ("GET", r"^/api/rules$", api_rules, None),
    ("PUT", r"^/api/rules/([^/]+)$", api_rule_update, "admin"),
    ("GET", r"^/api/users$", api_user_list, "admin"),
    ("POST", r"^/api/users$", api_user_create, "admin"),
    ("GET", r"^/api/logs$", api_logs, "admin"),
    ("GET", r"^/api/keys$", api_key_list, "admin"),
    ("POST", r"^/api/keys$", api_key_create, "admin"),
    ("POST", r"^/api/keys/([0-9]+)/revoke$", api_key_revoke, "admin"),
    ("GET", r"^/api/webhooks$", api_wh_list, "admin"),
    ("POST", r"^/api/webhooks$", api_wh_create, "admin"),
    ("POST", r"^/api/webhooks/test$", api_wh_test, "admin"),
    ("GET", r"^/api/webhooks/deliveries$", api_wh_deliveries, "admin"),
    ("GET", r"^/api/sync/changes$", api_sync, None),
    ("GET", r"^/api/health$", api_health, None),
    ("GET", r"^/api/openapi\.json$", api_openapi, None),
]

_COMPILED = [(mth, re.compile(p), fn, perm) for mth, p, fn, perm in ROUTES]


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "FeiBen-Cost/" + VERSION

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _path(self):
        raw = urlparse(self.path)
        p = raw.path
        if PATH_PREFIX and p.startswith(PATH_PREFIX + "/"):
            p = p[len(PATH_PREFIX):]
        elif PATH_PREFIX and p == PATH_PREFIX:
            p = "/"
        return p, parse_qs(raw.query)

    def _token(self):
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return (self.headers.get("X-Fb-Token") or self.headers.get("X-Auth-Token")
                or self._cookie_token() or ((self._cur_q or {}).get("token") or [""])[0])

    def _cookie_token(self):
        c = self.headers.get("Cookie") or ""
        m = re.search(r"token=([0-9a-f]+)", c)
        return m.group(1) if m else ""

    _cur_q = {}

    def _send(self, code, obj, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            bad("请求体不是合法 JSON")

    def _rate_ok(self):
        ip = self.client_address[0]
        now = time.time()
        w = _RATE.get(ip)
        if not w or now - w[0] > 60:
            _RATE[ip] = [now, 1]
            return True
        w[1] += 1
        return w[1] <= _RATE_LIMIT

    def _user(self, cn, need_perm):
        token = self._token()
        uname = token_user(cn, token)
        if not uname:
            key = check_key(cn, self.headers.get("X-Fb-Key") or "")
            if key:
                if need_perm and need_perm.endswith(".write") or need_perm == "admin":
                    bad("API Key 为只读 scope，禁止写操作", 403)
                return {"username": "apikey:" + key["name"], "name": key["name"],
                        "role": "viewer", "_token": ""}
            bad("未登录或令牌无效", 401)
        r = cn.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
        if not r:
            bad("用户不存在", 401)
        u = {"username": r["username"], "name": r["name"], "role": r["role"], "_token": token}
        if need_perm and not cost.can(u["role"], need_perm):
            bad("权限不足（需要 %s）" % need_perm, 403)
        return u

    def _dispatch(self, method):
        if not self._rate_ok():
            return self._send(429, {"code": 429, "message": "请求过于频繁，请稍后再试"})
        path, qs = self._path()
        self._cur_q = qs
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        try:
            cn = connect()
            match = None
            for mth, rx, fn, perm in _COMPILED:
                if mth != method:
                    continue
                mm = rx.match(path)
                if mm:
                    match = (fn, perm, mm)
                    break
            if match and match[0] is None and ".csv" in path:
                u = self._user(cn, "report.read")
                kind = re.search(r"reports/(\w+)\.csv", path).group(1)
                out = api_export(u, {"_q": {k: v[0] for k, v in qs.items()}}, kind)
                data = b"\xef\xbb\xbf" + out["text"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''%s" % quote(out["__csv__"]))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                db.close_thread_conns()
                return
            if not match:
                bad("接口不存在：%s %s" % (method, path), 404)
            fn, perm, mm = match
            body = {} if method == "GET" else self._body_json()
            if method == "GET":
                body = {"_q": {k: v[0] for k, v in qs.items()}}
            idem = self.headers.get("Idempotency-Key")
            if idem and method == "POST":
                row = cn.execute("SELECT status,response FROM idem_keys WHERE key=?",
                                 (idem,)).fetchone()
                if row and row["status"] == "done":
                    return self._send(200, json.loads(row["response"]),
                                      {"X-Idempotent-Replay": "true"})
                cn.execute("INSERT OR IGNORE INTO idem_keys(key,created) VALUES(?,?)",
                           (idem, cost.now_str()))
                cn.commit()
            if perm:
                u = self._user(cn, perm)
            elif path in ("/api/auth/login", "/api/health", "/api/openapi.json"):
                u = None
            else:
                u = self._user(cn, None)
            out = fn(u, mm, body)
            if idem and method == "POST":
                cn.execute("UPDATE idem_keys SET status='done',response=? WHERE key=?",
                           (json.dumps(out, ensure_ascii=False), idem))
                cn.commit()
            self._send(200, out)
        except ApiErr as e:
            try:
                self._send(e.code, {"code": e.code, "message": e.msg})
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            try:
                self._send(500, {"code": 500, "message": "服务器内部错误：%s" % e})
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close_thread_conns()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        if not (path.endswith(".html") or path.endswith(".js") or path.endswith(".css")
                or path.endswith(".svg") or path.endswith(".png")):
            return self._notfound()
        fname = os.path.basename(path)
        fp = os.path.join(FRONT, fname)
        if not os.path.isfile(fp):
            return self._notfound()
        ctype = {"html": "text/html; charset=utf-8",
                 "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml",
                 "png": "image/png"}.get(fname.rsplit(".", 1)[-1], "application/octet-stream")
        data = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _notfound(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def openapi_json():
    paths = {}
    for mth, rx, fn, perm in _COMPILED:
        p = re.sub(r"\([^)]*\)", "{param}", rx.pattern).strip("^$")
        if ".csv" in p:
            p = "/api/reports/{kind}.csv"
        item = paths.setdefault(p, {})
        item[mth.lower()] = {"summary": fn.__name__ if fn else "export",
                             "tags": [p.split("/")[2] if len(p.split("/")) > 2 else "misc"]}
    return {"openapi": "3.0.0", "info": {"title": BRAND + " REST API", "version": VERSION},
            "paths": paths}


def _worker_loop():
    backoff = [30, 60, 120]
    while True:
        try:
            if _WEBHOOK_Q:
                wid, url, secret, event, payload = _WEBHOOK_Q.pop(0)
                ts = str(int(time.time()))
                sig = hmac.new(secret.encode(), (ts + "." + payload).encode(),
                               hashlib.sha256).hexdigest()
                req = urllib.request.Request(url, data=payload.encode("utf-8"), method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "X-Fb-Event": event,
                                                      "X-Fb-Timestamp": ts,
                                                      "X-Fb-Signature": sig})
                cn = connect()
                try:
                    r = urllib.request.urlopen(req, timeout=5)
                    cn.execute("UPDATE webhook_deliveries SET status='success',"
                               "attempts=attempts+1,last_at=?,response=? WHERE webhook_id=?"
                               " AND event=? AND status='pending'",
                               (cost.now_str(), str(r.status), wid, event))
                except Exception as e:  # noqa: BLE001
                    att = val(cn, "SELECT attempts FROM webhook_deliveries WHERE webhook_id=?"
                                  " AND event=? AND status='pending'", (wid, event))
                    if att < 3:
                        cn.execute("UPDATE webhook_deliveries SET attempts=attempts+1,last_at=?,"
                                   "response=? WHERE webhook_id=? AND event=?"
                                   " AND status='pending'",
                                   (cost.now_str(), str(e)[:200], wid, event))
                        _WEBHOOK_Q.append((wid, url, secret, event, payload))
                    else:
                        cn.execute("UPDATE webhook_deliveries SET status='failed',"
                                   "attempts=attempts+1,last_at=?,response=? WHERE webhook_id=?"
                                   " AND event=? AND status='pending'",
                                   (cost.now_str(), str(e)[:200], wid, event))
                cn.commit()
                db.close_thread_conns()
            else:
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            time.sleep(1)


def _warmup(cn, period):
    """首次播种后自动跑一遍分摊与差异，让演示数据开箱即用（失败不阻塞启动）。"""
    u = {"username": "system", "name": "系统初始化", "role": "admin", "_token": ""}
    if not val(cn, "SELECT COUNT(*) FROM allocation_runs WHERE period=?", (period,)):
        try:
            api_alloc_run(u, None, {"period": period})
        except Exception as e:  # noqa: BLE001
            print("warmup alloc skipped:", e)
    if not val(cn, "SELECT COUNT(*) FROM variances WHERE period=?", (period,)):
        try:
            api_variance_calc(u, None, {"period": period})
        except Exception as e:  # noqa: BLE001
            print("warmup variance skipped:", e)


def main():
    db.init()
    cn = connect()
    fresh = not val(cn, "SELECT COUNT(*) FROM users")
    if fresh:
        seed_mod.seed()
        cn = connect()
        _warmup(cn, cost.cur_period())
    db.close_thread_conns()
    threading.Thread(target=_worker_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("%s %s listening on %s:%d (prefix=%s)" % (BRAND, VERSION, HOST, PORT, PATH_PREFIX))
    srv.serve_forever()


if __name__ == "__main__":
    main()
