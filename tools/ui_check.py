# -*- coding: utf-8 -*-
"""UI 巡检：逐页加载、抓控制台错误、截图（playwright chromium）"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp(prefix="feiben_ui_")
os.environ["FEIBEN_DB"] = os.path.join(TMP, "ui.db")
os.environ["PORT"] = "8921"
os.environ["FEIBEN_PREFIX"] = ""

import db  # noqa: E402
import seed  # noqa: E402
import server  # noqa: E402

BASE = "http://127.0.0.1:8921"
SHOTS = os.path.join(ROOT, "reports", "screenshots")
PAGES = [("dashboard", "成本驾驶舱"), ("center", "成本中心"), ("subject", "成本科目"),
         ("product", "产品与BOM"), ("std", "标准成本"), ("wo", "生产工单"),
         ("exp", "费用归集"), ("alloc", "成本分摊"), ("budget", "预算管控"),
         ("variance", "差异分析"), ("report", "报表中心"), ("period", "期间结账"),
         ("sys", "系统设置")]


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    db.init()
    seed.seed()
    db.close_thread_conns()
    server._warmup(db.connect(), "2026-10")
    db.close_thread_conns()
    srv = server.ThreadingHTTPServer(("127.0.0.1", 8921), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.6)

    errors, results = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1512, "height": 950})
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append("%s: %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        pg.goto(BASE + "/login.html", wait_until="networkidle")
        pg.fill("#u", "admin")
        pg.fill("#p", "cost@2026")
        pg.click("#btn")
        pg.wait_for_url("**/index.html", timeout=15000)
        pg.wait_for_timeout(1200)

        for pid, title in PAGES:
            before = len(errors)
            pg.evaluate("(h)=>{location.hash=h}", "#" + pid)
            pg.wait_for_timeout(1100)
            rows = pg.locator("table tbody tr").count()
            kpis = pg.locator(".kpi").count()
            shot = os.path.join(SHOTS, "ui_%s.png" % pid)
            pg.screenshot(path=shot, full_page=False)
            new_err = errors[before:]
            results.append((pid, title, rows, kpis, new_err))
            print("  %-10s %-12s 表格行=%-3d 卡片=%-2d 错误=%d %s" % (
                pid, title, rows, kpis, len(new_err), new_err[:2] if new_err else ""))

        # 弹层巡检：工单明细
        pg.evaluate("(h)=>{location.hash=h}", "#wo")
        pg.wait_for_timeout(900)
        btn = pg.locator("[data-detail]").first
        if btn.count():
            btn.click()
            pg.wait_for_timeout(900)
            pg.screenshot(path=os.path.join(SHOTS, "ui_wo_modal.png"))
            print("  工单明细弹层：", pg.locator(".dlg .dh h3").inner_text())
            pg.click(".dlg .dh .x")
        # 移动端
        pg.set_viewport_size({"width": 430, "height": 900})
        pg.evaluate("(h)=>{location.hash=h}", "#dashboard")
        pg.wait_for_timeout(900)
        pg.screenshot(path=os.path.join(SHOTS, "ui_mobile_dashboard.png"))
        b.close()

    total_err = sum(len(r[4]) for r in results)
    print("-" * 70)
    print("页面 %d 个，控制台错误 %d 条" % (len(results), total_err))
    srv.shutdown()
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
