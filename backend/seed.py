# -*- coding: utf-8 -*-
"""飞奔成本管理系统 · 演示数据（空库自动播种，口径与 cost.py 一致）"""
import hashlib
import os
import random

import cost
import db

SALT_LEN = 8


def hash_pwd(pwd, salt):
    return hashlib.sha256((pwd + salt).encode("utf-8")).hexdigest()


def _user(cn, username, pwd, name, role, dept=""):
    salt = os.urandom(SALT_LEN).hex()
    cn.execute("INSERT INTO users(username,password_hash,salt,name,role,dept,created)"
               " VALUES(?,?,?,?,?,?,?)",
               (username, hash_pwd(pwd, salt), salt, name, role, dept, cost.now_str()))


CENTERS = [
    # code, name, ctype, parent, leader, labor_rate, oh_rate, order, driver, driver_qty
    ("CC201", "动力辅助车间", "辅助", "", "王工", 0, 0, 1, "机器工时", 4200),
    ("CC202", "设备维修组", "辅助", "", "李强", 32, 6, 2, "人工工时", 1600),
    ("CC203", "品质检验组", "辅助", "", "陈敏", 30, 4, 3, "人工工时", 1200),
    ("CC101", "注塑车间", "生产", "", "赵勇", 38, 26, 5, "机器工时", 9600),
    ("CC102", "冲压车间", "生产", "", "孙磊", 36, 24, 5, "机器工时", 7200),
    ("CC103", "装配车间", "生产", "", "周洁", 34, 20, 5, "人工工时", 5200),
    ("CC301", "生产管理部", "管理", "", "吴涛", 42, 0, 6, "人数", 24),
    ("CC302", "财务部", "管理", "", "郑霞", 45, 0, 7, "人数", 9),
    ("CC401", "销售中心", "销售", "", "冯磊", 40, 0, 8, "人数", 14),
    ("CC501", "研发中心", "研发", "", "许工", 46, 8, 8, "人工工时", 2200),
]

SUBJECTS = [
    ("S1001", "直接材料", "材料", "直接"),
    ("S1002", "辅助材料", "材料", "间接"),
    ("S1003", "外购件", "材料", "直接"),
    ("S2001", "直接人工", "人工", "直接"),
    ("S2002", "加班工资", "人工", "间接"),
    ("S2003", "社保公积金", "人工", "间接"),
    ("S3001", "电费", "制造费用", "间接"),
    ("S3002", "水费", "制造费用", "间接"),
    ("S3003", "设备折旧", "制造费用", "间接"),
    ("S3004", "维修费", "制造费用", "间接"),
    ("S3005", "低值易耗品", "制造费用", "间接"),
    ("S4001", "办公费", "期间费用", "间接"),
    ("S4002", "差旅费", "期间费用", "间接"),
    ("S4003", "业务招待费", "期间费用", "间接"),
    ("S4004", "研发材料费", "期间费用", "间接"),
]

MATERIALS = [
    ("M1001", "ABS 塑料粒子", "kg", 12.6),
    ("M1002", "PP 塑料粒子", "kg", 10.8),
    ("M1003", "PC 塑料粒子", "kg", 21.5),
    ("M2001", "冷轧钢板 1.2mm", "kg", 5.4),
    ("M2002", "不锈钢板 0.8mm", "kg", 18.2),
    ("M2003", "铝型材 6063", "kg", 22.4),
    ("M3001", "直流电机 24V", "个", 68.0),
    ("M3002", "轴承 6203", "个", 6.8),
    ("M3003", "扇叶组件", "套", 15.5),
    ("M3004", "螺丝 M4×12", "个", 0.12),
    ("M3005", "包装纸箱", "个", 3.6),
]

