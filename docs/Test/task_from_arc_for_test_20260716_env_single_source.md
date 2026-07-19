# 测试任务：后端数据源 ENV 单一配置源

日期：2026-07-16

## 测试目标

验证所有后端数据源运行配置只来自 ENV，旧 JSON 与航班合同注册文件不再影响运行结果，并保证配置集中后不降低事实安全和敏感信息保护。

## 配置加载测试

- `TRAVEL_DATA_SOURCE_IDS` 能正确注册一个和多个数据源。
- source_id 重复、空值、非法字符时启动失败。
- 未知 `ADAPTER` 启动失败，并只输出 source_id/键名。
- 布尔、整数、枚举、URL、HTTP Method 和 Host allowlist 类型校验正确。
- `ENABLED=true` 且缺少必填变量时启动失败。
- `ENABLED=false` 且缺少凭证时允许启动并返回 `DISABLED`。
- 未被消费的 `TRAVEL_SOURCE_*` 键会被检测，不允许静默忽略。
- 测试通过 monkeypatch 注入环境，结束后不污染其他用例和开发机 `.env`。

## 单一配置源测试

- 删除旧 JSON 后全量测试和后端启动通过。
- 搜索确认运行时代码没有读取 `data_sources.dev.json`、`data_sources.test.json`、`data_sources.prod.json`。
- 搜索确认不存在 `flight_provider_contracts` 和 `public_airline_contract_ready` 引用。
- `.env.example` 中每个 `TRAVEL_DATA_SOURCE_IDS` 示例项都有对应 adapter 和必填键。
- settings 模型的可配置字段都能在 `.env.example` 找到，且示例不含真实 secret。

## Provider 回归

- 12306、地图、地理编码、天气、LLM、航班状态、官方跳转分别验证启用、禁用和缺失配置状态。
- Provider 构造器使用传入 settings；修改进程环境后，不应在同一进程中隐式改变已创建的配置快照。
- 禁用 Provider 不创建 HTTP client、不发起网络请求。
- QPS、timeout、retry、cache TTL 使用 ENV 中的类型化值。
- 非 allowlist HTTPS host 被拒绝；HTTP 或畸形 URL 被拒绝。

## 航班安全回归

- 删除航班合同文件后，未实现/未注册 adapter 仍不能生成航班。
- `ENABLED=true` 不能绕过响应 schema、票价、舱位、库存和时间事实校验。
- Provider 返回空、验证码、限流、token 失败、超时和非法响应时，航班候选保持为空并返回明确错误。
- OpenSky 状态 Provider 与航班报价 Provider 的能力边界保持独立。
- 航司官方 redirect 不得被当成航班报价来源。
- 无真实报价时不得恢复模板航班或模拟价格。

## API 与日志测试

- `/api/data-sources/status` 外部 schema 保持兼容。
- 状态中的 `enabled`、`health_status`、`degraded_reason` 与同一 ENV 快照一致。
- 错误日志只包含 source_id 和非法/缺失键名，不含键值。
- HTTP 请求日志不包含 API key、token、Cookie 或完整敏感 query string。

## 规划集成测试

- 铁路 Provider 可用、航班 Provider 禁用时，只生成真实铁路候选，并明确标记 `flight_core_fact` 缺失。
- 航班 Provider 返回完整真实 offer 时，生成包含 `FLIGHT` segment 的计划。
- 航班 Provider 配置非法时启动失败，不等到用户发起任务后才模糊返回无候选。
- 混合空铁方案只消费已验证铁路和航班事实。

## 建议执行

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_data_sources.py -q
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py -q
.\.venv\Scripts\python -m pytest backend/app/tests/test_api.py -q
.\.venv\Scripts\python -m pytest backend/app/tests -q
rg -n "data_sources\.(dev|test|prod)\.json|flight_provider_contracts|public_airline_contract_ready" backend scripts
```

## 通过标准

- 所有配置加载、Provider、API 和规划回归通过。
- 旧配置源引用为 0。
- `.env.example` 一致性检查通过。
- 日志脱敏测试通过。
- 没有模拟航班、静默 fallback 或双配置源。
