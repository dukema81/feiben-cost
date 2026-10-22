# 飞奔成本管理系统（FeiBen Cost Management）

制造业成本核算与分析系统：**标准成本 → 实际归集 → 阶梯分摊 → 约当产量 → 四维差异 → 关账锁期** 全链路打通。
零第三方依赖（Python 标准库 + sqlite3 + 原生 JS），单进程可跑，支持 nginx 子路径部署。

## 快速启动

```bash
cd backend
python server.py            # 默认 127.0.0.1:8020，空库自动播种演示数据
# 或指定端口 / 监听地址
PORT=8020 python server.py
```

浏览器打开 http://127.0.0.1:8020/ ，演示账号 **admin / cost@2026**。

## 目录结构

```
feiben-cost/
├── backend/
│   ├── cost.py       # 纯函数业务内核（标准成本/约当产量/差异/阶梯分摊/闸口/权限）
│   ├── db.py         # 24 表 schema，sqlite3 WAL，线程本地连接
│   ├── seed.py       # 演示数据（10 成本中心 / 15 科目 / 8 产品 / 14 工单 / 30 费用单）
│   └── server.py     # 69 路由 + 鉴权/限流/幂等/Webhook/OpenAPI
├── frontend/         # 13 页原生 JS SPA（无框架）
├── tests/            # pytest：87 条单元 + 接口用例
├── tools/            # 冒烟测试 / API 文档生成 / 打包 / 推送
├── docs/             # 设计文档 / API 契约 / 用户手册 / 测试报告
└── deploy/           # 部署包构建
```

## 核心能力

| 模块 | 说明 |
|---|---|
| 成本中心 | 生产/辅助/管理/销售/研发五类；每中心含人工费率、制造费率、分摊顺序、动因量 |
| 成本科目 | 材料/人工/制造费用/期间费用，直接或间接归集 |
| 产品与 BOM | 物料用量 + 损耗率 + 标准单价 + 标准工时，自动生成材料标准成本 |
| 标准成本 | 按期版本化计算，旧版转历史，可发布指定版本 |
| 生产工单 | 领料、报工、核算、完工；实际成本 = 材料 + 人工 + 工时×制费率 |
| 约当产量 | 完工与在制分离：`约当产量 = 完工数 + 在制数 × 完工进度` |
| 费用归集 | 审批流，批准即占用预算，驳回自动冲回 |
| 成本分摊 | 阶梯（顺序）法，禁止回分，输出守恒校核差 |
| 预算管控 | 期间×中心×科目，90% 预警 / 110% 阻断提交 |
| 差异分析 | 材料价差+量差、人工工资率差+效率差、制费耗费差，五项之和强制等于总差异 |
| 报表中心 | 成本中心汇总、产品成本卡、差异 TOP、12 期趋势、CSV 导出 |
| 期间结账 | 三闸口（无待审批 / 无未完工 / 已分摊），结账后写入一律拒绝，反结账限管理员并留痕 |

## 测试

```bash
python -m pytest tests/ -q        # 87 passed
python tools/smoke_api.py         # 52 checks（全量 GET + 写入链路 + 闸口负例）
```

## 部署（systemd + nginx 子路径）

```ini
# /etc/systemd/system/feiben-cost.service
[Unit]
Description=FeiBen Cost Management
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/feiben-cost/backend
Environment=FEIBEN_PORT=8020
ExecStart=/usr/bin/python3 /opt/feiben-cost/backend/server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

nginx（在已有 server 块内追加）：

```nginx
location /cost/ {
    proxy_pass http://127.0.0.1:8020/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## 演示账号

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | cost@2026 | 系统管理员 |
| manager | cm@2026fB | 成本经理 |
| acct | ac@2026fB | 成本会计 |
| owner | co@2026fB | 成本中心负责人 |
| prod | pd@2026fB | 生产统计 |
| viewer | vw@2026fB | 只读用户 |
| auditor | au@2026fB | 审计 |

> 生产环境请立即通过「系统设置—修改密码」更换口令，并删除演示账号。

## 版本

v1.0.0 · 2026-10-22 · 设计文档见 `docs/feiben-design.md`