# code, name, spec, unit, std_hours, center, list_price, BOM[(material, qty, loss)]
PRODUCTS = [
    ("P1001", "电机外壳 A 型", "180×120×90", "件", 0.35, "CC101", 28.0,
     [("M1001", 0.42, 0.03), ("M3004", 4, 0.01), ("M3005", 0.02, 0)]),
    ("P1002", "齿轮箱盖", "150×150×40", "件", 0.28, "CC101", 22.0,
     [("M1002", 0.35, 0.04), ("M3004", 3, 0.01)]),
    ("P1003", "控制盒上盖", "120×80×30", "件", 0.31, "CC101", 25.0,
     [("M1003", 0.30, 0.05), ("M3005", 0.02, 0)]),
    ("P2001", "电机支架", "1.2mm 冷轧", "件", 0.22, "CC102", 15.0,
     [("M2001", 0.55, 0.06), ("M3004", 2, 0.01)]),
    ("P2002", "电机端盖", "0.8mm 不锈钢", "件", 0.18, "CC102", 12.0,
     [("M2002", 0.28, 0.05), ("M3002", 1, 0.005)]),
    ("P2003", "散热支架", "6063 铝型材", "件", 0.20, "CC102", 16.5,
     [("M2003", 0.32, 0.04)]),
    ("P3001", "电动工具整机", "24V 无刷", "台", 1.20, "CC103", 320.0,
     [("M3001", 1, 0.01), ("M3002", 2, 0.01), ("M3004", 8, 0.01),
      ("M2001", 0.9, 0.05), ("M3005", 1, 0)]),
    ("P3002", "家用风扇整机", "16 寸", "台", 0.90, "CC103", 210.0,
     [("M3001", 1, 0.01), ("M3003", 1, 0.01), ("M3004", 6, 0.01), ("M3005", 1, 0)]),
]

EXPENSES = [
    # period, center, subject, amount, source, summary, status
    ("2026-09", "CC101", "S3001", 86400.0, "采购", "注塑车间 9 月电费", "已批准"),
    ("2026-09", "CC101", "S3003", 42000.0, "折旧", "注塑机折旧 6 台", "已批准"),
    ("2026-09", "CC102", "S3001", 51200.0, "采购", "冲压车间 9 月电费", "已批准"),
    ("2026-09", "CC102", "S3003", 28500.0, "折旧", "冲床折旧 4 台", "已批准"),
    ("2026-09", "CC103", "S2002", 32800.0, "工资", "装配加班工资", "已批准"),
    ("2026-09", "CC201", "S3001", 76000.0, "采购", "厂区总电费 9 月", "已批准"),
    ("2026-09", "CC202", "S3004", 18900.0, "报销", "设备维修备件", "已批准"),
    ("2026-09", "CC203", "S3005", 9600.0, "采购", "检具耗材", "已批准"),
    ("2026-09", "CC301", "S4001", 15600.0, "报销", "生产管理部办公费", "已批准"),
    ("2026-09", "CC401", "S4003", 23800.0, "报销", "客户招待", "已批准"),
    ("2026-10", "CC101", "S3001", 90100.0, "采购", "注塑车间 10 月电费", "已批准"),
    ("2026-10", "CC101", "S3003", 42000.0, "折旧", "注塑机折旧 6 台", "已批准"),
    ("2026-10", "CC102", "S3001", 53800.0, "采购", "冲压车间 10 月电费", "已批准"),
    ("2026-10", "CC102", "S3003", 28500.0, "折旧", "冲床折旧 4 台", "已批准"),
    ("2026-10", "CC103", "S2002", 36400.0, "工资", "装配加班工资", "已批准"),
    ("2026-10", "CC103", "S3005", 12400.0, "采购", "装配线低值易耗", "已批准"),
    ("2026-10", "CC201", "S3001", 81200.0, "采购", "厂区总电费 10 月", "已批准"),
    ("2026-10", "CC201", "S3002", 18400.0, "采购", "厂区水费 10 月", "已批准"),
    ("2026-10", "CC202", "S3004", 21300.0, "报销", "空压机大修", "已批准"),
    ("2026-10", "CC202", "S3005", 6800.0, "采购", "维修班工具", "已批准"),
    ("2026-10", "CC203", "S3005", 10200.0, "采购", "检具耗材", "已批准"),
    ("2026-10", "CC203", "S2002", 8600.0, "工资", "检验加班", "已批准"),
    ("2026-10", "CC301", "S4001", 16800.0, "报销", "生产管理部办公费", "已批准"),
    ("2026-10", "CC301", "S4002", 12600.0, "报销", "车间主任出差", "待审批"),
    ("2026-10", "CC302", "S4001", 9400.0, "报销", "财务部办公费", "已批准"),
    ("2026-10", "CC401", "S4003", 26800.0, "报销", "客户招待", "已批准"),
    ("2026-10", "CC401", "S4002", 18500.0, "报销", "销售出差", "待审批"),
    ("2026-10", "CC501", "S4004", 42600.0, "采购", "新品试制材料", "已批准"),
    ("2026-10", "CC501", "S4001", 7200.0, "报销", "研发部办公费", "草稿"),
    ("2026-10", "CC101", "S3004", 4200.0, "报销", "注塑机螺杆维修", "草稿"),
]

