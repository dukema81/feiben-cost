# -*- coding: utf-8 -*-
"""飞奔成本管理系统 · 数据层（24 表，sqlite3 WAL，零依赖）"""
import os
import sqlite3
import threading

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FEIBEN_DB") or os.path.join(_DIR, "data", "feiben.db")

_local = threading.local()


def connect():
    cn = getattr(_local, "cn", None)
    if cn is not None:
        return cn
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    cn = sqlite3.connect(DB_PATH, timeout=20)
    cn.row_factory = sqlite3.Row
    cn.execute("PRAGMA journal_mode=WAL")
    cn.execute("PRAGMA busy_timeout=20000")
    cn.execute("PRAGMA foreign_keys=ON")
    _local.cn = cn
    return cn


def close_thread_conns():
    cn = getattr(_local, "cn", None)
    if cn is not None:
        try:
            cn.close()
        except Exception:  # noqa: BLE001
            pass
        _local.cn = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, salt TEXT NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL, dept TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cost_centers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  ctype TEXT NOT NULL DEFAULT '生产', parent_code TEXT DEFAULT '',
  leader TEXT DEFAULT '', labor_rate REAL DEFAULT 0, oh_rate REAL DEFAULT 0,
  alloc_order INTEGER DEFAULT 9, driver TEXT DEFAULT '人工工时', driver_qty REAL DEFAULT 0,
  status TEXT NOT NULL DEFAULT '启用', remark TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subjects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '材料', gather TEXT NOT NULL DEFAULT '直接',
  enabled INTEGER DEFAULT 1, remark TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  spec TEXT DEFAULT '', unit TEXT DEFAULT '件', std_hours REAL DEFAULT 0,
  center_code TEXT DEFAULT '', list_price REAL DEFAULT 0,
  status TEXT NOT NULL DEFAULT '在产', remark TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bom_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT NOT NULL,
  material_code TEXT NOT NULL, material_name TEXT DEFAULT '', qty_per REAL NOT NULL DEFAULT 1,
  loss_rate REAL DEFAULT 0, std_price REAL DEFAULT 0, unit TEXT DEFAULT 'kg');
CREATE TABLE IF NOT EXISTS std_costs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, product_code TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, mat_cost REAL DEFAULT 0, labor_cost REAL DEFAULT 0,
  oh_cost REAL DEFAULT 0, unit_cost REAL DEFAULT 0, status TEXT NOT NULL DEFAULT '草稿',
  calc_at TEXT NOT NULL, published_at TEXT DEFAULT '', UNIQUE(period, product_code, version));
CREATE TABLE IF NOT EXISTS work_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT UNIQUE NOT NULL, product_code TEXT NOT NULL,
  period TEXT NOT NULL, center_code TEXT NOT NULL, qty_plan REAL NOT NULL DEFAULT 0,
  qty_done REAL DEFAULT 0, wip_rate REAL DEFAULT 1, start_date TEXT DEFAULT '',
  end_date TEXT DEFAULT '', status TEXT NOT NULL DEFAULT '草稿',
  mat_actual REAL DEFAULT 0, labor_actual REAL DEFAULT 0, oh_actual REAL DEFAULT 0,
  total_actual REAL DEFAULT 0, unit_cost REAL DEFAULT 0,
  equiv_qty REAL DEFAULT 0, finished_cost REAL DEFAULT 0, wip_cost REAL DEFAULT 0,
  calc_at TEXT DEFAULT '', remark TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wo_materials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wo_no TEXT NOT NULL, material_code TEXT NOT NULL,
  material_name TEXT DEFAULT '', qty REAL NOT NULL DEFAULT 0, price REAL DEFAULT 0,
  amount REAL DEFAULT 0, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wo_labor(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wo_no TEXT NOT NULL, work_type TEXT DEFAULT '加工',
  hours REAL NOT NULL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0,
  worker TEXT DEFAULT '', at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT UNIQUE NOT NULL, period TEXT NOT NULL,
  center_code TEXT NOT NULL, subject_code TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT '手工', doc_ref TEXT DEFAULT '', summary TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT '草稿', applicant TEXT DEFAULT '', approver TEXT DEFAULT '',
  decided_at TEXT DEFAULT '', budget_used INTEGER DEFAULT 0, remark TEXT DEFAULT '',
  created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS allocation_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_center TEXT NOT NULL, to_center TEXT NOT NULL,
  driver TEXT DEFAULT '人工工时', weight REAL DEFAULT 1, enabled INTEGER DEFAULT 1,
  created TEXT NOT NULL, UNIQUE(from_center, to_center));
