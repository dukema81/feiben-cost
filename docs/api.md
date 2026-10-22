# 飞奔成本管理系统 · API 契约 v1.0.0

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
| `admin` 系统管理员 | center.read、center.write、subject.read、subject.write、product.read、product.write、std.read、std.write、wo.read、wo.write、exp.read、exp.write、exp.approve、alloc.read、alloc.write、budget.read、budget.write、report.read、period.close、admin |
| `cost_manager` 成本经理 | center.read、center.write、subject.read、subject.write、product.read、product.write、std.read、std.write、wo.read、wo.write、exp.read、exp.write、exp.approve、alloc.read、alloc.write、budget.read、budget.write、report.read、period.close |
| `accountant` 成本会计 | center.read、subject.read、product.read、std.read、std.write、wo.read、exp.read、exp.write、exp.approve、alloc.read、alloc.write、budget.read、report.read |
| `center_owner` 成本中心负责人 | center.read、subject.read、product.read、std.read、wo.read、exp.read、exp.write、alloc.read、budget.read、report.read |
| `production` 生产统计 | center.read、subject.read、product.read、std.read、wo.read、wo.write、exp.read、report.read |
| `viewer` 只读用户 | center.read、subject.read、product.read、std.read、wo.read、exp.read、alloc.read、budget.read、report.read |
| `auditor` 审计 | center.read、subject.read、product.read、std.read、wo.read、exp.read、alloc.read、budget.read、report.read |

## 路由清单（共 69 条）

