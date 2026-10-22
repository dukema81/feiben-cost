# 飞奔成本管理系统 · 立项与设计文档 v1.0

| 项 | 内容 |
|---|---|
| 系统名称 | 飞奔成本管理系统（FeiBen Cost Management） |
| 代号 | feiben-cost |
| 版本 | v1.0.0 |
| 立项日期 | 2026-10-22 |
| 交付形态 | 零依赖 Python 单体服务（http.server + sqlite3）+ 原生 JS 前端 |
| 端口 | 8020（FEIBEN_PORT） |
| 演示账号 | admin / cost@2026 |

---

## 1. 背景与目标

制造型企业的成本管理普遍卡在三个断点上：**标准成本定不下来、实际成本归不上去、差异说不清楚**。Excel 拼凑的成本表每月要 3~5 人天，且口径不统一——同一批产品，财务算的、生产算的、老板看到的三个数。

飞奔成本管理系统要把这条链路一次打通：

1. **可定义**：成本中心 / 成本科目 / 产品 BOM / 标准费率四张主数据定死口径；
2. **可归集**：费用单 + 工单领料 + 工时报工，三源归集到成本中心与产品；
3. **可分摊**：辅助成本中心按动因阶梯分摊到生产中心，分摊前后总额守恒；
4. **可核算**：工单实际成本 → 约当产量法分离完工与在制 → 单位成本与成本卡；
5. **可分析**：标准 vs 实际，价差 / 量差 / 效率差 / 耗费差四维分解，且分解项之和必须等于总差异；
6. **可控制**：预算额度前置管控 + 期间结账闸口，杜绝「事后填数」。

### 设计原则

- **口径优先于功能**：所有算法写在 `backend/cost.py` 纯函数层，可单测、可复现，不埋在路由里。
- **闸口而非提示**：不合规的单据在服务端直接拦截（结账后禁止改数、阶梯分摊禁止回分、超预算按规则阻断）。
- **守恒可校验**：分摊总额、差异分解、产品成本卡三处均输出校核字段，前端可见。

---

## 2. 业务范围（模块清单）

| # | 模块 | 核心对象 | 关键能力 |
|---|---|---|---|
| 1 | 成本中心 | cost_centers | 四类中心（生产/辅助/管理/销售）+ 费率 + 分摊顺序 + 动因量 |
| 2 | 成本科目 | subjects | 材料/人工/制造费用/期间费用四大类，直接/间接归集方式 |
| 3 | 产品与 BOM | products / bom_lines | 物料用量、损耗率、标准单价、标准工时、售价 |
| 4 | 标准成本 | std_costs | 按期间+版本计算单位标准成本卡（材料/人工/制费） |
| 5 | 生产工单 | work_orders | 领料、报工、完工入库、约当产量、在制成本 |
| 6 | 费用归集 | expenses | 手工/导入费用单，审批流，预算占用回写 |
| 7 | 分摊 | allocation_rules / runs | 阶梯分摊，动因权重，守恒校核 |
| 8 | 预算 | budgets | 期间×中心×科目额度，执行率与超支预警 |
| 9 | 差异分析 | variances | 价差/量差/效率差/耗费差，四维分解 |
| 10 | 报表 | — | 成本中心汇总、产品成本卡、差异 TOP、趋势、CSV 导出 |
| 11 | 期间管理 | periods | 打开/结账，三闸口校验 |
| 12 | 系统 | users / rules / keys / webhooks | 8 角色权限、业务规则、API Key、Webhook、审计日志 |

---

## 3. 核心业务口径（可验证部分）

### 3.1 标准成本卡

```
材料标准成本 = Σ ( 用量 × (1 + 损耗率) × 标准单价 )
人工标准成本 = 标准工时 × 中心人工费率
制造标准成本 = 标准工时 × 中心制造费率
单位标准成本 = 材料 + 人工 + 制造
```

### 3.2 实际成本归集（工单）

```
实际材料 = Σ 领料明细金额
实际人工 = Σ 报工金额  （工时 × 工资率）
实际制费 = 实际工时 × 中心制造费率（预定分配率）
合计     = 材料 + 人工 + 制费
```

### 3.3 约当产量法（完工 / 在制分离）

```
约当产量 = 完工数量 + 在制数量 × 完工进度
单位成本 = 合计成本 ÷ 约当产量
完工转出 = 单位成本 × 完工数量
在制成本 = 单位成本 × 在制数量 × 完工进度
```

闸口：完工数量 > 计划数量时拒绝；完工进度不在 (0,1] 时拒绝；约当产量为 0 时拒绝核算。

### 3.4 差异分解（两因素法，四维）

| 维度 | 公式 | 适用范围 |
|---|---|---|
| 价差（材料） | (实际单价 − 标准单价) × 实际用量 | 材料 |
| 量差（材料） | (实际用量 − 标准用量) × 标准单价 | 材料 |
| 工资率差异 | (实际工资率 − 标准工资率) × 实际工时 | 人工 |
| 效率差异 | (实际工时 − 标准工时) × 标准工资率 | 人工 / 制费 |
| 耗费差异 | 实际制造费用 − 预算制造费用 | 制造费用 |