BUDGETS = [
    ("CC101", "S3001", 95000), ("CC101", "S3003", 44000), ("CC101", "S3004", 6000),
    ("CC102", "S3001", 56000), ("CC102", "S3003", 30000),
    ("CC103", "S2002", 40000), ("CC103", "S3005", 15000),
    ("CC201", "S3001", 88000), ("CC201", "S3002", 20000),
    ("CC202", "S3004", 25000), ("CC202", "S3005", 8000),
    ("CC203", "S3005", 12000), ("CC203", "S2002", 10000),
    ("CC301", "S4001", 18000), ("CC301", "S4002", 15000),
    ("CC302", "S4001", 10000),
    ("CC401", "S4003", 28000), ("CC401", "S4002", 20000),
    ("CC501", "S4004", 45000), ("CC501", "S4001", 8000),
]

ALLOC_RULES = [
    ("CC201", "CC101", "机器工时", 96),
    ("CC201", "CC102", "机器工时", 72),
    ("CC201", "CC103", "人工工时", 52),
    ("CC202", "CC101", "人工工时", 40),
    ("CC202", "CC102", "人工工时", 35),
    ("CC202", "CC103", "人工工时", 45),
    ("CC203", "CC101", "人工工时", 30),
    ("CC203", "CC102", "人工工时", 25),
    ("CC203", "CC103", "人工工时", 45),
]

# 工单：(no, product, period, center, qty_plan, qty_done, wip_rate, status)
ORDERS = [
    ("WO202610-0001", "P1001", "2026-10", "CC101", 5000, 5000, 1.0, "已完工"),
    ("WO202610-0002", "P1001", "2026-10", "CC101", 4000, 4000, 1.0, "已完工"),
    ("WO202610-0003", "P1002", "2026-10", "CC101", 3000, 2600, 0.6, "在生产"),
    ("WO202610-0004", "P1003", "2026-10", "CC101", 2500, 2500, 1.0, "已完工"),
    ("WO202610-0005", "P2001", "2026-10", "CC102", 6000, 6000, 1.0, "已完工"),
    ("WO202610-0006", "P2002", "2026-10", "CC102", 4000, 3500, 0.5, "在生产"),
    ("WO202610-0007", "P2003", "2026-10", "CC102", 3000, 3000, 1.0, "已完工"),
    ("WO202610-0008", "P3001", "2026-10", "CC103", 800, 800, 1.0, "已完工"),
    ("WO202610-0009", "P3002", "2026-10", "CC103", 1200, 1100, 0.7, "在生产"),
    ("WO202610-0010", "P3001", "2026-10", "CC103", 600, 600, 1.0, "已完工"),
    ("WO202609-0001", "P1001", "2026-09", "CC101", 4800, 4800, 1.0, "已完工"),
    ("WO202609-0002", "P2001", "2026-09", "CC102", 5500, 5500, 1.0, "已完工"),
    ("WO202609-0003", "P3001", "2026-09", "CC103", 700, 700, 1.0, "已完工"),
    ("WO202609-0004", "P3002", "2026-09", "CC103", 1000, 1000, 1.0, "已完工"),
]

MAT_PRICE = {m[0]: m[3] for m in MATERIALS}
MAT_NAME = {m[0]: m[1] for m in MATERIALS}
TECH = {p[0]: p[4] for p in PRODUCTS}