| # | 方法 | 路径 | 所需权限 | 处理函数 |
|---|---|---|---|---|
| 1 | POST | `/api/auth/login` | 登录即可 | api_login |
| 2 | POST | `/api/auth/logout` | 登录即可 | api_logout |
| 3 | GET | `/api/auth/me` | 登录即可 | api_me |
| 4 | PUT | `/api/auth/password` | 登录即可 | api_password |
| 5 | POST | `/api/auth/change-password` | 登录即可 | api_password |
| 6 | GET | `/api/board` | 登录即可 | api_board |
| 7 | GET | `/api/cost-centers` | `center.read` | api_center_list |
| 8 | POST | `/api/cost-centers` | `center.write` | api_center_create |
| 9 | PUT | `/api/cost-centers/([/]+)` | `center.write` | api_center_update |
| 10 | GET | `/api/subjects` | `subject.read` | api_subject_list |
| 11 | POST | `/api/subjects` | `subject.write` | api_subject_create |
| 12 | PUT | `/api/subjects/([/]+)` | `subject.write` | api_subject_update |
| 13 | GET | `/api/products` | `product.read` | api_product_list |
| 14 | POST | `/api/products` | `product.write` | api_product_create |
| 15 | GET | `/api/products/([/]+)` | `product.read` | api_product_detail |
| 16 | PUT | `/api/products/([/]+)` | `product.write` | api_product_update |
| 17 | GET | `/api/products/([/]+)/bom` | `product.read` | api_bom_list |
| 18 | POST | `/api/products/([/]+)/bom` | `product.write` | api_bom_add |
| 19 | DELETE | `/api/products/([/]+)/bom/([0-9]+)` | `product.write` | api_bom_delete |
| 20 | GET | `/api/std-costs` | `std.read` | api_std_list |
| 21 | POST | `/api/std-costs/calc` | `std.write` | api_std_calc |
| 22 | POST | `/api/std-costs/([0-9\-]+)/([/]+)/publish` | `std.write` | api_std_publish |
| 23 | GET | `/api/work-orders` | `wo.read` | api_wo_list |
| 24 | POST | `/api/work-orders` | `wo.write` | api_wo_create |
| 25 | GET | `/api/work-orders/([/]+)` | `wo.read` | api_wo_detail |
| 26 | PUT | `/api/work-orders/([/]+)` | `wo.write` | api_wo_update |
| 27 | POST | `/api/work-orders/([/]+)/materials` | `wo.write` | api_wo_material |
| 28 | POST | `/api/work-orders/([/]+)/labor` | `wo.write` | api_wo_labor |
| 29 | POST | `/api/work-orders/([/]+)/calc` | `wo.write` | api_wo_calc |
| 30 | POST | `/api/work-orders/([/]+)/stage` | `wo.write` | api_wo_stage |
| 31 | GET | `/api/expenses` | `exp.read` | api_exp_list |
| 32 | POST | `/api/expenses` | `exp.write` | api_exp_create |
| 33 | GET | `/api/expenses/summary` | `exp.read` | api_exp_summary |
| 34 | POST | `/api/expenses/([/]+)/stage` | `exp.write` | api_exp_stage |
| 35 | GET | `/api/allocation-rules` | `alloc.read` | api_rule_list |
| 36 | POST | `/api/allocation-rules` | `alloc.write` | api_rule_create |
| 37 | DELETE | `/api/allocation-rules/([0-9]+)` | `alloc.write` | api_rule_delete |
| 38 | POST | `/api/allocations/run` | `alloc.write` | api_alloc_run |
| 39 | GET | `/api/allocations` | `alloc.read` | api_alloc_list |
| 40 | GET | `/api/allocations/([/]+)` | `alloc.read` | api_alloc_detail |
| 41 | GET | `/api/budgets` | `budget.read` | api_budget_list |
| 42 | POST | `/api/budgets` | `budget.write` | api_budget_upsert |
| 43 | GET | `/api/budgets/exec` | `budget.read` | api_budget_exec |
| 44 | GET | `/api/variances` | `report.read` | api_variance_list |
| 45 | POST | `/api/variances/calc` | `report.read` | api_variance_calc |
| 46 | GET | `/api/reports/center-summary` | `report.read` | api_rep_center_summary |
| 47 | GET | `/api/reports/product-cost` | `report.read` | api_rep_product_cost |
| 48 | GET | `/api/reports/variance-top` | `report.read` | api_rep_variance_top |
| 49 | GET | `/api/reports/trend` | `report.read` | api_rep_trend |
| 50 | GET | `/api/reports/(centers|products|expenses|variances)\.csv` | 登录即可 | export |
| 51 | GET | `/api/periods` | `report.read` | api_period_list |
| 52 | POST | `/api/periods` | `period.close` | api_period_create |
| 53 | POST | `/api/periods/([0-9\-]+)/close` | `period.close` | api_period_close |
| 54 | POST | `/api/periods/([0-9\-]+)/reopen` | `admin` | api_period_reopen |
| 55 | GET | `/api/rules` | 登录即可 | api_rules |
| 56 | PUT | `/api/rules/([/]+)` | `admin` | api_rule_update |
| 57 | GET | `/api/users` | `admin` | api_user_list |
| 58 | POST | `/api/users` | `admin` | api_user_create |
| 59 | GET | `/api/logs` | `admin` | api_logs |
| 60 | GET | `/api/keys` | `admin` | api_key_list |
| 61 | POST | `/api/keys` | `admin` | api_key_create |
| 62 | POST | `/api/keys/([0-9]+)/revoke` | `admin` | api_key_revoke |
| 63 | GET | `/api/webhooks` | `admin` | api_wh_list |
| 64 | POST | `/api/webhooks` | `admin` | api_wh_create |
| 65 | POST | `/api/webhooks/test` | `admin` | api_wh_test |
| 66 | GET | `/api/webhooks/deliveries` | `admin` | api_wh_deliveries |
| 67 | GET | `/api/sync/changes` | 登录即可 | api_sync |
| 68 | GET | `/api/health` | 登录即可 | api_health |
| 69 | GET | `/api/openapi\.json` | 登录即可 | api_openapi |

## 事件（Webhook）

`center.created`、`product.created`、`std.calculated`、`wo.created`、`wo.completed`、`expense.created`、`expense.approved`、`expense.rejected`、`alloc.executed`、`budget.updated`、`period.closed`、`variance.calculated`、`test.ping`

签名：`X-Fb-Signature = HMAC-SHA256(secret, timestamp + '.' + payload)`，头部同时带 `X-Fb-Event`、`X-Fb-Timestamp`；失败按 30/60/120 秒退避重试 3 次。