**强制校核**：`价差 + 量差 = 总差异`，偏差超过 0.01 元即视为算法故障（单测 4 条覆盖）。

### 3.5 阶梯分摊法

- 辅助中心按 `alloc_order` 升序依次分摊；
- 每个中心把「自身直接归集 + 上游分入」按受益中心权重全部摊出；
- **禁止回分**：只能分给 `alloc_order` 更大的中心，违反即报错；
- **守恒校核**：`分摊前辅助中心合计 = 分摊出去总额`，差额 > 0.01 元视为失败；
- 权重来源：人工工时 / 机器工时 / 面积 / 人数 / 直接成本，按规则权重归一。

### 3.6 预算与结账闸口

| 闸口 | 触发点 | 判定 |
|---|---|---|
| 预算占用 | 费用单提交 | 期间+中心+科目 累计 > 预算 × 阻断倍率（默认 1.1）→ 拒绝 |
| 期间关闭 | 费用单/工单/分摊写入 | 期间状态 = 已结账 → 一律拒绝 |
| 结账 | 期末结账 | 待审批费用单 > 0 / 未完工工单 > 0 / 分摊未执行 → 拒绝 |

---

## 4. 数据模型（24 表）

| 表 | 说明 | 关键字段 |
|---|---|---|
| users | 用户 | username, password_hash, salt, role |
| cost_centers | 成本中心 | code, name, ctype, parent_code, labor_rate, oh_rate, alloc_order, driver, driver_qty |
| subjects | 成本科目 | code, name, category, gather(直接/间接), enabled |
| products | 产品 | code, name, spec, unit, std_hours, center_code, list_price |
| bom_lines | BOM 明细 | product_code, material_code, qty_per, loss_rate, std_price |
| std_costs | 标准成本卡 | period, product_code, version, mat_cost, labor_cost, oh_cost, unit_cost |
| work_orders | 生产工单 | no, product_code, qty_plan, qty_done, wip_rate, center_code, period, status |
| wo_materials | 工单领料 | wo_no, material_code, qty, price, amount |
| wo_labor | 工时报工 | wo_no, work_type, hours, rate, amount |
| expenses | 费用归集单 | no, period, center_code, subject_code, amount, source, status |
| allocation_rules | 分摊规则 | from_center, to_center, driver, weight, enabled |
| allocation_runs | 分摊批次 | no, period, method, total_allocated, status |
| allocation_lines | 分摊明细 | run_no, from_center, to_center, base_amount, amount |
| budgets | 预算 | period, center_code, subject_code, amount, used |
| variances | 差异分析 | period, product_code, qty, std_cost, act_cost, total/price/qty/eff/expense_var |
| periods | 会计期间 | period, status, closed_at, closed_by |
| rules | 业务规则 | code, name, category, value, unit |
| logs | 审计日志 | at, user, action, detail |
| api_keys | API Key | key_hash, name, scope |
| webhooks / webhook_deliveries | 事件推送 | url, secret, events, status, attempts |
| idem_keys | 幂等键 | key, status, response |
| sync_state | 增量同步游标 | entity, last_at |
| tokens | 会话令牌 | token, username, created |

---

## 5. API 契约（72 路由）

约定：全部 `/api/*`，JSON in/out；鉴权 `Authorization: Bearer <token>`（兼容 `X-Fb-Token` / Cookie / `X-Fb-Key`）；错误 `{code, message}`。

### 5.1 认证与看板

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/auth/login | {username, password} → {token, user} |
| POST | /api/auth/logout | 注销令牌 |
| GET | /api/auth/me | 当前用户与权限 |
| PUT | /api/auth/password | 修改密码 {old, new} |
| POST | /api/auth/change-password | 别名（old_password/new_password） |
| GET | /api/board | 驾驶舱 KPI |

### 5.2 主数据

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/cost-centers | 列表（含归集/分摊净额）/ 新建 |
| PUT | /api/cost-centers/{code} | 修改 |
| GET/POST | /api/subjects | 科目列表 / 新建 |
| PUT | /api/subjects/{code} | 修改 |
| GET/POST | /api/products | 产品列表 / 新建 |
| GET | /api/products/{code} | 产品 + BOM + 标准卡 |
| PUT | /api/products/{code} | 修改 |
| GET/POST | /api/products/{code}/bom | BOM 明细 / 追加 |
| DELETE | /api/products/{code}/bom/{id} | 删除 BOM 行 |

### 5.3 标准成本

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/std-costs?period= | 期间标准卡列表 |
| POST | /api/std-costs/calc | 按期计算（全产品或指定产品）→ 生成新版本 |
| POST | /api/std-costs/{period}/{product}/publish | 发布版本 |

### 5.4 生产工单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/work-orders | 列表 / 新建 |
| GET | /api/work-orders/{no} | 详情（领料+报工+成本） |
| PUT | /api/work-orders/{no} | 修改计划量/进度/中心 |
| POST | /api/work-orders/{no}/materials | 领料 |
| POST | /api/work-orders/{no}/labor | 报工 |
| POST | /api/work-orders/{no}/calc | 核算实际成本（约当产量） |
| POST | /api/work-orders/{no}/stage | 状态流转（已完工/已关闭） |

