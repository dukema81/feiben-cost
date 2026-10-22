# -*- coding: utf-8 -*-
"""从路由表生成 docs/api.md"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("FEIBEN_DB", os.path.join(ROOT, "backend", "data", "feiben.db"))

import cost  # noqa: E402
import server  # noqa: E402

HEAD = """# 飞奔成本管理系统 · API 契约 v__VER__

基础路径：`/api`（生产环境经 nginx 子路径 `/cost/` 转发，服务端同时兼容带前缀与不带前缀两种请求）

## 通用约定

| 项 | 约定 |
|---|---|
| 传输 | HTTP/1.1，`Content-Type: application/json; charset=utf-8` |
| 鉴权 | `Authorization: Bearer <token>`（兼容 `X-Fb-Token`、Cookie `token`、查询串 `?token=`、`X-Fb-Key`） |
| 只读 Key | `X-Fb-Key: fb_xxx`，scope=read 时禁止一切写操作（403） |
| 错误 | 非 2xx 返回 `{ "code": 400, "message": "中文原因" }` |
| 限流 | 单 IP 300 次/分钟，超限 429 |
| 幂等 | POST 携带 `Idempotency-Key`，重复请求返回首次响应并带 `X-Idempotent-Replay: true` |
| 期间 | 写操作均校验会计期间状态，已结账期间返回 409 |
| 金额 | 统一两位小数，四舍五入；差异分解尾差归入材料量差以保证闭合 |
| 导出 | `GET /api/reports/{centers,products,expenses,variances}.csv?period=YYYY-MM`，UTF-8 BOM |

## 权限矩阵

| 角色 | 权限 |
|---|---|
"""


def main():
    lines = [HEAD.replace("__VER__", cost.VERSION)]
    for code, r in cost.ROLES.items():
        lines.append("| `%s` %s | %s |\n" % (code, r["name"], "、".join(r["perms"])))
    lines.append("\n## 路由清单（共 %d 条）\n\n" % len(server.ROUTES))
    lines.append("| # | 方法 | 路径 | 所需权限 | 处理函数 |\n|---|---|---|---|---|\n")
    for i, (mth, pat, fn, perm) in enumerate(server.ROUTES, 1):
        p = pat.replace("^", "").replace("$", "")
        lines.append("| %d | %s | `%s` | %s | %s |\n" % (
            i, mth, p, ("`%s`" % perm) if perm else "登录即可",
            fn.__name__ if fn else "export"))
    lines.append("\n## 事件（Webhook）\n\n")
    lines.append("、".join("`%s`" % e for e in server.EVENTS) + "\n\n")
    lines.append("签名：`X-Fb-Signature = HMAC-SHA256(secret, timestamp + '.' + payload)`，"
                 "头部同时带 `X-Fb-Event`、`X-Fb-Timestamp`；失败按 30/60/120 秒退避重试 3 次。\n")
    out = os.path.join(ROOT, "docs", "api.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    print("written", out, "routes", len(server.ROUTES))


if __name__ == "__main__":
    main()