CREATE TABLE IF NOT EXISTS allocation_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT UNIQUE NOT NULL, period TEXT NOT NULL,
  method TEXT NOT NULL DEFAULT '阶梯法', status TEXT NOT NULL DEFAULT '已完成',
  base_total REAL DEFAULT 0, allocated_total REAL DEFAULT 0, check_diff REAL DEFAULT 0,
  operator TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS allocation_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_no TEXT NOT NULL, step INTEGER DEFAULT 0,
  from_center TEXT NOT NULL, to_center TEXT NOT NULL, driver TEXT DEFAULT '',
  weight REAL DEFAULT 0, base_amount REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, center_code TEXT NOT NULL,
  subject_code TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, used REAL DEFAULT 0,
  remark TEXT DEFAULT '', created TEXT NOT NULL, UNIQUE(period, center_code, subject_code));
CREATE TABLE IF NOT EXISTS variances(
  id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, product_code TEXT NOT NULL,
  from_wo TEXT DEFAULT '', qty REAL DEFAULT 0, std_unit_cost REAL DEFAULT 0,
  act_unit_cost REAL DEFAULT 0, std_total REAL DEFAULT 0, act_total REAL DEFAULT 0,
  total_var REAL DEFAULT 0, price_var REAL DEFAULT 0, qty_var REAL DEFAULT 0,
  rate_var REAL DEFAULT 0, eff_var REAL DEFAULT 0, expense_var REAL DEFAULT 0,
  check_diff REAL DEFAULT 0, level TEXT DEFAULT '', calc_at TEXT NOT NULL,
  UNIQUE(period, product_code, from_wo));
CREATE TABLE IF NOT EXISTS periods(
  id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT '打开', closed_at TEXT DEFAULT '', closed_by TEXT DEFAULT '',
  remark TEXT DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules(
  code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  value TEXT NOT NULL, unit TEXT DEFAULT '', enabled INTEGER DEFAULT 1, remark TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, user TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key_hash TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL,
  name TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'read', created TEXT NOT NULL,
  last_used TEXT DEFAULT '', revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS webhooks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
  secret TEXT NOT NULL, events TEXT NOT NULL, enabled INTEGER DEFAULT 1, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_deliveries(
  id INTEGER PRIMARY KEY AUTOINCREMENT, webhook_id INTEGER NOT NULL, event TEXT NOT NULL,
  payload TEXT NOT NULL, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  last_at TEXT DEFAULT '', response TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS idem_keys(
  key TEXT PRIMARY KEY, status TEXT DEFAULT 'processing', response TEXT DEFAULT '',
  created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_state(
  entity TEXT PRIMARY KEY, last_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS tokens(
  token TEXT PRIMARY KEY, username TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_bom_product ON bom_lines(product_code);
CREATE INDEX IF NOT EXISTS idx_wo_period ON work_orders(period, center_code);
CREATE INDEX IF NOT EXISTS idx_womat ON wo_materials(wo_no);
CREATE INDEX IF NOT EXISTS idx_wolab ON wo_labor(wo_no);
CREATE INDEX IF NOT EXISTS idx_exp_period ON expenses(period, center_code, subject_code);
CREATE INDEX IF NOT EXISTS idx_alloc_run ON allocation_lines(run_no);
CREATE INDEX IF NOT EXISTS idx_var_period ON variances(period, product_code);
"""


def init():
    cn = connect()
    cn.executescript(SCHEMA)
    cn.commit()
    return cn


if __name__ == "__main__":
    init()
    print("feiben.db 初始化完成：", DB_PATH)