### 5.5 费用归集

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/expenses | 列表（期间/中心/科目筛选）/ 新建（预算闸口） |
| POST | /api/expenses/{no}/stage | 提交/批准/驳回（预算回写） |
| GET | /api/expenses/summary?period= | 按科目类别汇总 |

### 5.6 分摊

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/allocation-rules | 规则列表 / 新建（禁止回分） |
| DELETE | /api/allocation-rules/{id} | 删除 |
| POST | /api/allocations/run | 执行阶梯分摊 {period} |
| GET | /api/allocations | 批次列表 |
| GET | /api/allocations/{no} | 批次明细（含守恒校核） |

### 5.7 预算与差异

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/budgets?period= | 预算列表 / 设定（同键 upsert） |
| GET | /api/budgets/exec?period= | 执行率报表 |
| GET/POST | /api/variances | 差异列表 / 计算（按期或单产品+工单） |

### 5.8 报表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/reports/center-summary?period= | 成本中心汇总（直接+分入−分出） |
| GET | /api/reports/product-cost?period= | 产品成本卡（标准 vs 实际 vs 差异） |
| GET | /api/reports/variance-top?period=&n= | 差异 TOP N |
| GET | /api/reports/trend?months= | 成本趋势 |
| GET | /api/reports/(centers\|products\|expenses\|variances).csv | CSV 导出 |

### 5.9 期间与系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | /api/periods | 期间列表 / 新建 |
| POST | /api/periods/{period}/close | 结账（三闸口） |
| POST | /api/periods/{period}/reopen | 反结账（admin） |
| GET | /api/rules · PUT /api/rules/{code} | 业务规则 |
| GET/POST | /api/users | 用户 |
| GET | /api/logs | 审计日志 |
| GET/POST | /api/keys · POST /api/keys/{id}/revoke | API Key |
| GET/POST | /api/webhooks · POST /api/webhooks/test · GET /api/webhooks/deliveries | Webhook |
| GET | /api/sync/changes?since= | 增量同步 |
| GET | /api/health · /api/openapi.json | 健康检查 / OpenAPI |

---

## 6. 权限矩阵（7 角色 × 14 权限）

| 角色 | 说明 | 权限 |
|---|---|---|
| admin | 系统管理员 | 全部 |
| cost_manager | 成本经理 | 主数据写 + 工单/费用/分摊/预算/报表 + 结账 |
| accountant | 成本会计 | 费用/分摊/差异/报表 + 标准成本 |
| center_owner | 成本中心负责人 | 本中心费用提交、报表只读 |
| production | 生产统计 | 工单/领料/报工 |
| viewer | 只读 | 全部 read |
| auditor | 审计 | read + 日志 + 差异 |

---

## 7. 技术架构

```
浏览器（原生 JS SPA，6 个页模块）
   ↕ JSON over HTTP
backend/server.py  路由/鉴权/限流/幂等/Webhook/OpenAPI（约 75 路由）
   ↕
backend/cost.py    纯函数业务内核（标准成本/约当产量/差异/分摊/闸口）
   ↕
backend/db.py      sqlite3 WAL，24 表，线程本地连接
```

- 零第三方依赖，Python 3.8+ 直接跑；
- 前端不引入框架，滚动表格 + SVG 图表，单文件 CSS；
- 部署：systemd + nginx 子路径 `/cost/`（端口 8020）。

---

## 8. 里程碑

| 阶段 | 交付物 | 验收 |
|---|---|---|
| M1 设计 | 本文档 + API 契约 | 口径评审通过 |
| M2 后端 | db / cost / seed / server | 单元测试 30+ 全绿 |
| M3 前端 | 15 页 + 6 模块 | UI 巡检无 JS 错误 |
| M4 测试 | 单元/接口/冒烟/E2E | 四类门禁全绿 |
| M5 部署 | systemd + nginx + 公网 | 公网登录与三闸口实测 |
| M6 交付 | 用户手册 + 部署包 + GitHub | 文档齐备 |

## 9. 验收标准

1. 标准成本卡计算与手工 Excel 复算一致（误差 ≤ 0.01 元）；
2. 差异分解：价差 + 量差 = 总差异（单测断言）；
3. 分摊守恒：分摊前辅助中心合计 = 分摊总额（单测断言）；
4. 结账闸口：待审批单据存在时结账必须失败；
5. 结账后写入必须被拒（费用/工单/分摊三处）；
6. 公网可登录，admin 口令非默认弱口令。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 企业实际 BOM 层级复杂（多级 BOM） | v1.0 只做单层 BOM，多级展开列入 v1.1 |
| 分摊动因数据缺失 | 动因量未维护时按 1 均分，并在报表标注「按均分」 |
| 与 ERP 重复建设 | 通过 API Key + Webhook 与飞鸢 ERP 对接，不重复做主数据 |
| 期间结账后数据修正 | 反结账限 admin 且写审计日志 |
