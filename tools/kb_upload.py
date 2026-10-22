# -*- coding: utf-8 -*-
"""飞奔成本管理系统 · 文档批量上传知识库（分类 33 企业管理系统）"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feiben-cost"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feiben-design.md", "飞奔成本管理系统建设方案",
     "「飞奔成本管理系统」完整建设方案 V1.0：建设背景与目标、12 模块业务范围、核心成本口径"
     "（标准成本卡、实际成本归集、约当产量法、材料/人工/制费五维差异、阶梯顺序分摊禁止回分、"
     "预算三段闸口 90%/100%/110%、结账三闸口）、24 表数据模型、69 路由 API 契约、"
     "7 角色 × 20 权限矩阵、零依赖技术架构（标准库 http.server + sqlite3 WAL）、"
     "6 阶段实施里程碑、验收标准（差异五维闭合 checkDiff=0、分摊守恒 baseTotal=allocatedTotal、"
     "结账闸口拦截）与风险应对。",
     "飞奔成本,成本管理,标准成本,差异分析,阶梯分摊,约当产量,建设方案"),
    ("docs/api.md", "飞奔成本管理系统 REST 接口契约",
     "69 路由完整契约：统一响应包、多通道鉴权（Bearer / X-Fb-Token / Cookie / ?token= / X-Fb-Key）、"
     "Idempotency-Key 幂等、限流 300 次每分钟、认证与看板、主数据（成本中心/科目/产品与BOM）、"
     "标准成本重算、工单（建单/领料/报工/完工核算/约当分摊）、费用归集与审批、"
     "阶梯分摊（规则/执行/批次明细）、预算与执行率、差异计算、报表 4 张与 CSV 导出（UTF-8 BOM）、"
     "期间结账/反结账、系统管理（用户/规则/API Key/Webhook HMAC-SHA256 签名 13 种事件/增量同步/审计日志）、"
     "权限矩阵与对接实施建议。",
     "飞奔成本,API,接口契约,REST,Webhook,增量同步,对接"),
    ("docs/test-report.md", "飞奔成本管理系统测试报告",
     "四层自动化测试全部通过：单元测试 51 条（标准卡/实际归集/约当产量/五维差异/阶梯分摊/预算闸口/"
     "工单与费用闸口/权限矩阵）、接口测试 36 条（鉴权/权限/主数据/工单/费用预算/分摊/差异/锁期/系统）、"
     "接口冒烟 52 检查点（30 条全量 GET + 写入链路 + 4 条闸口负例 + 注销失效）、"
     "UI 巡检 13 页 0 控制台错误 + 15 张截图。核心口径实测：差异五维闭合 checkDiff=0.00、"
     "分摊守恒 146500.00=146500.00、结账三闸口逐一拦截验证。含线上验收与已知限制。",
     "飞奔成本,测试报告,质量门禁,自动化测试,Playwright"),
    ("docs/user-guide.md", "飞奔成本管理系统操作手册",
     "12 章操作手册：启动与环境变量（FEIBEN_PORT/FEIBEN_PREFIX）、7 角色账号登录、界面骨架与期间切换、"
     "13 个页面逐页操作说明、标准成本卡公式与算例、工单全流程（领料→报工→完工→约当产量核算）、"
     "费用提交与审批流、阶梯分摊执行与规则维护、预算预警与阻断、五维差异解读（每个差异该谁管）、"
     "报表与 CSV 导出、期间结账/反结账、系统管理与集成、8 条常见问题、运维指南（备份恢复、"
     "重置演示数据、健康检查、systemd + nginx 生产部署）。",
     "飞奔成本,操作手册,用户指南,成本管理"),
    ("demo/feiben-cost-demo.zip", "飞奔成本管理系统离线演示（DEMO）",
     "单文件离线演示：解压后双击 HTML 即可用浏览器打开，无需服务与网络。数据取自线上实例"
     "2026-10 期间真实快照：10 成本中心（3 辅助阶梯分摊）/ 8 产品含 BOM / 10 工单 / 20 费用单 / "
     "20 预算行 / 5 产品五维差异 / 分摊守恒校验 146500.00。12 个页签覆盖仪表盘、主数据、"
     "标准成本、工单、费用、分摊（含规则与摊出明细）、预算、差异、报表、期间结账。",
     "飞奔成本,DEMO,离线演示,成本管理"),
]


def req(path, method="GET", data=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if data is not None:
        r.data = json.dumps(data).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                     # noqa: BLE001
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    mime = "application/zip" if full.endswith(".zip") else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if full.endswith(".docx") else "text/markdown")
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:                                         # noqa: BLE001
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def build_demo_zip():
    src = os.path.join(ROOT, "demo", "feiben-cost-demo.html")
    out = os.path.join(ROOT, "demo", "feiben-cost-demo.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "飞奔成本管理系统Demo.html")
        z.writestr("使用说明.txt",
                   "飞奔成本管理系统 · 离线演示\r\n"
                   "1. 解压后双击「飞奔成本管理系统Demo.html」，用浏览器打开即可，无需安装、无需联网。\r\n"
                   "2. 数据为线上实例 2026-10 期间真实快照：10 成本中心 / 8 产品 / 10 工单 / 20 费用单 / 20 预算行。\r\n"
                   "3. 12 个页签：仪表盘 / 成本中心 / 会计科目 / 产品与BOM / 标准成本 / 工单管理 / 费用归集 /\r\n"
                   "   阶梯分摊 / 预算管控 / 差异分析 / 报表中心 / 期间结账。\r\n"
                   "4. 本页为静态展示，不含写操作；分摊守恒（146500.00）与差异五维闭合（checkDiff=0.00）\r\n"
                   "   在页面上可直接核对。\r\n"
                   "5. 完整版本请访问 http://42.193.158.63/cost/（admin / cost@2026）。\r\n")
    print("DEMO zip 重建：%.1f KB" % (os.path.getsize(out) / 1024.0))


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    st, j = req("/api/users/whoami", token=TOKEN)
    print("whoami:", j.get("code"))

    build_demo_zip()

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-28s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    st, j = req("/api/document-categories", token=TOKEN)
    for c in (j.get("data") or []):
        if isinstance(c, dict) and c.get("id") == CAT:
            print("cat%d docCount:" % CAT, c.get("docCount"))


if __name__ == "__main__":
    main()