def seed():
    cn = db.connect()
    cn.executescript(db.SCHEMA)
    if cn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return

    now = cost.now_str()
    # 用户（7 角色，独立口令）
    _user(cn, "admin", "cost@2026", "管理员", "admin", "信息部")
    _user(cn, "manager", "cm@2026fB", "罗成本", "cost_manager", "财务部")
    _user(cn, "acct", "ac@2026fB", "钱会计", "accountant", "财务部")
    _user(cn, "owner", "co@2026fB", "赵勇", "center_owner", "注塑车间")
    _user(cn, "prod", "pd@2026fB", "孙统计", "production", "生产管理部")
    _user(cn, "viewer", "vw@2026fB", "访客", "viewer", "")
    _user(cn, "auditor", "au@2026fB", "审计员", "auditor", "审计部")

    # 业务规则
    for code, name, cat, val, unit, remark in cost.DEFAULT_RULES:
        cn.execute("INSERT OR REPLACE INTO rules(code,name,category,value,unit,enabled,remark)"
                   " VALUES(?,?,?,?,?,1,?)", (code, name, cat, val, unit, remark))

    # 成本中心
    for code, name, ctype, parent, leader, lr, ohr, order, drv, qty in CENTERS:
        cn.execute("INSERT INTO cost_centers(code,name,ctype,parent_code,leader,labor_rate,"
                   "oh_rate,alloc_order,driver,driver_qty,status,created)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?, '启用',?)",
                   (code, name, ctype, parent, leader, lr, ohr, order, drv, qty, now))

    # 科目
    for code, name, cat, gather in SUBJECTS:
        cn.execute("INSERT INTO subjects(code,name,category,gather,enabled,created)"
                   " VALUES(?,?,?,?,1,?)", (code, name, cat, gather, now))

    # 产品 + BOM
    for code, name, spec, unit, hours, center, price, bom in PRODUCTS:
        cn.execute("INSERT INTO products(code,name,spec,unit,std_hours,center_code,list_price,"
                   "status,created) VALUES(?,?,?,?,?,?,?,'在产',?)",
                   (code, name, spec, unit, hours, center, price, now))
        for mat, qty, loss in bom:
            cn.execute("INSERT INTO bom_lines(product_code,material_code,material_name,qty_per,"
                       "loss_rate,std_price,unit) VALUES(?,?,?,?,?,?,?)",
                       (code, mat, MAT_NAME[mat], qty, loss, MAT_PRICE[mat],
                        [m[2] for m in MATERIALS if m[0] == mat][0]))

    # 标准成本（两个期间各一版）
    center_rate = {c[0]: (c[5], c[6]) for c in CENTERS}
    for period in ("2026-09", "2026-10"):
        for code, name, spec, unit, hours, center, price, bom in PRODUCTS:
            lines = cn.execute("SELECT * FROM bom_lines WHERE product_code=?", (code,)).fetchall()
            lr, ohr = center_rate[center]
            card = cost.std_card([dict(r) for r in lines], hours, lr, ohr)
            cn.execute("INSERT INTO std_costs(period,product_code,version,mat_cost,labor_cost,"
                       "oh_cost,unit_cost,status,calc_at,published_at)"
                       " VALUES(?,?,1,?,?,?,?,'已发布',?,?)",
                       (period, code, card["matCost"], card["laborCost"], card["ohCost"],
                        card["unitCost"], now, now))

    # 期间
    for period in ("2026-09", "2026-10"):
        cn.execute("INSERT INTO periods(period,status,created) VALUES(?,?,?)",
                   (period, "打开", now))

    # 费用单
    seq = {}
    for period, center, subject, amount, source, summary, status in EXPENSES:
        seq[period] = seq.get(period, 0) + 1
        no = cost.doc_no("EXP", period, seq[period])
        approver = "manager" if status in ("已批准", "已驳回") else ""
        cn.execute("INSERT INTO expenses(no,period,center_code,subject_code,amount,source,"
                   "doc_ref,summary,status,applicant,approver,decided_at,budget_used,created)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, period, center, subject, amount, source, "", summary, status,
                    "acct", approver, now if approver else "", 1 if status == "已批准" else 0, now))
        if status == "已批准":
            cn.execute("UPDATE budgets SET used=used+? WHERE period=? AND center_code=?"
                       " AND subject_code=?", (amount, period, center, subject))

    # 预算
    for period in ("2026-09", "2026-10"):
        for center, subject, amount in BUDGETS:
            used = 0.0
            r = cn.execute("SELECT SUM(amount) s FROM expenses WHERE period=? AND center_code=?"
                           " AND subject_code=? AND status='已批准'",
                           (period, center, subject)).fetchone()
            used = cost.safe_num(r["s"])
            cn.execute("INSERT OR REPLACE INTO budgets(period,center_code,subject_code,amount,"
                       "used,created) VALUES(?,?,?,?,?,?)",
                       (period, center, subject, amount, cost.q2(used), now))

    # 分摊规则
    for f, t, drv, w in ALLOC_RULES:
        cn.execute("INSERT OR REPLACE INTO allocation_rules(from_center,to_center,driver,weight,"
                   "enabled,created) VALUES(?,?,?,?,1,?)", (f, t, drv, w, now))

    # 工单 + 领料 + 报工
    rnd = random.Random(20261022)
    for no, prod, period, center, plan, done, wip, status in ORDERS:
        cn.execute("INSERT INTO work_orders(no,product_code,period,center_code,qty_plan,qty_done,"
                   "wip_rate,start_date,end_date,status,created)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (no, prod, period, center, plan, done, wip,
                    period + "-02", period + "-28" if status == "已完工" else "",
                    status, now))
        bom = cn.execute("SELECT * FROM bom_lines WHERE product_code=?", (prod,)).fetchall()
        material_sum = 0.0
        mat_rows, lab_rows = [], []
        for b in bom:
            need = cost.safe_num(b["qty_per"]) * (1 + cost.safe_num(b["loss_rate"]))
            qty = round(need * plan * (1 + rnd.uniform(-0.01, 0.035)), 3)
            price = round(cost.safe_num(b["std_price"]) * rnd.uniform(0.97, 1.06), 4)
            amount = cost.q2(qty * price)
            material_sum += amount
            mat_rows.append({"qty": qty, "price": price, "amount": amount})
            cn.execute("INSERT INTO wo_materials(wo_no,material_code,material_name,qty,price,"
                       "amount,at) VALUES(?,?,?,?,?,?,?)",
                       (no, b["material_code"], b["material_name"], qty, price, amount, now))
        hours_std = TECH[prod] * plan
        hours = round(hours_std * rnd.uniform(0.95, 1.12), 2)
        oh_rate = [c[6] for c in CENTERS if c[0] == center][0]
        lr = [c[5] for c in CENTERS if c[0] == center][0]
        rate = round(lr * rnd.uniform(0.98, 1.05), 2)
        ind_hours = round(hours * 0.08, 2)
        for wt, h in (("直接工时", hours), ("间接工时", ind_hours)):
            lab_rows.append({"hours": h, "rate": rate, "amount": cost.q2(h * rate)})
            cn.execute("INSERT INTO wo_labor(wo_no,work_type,hours,rate,amount,worker,at)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (no, wt, h, rate, cost.q2(h * rate), "班组" + ("A" if wt == "直接工时" else "B"),
                        now))
        ac = cost.actual_cost(mat_rows, lab_rows, oh_rate)
        split = cost.split_cost(ac["totalActual"], done, plan, wip) or {
            "equivQty": 0, "unitCost": 0, "finishedCost": 0, "wipCost": 0}
        cn.execute("UPDATE work_orders SET mat_actual=?,labor_actual=?,oh_actual=?,total_actual=?,"
                   "unit_cost=?,equiv_qty=?,finished_cost=?,wip_cost=?,calc_at=? WHERE no=?",
                   (ac["matActual"], ac["laborActual"], ac["ohActual"], ac["totalActual"],
                    split["unitCost"], split["equivQty"], split["finishedCost"],
                    split["wipCost"], now, no))

    cn.execute("INSERT OR REPLACE INTO sync_state(entity,last_at) VALUES('event',?)", (now,))
    cn.commit()
    db.close_thread_conns()
    print("飞奔成本管理系统演示数据播种完成")
