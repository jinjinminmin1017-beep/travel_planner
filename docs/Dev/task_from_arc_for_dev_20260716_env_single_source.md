# 开发任务：后端数据源 ENV 单一配置源

日期：2026-07-16

## 目标

将所有后端数据源运行配置统一到进程环境变量；本地由根目录 `.env` 注入，`.env.example` 成为唯一非敏感配置清单。删除数据源 JSON 配置源和 `flight_provider_contracts.py` 的运行时配置/门禁职责。

本任务不通过伪造 Provider 事实恢复航班。航班适配器未完成或真实查询失败时仍必须阻断航班方案。

## 任务范围

### 1. 建立类型化 ENV loader

- 在 `backend/app/data_sources/config_loader.py` 定义不可变 `DataSourceSettings` 基础模型与各 adapter 的特有 settings。
- 支持 `TRAVEL_DATA_SOURCE_IDS` 注册清单。
- 统一解析 `TRAVEL_SOURCE_<ID>_*`，至少覆盖：
  - `ADAPTER`
  - `ENABLED`
  - `LICENSE_STATUS`
  - `COMMERCIAL_ALLOWED`
  - `QPS_LIMIT`
  - `BASE_URL`
  - `SEARCH_PATH`
  - `HTTP_METHOD`
  - `ALLOWED_HOSTS`
  - `TIMEOUT_SECONDS`
  - `CACHE_TTL_SECONDS`
- 凭证字段由 adapter settings 定义，日志和异常不得输出值。
- 删除 JSON 加载、环境覆盖和 JSON fallback 逻辑。
- 对未知 `TRAVEL_SOURCE_*` 键、重复 source_id、未知 adapter、非法布尔/整数/枚举、启用源缺少必填项执行启动校验。

### 2. 统一 Provider 构造

- 建立 adapter 注册表：`adapter_name -> settings model + provider factory`。
- 修改 `*_providers.py`，由构造器接收 settings；移除模块内部散落的 `os.getenv()`。
- Provider 查询函数只使用启动时生成的不可变配置快照。
- 禁用 Provider 不构造网络客户端，不要求凭证。
- 启用 Provider 配置非法时启动失败，不返回“无 Provider”的模糊运行结果。

### 3. 收敛航班配置

- 删除 `backend/app/data_sources/flight_provider_contracts.py`。
- 将航司请求构造、响应解析、schema 校验和错误映射保留在 `flight_providers.py` 或拆分后的航司 adapter 中。
- 移除 `public_airline_contract_ready()` 运行门禁和合同注册表依赖。
- 不新增可手工设置的 `TECHNICAL_READY`/`CONTRACT_READY` 环境变量。
- `ENABLED=true` 只表示允许尝试构造和调用 Provider；adapter 缺失、必填配置缺失或健康检查失败时必须返回明确状态并阻止航班候选。
- 清理 Amadeus 等没有 adapter 消费的历史变量，或在本任务中补齐正式 adapter 后再保留；禁止保留无消费变量。

### 4. 维护唯一 ENV 清单

- 更新 `.env.example`，按数据源分组列出全部非敏感变量、安全默认值和简短说明。
- 更新本地 `.env` 只允许调整非敏感配置结构；不得在提交中包含真实凭证或本机值。
- 删除：
  - `backend/app/data_sources/data_sources.dev.json`
  - `backend/app/data_sources/data_sources.test.json`
  - `backend/app/data_sources/data_sources.prod.json`
- 更新 `scripts/check_real_api_config.py`、smoke 脚本和启动脚本，只读取 ENV settings。
- 更新 `docs/PROJECT_INDEX.md`，将后端运行配置入口改为 `.env/.env.example`。

### 5. 状态与可观测性

- `/api/data-sources/status` 继续使用现有响应 schema。
- `enabled` 来自不可变 ENV 快照；`health_status/degraded_reason` 结合配置校验与实际健康检查生成。
- `degraded_reason` 必须区分：未知 adapter、缺少键、非法 host、凭证缺失、许可未批准、健康检查失败、Provider 返回空。
- 日志不得输出 secret、token、Cookie 或完整带 query key 的 URL。

## 验收标准

- 运行时代码不再读取 `data_sources.*.json`。
- 仓库不存在对 `flight_provider_contracts.py` 或 `public_airline_contract_ready` 的引用。
- 所有 Provider 的可变运行配置只来自 ENV settings。
- `.env.example` 与 settings 字段、adapter 注册表通过自动一致性检查。
- 启用源缺少必填配置时后端启动失败，错误只包含 source_id 和键名。
- 禁用源缺少凭证时后端可以启动，状态明确为 `DISABLED`。
- 未实现航班 Provider 不会因设置 `ENABLED=true` 而生成模板航班。
- 12306、地图、天气、LLM、航班状态、跳转和规划回归通过。
- 不修改 API schema version，不需要数据库迁移。

## 建议验证命令

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_data_sources.py -q
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py -q
.\.venv\Scripts\python -m pytest backend/app/tests -q
rg -n "data_sources\.(dev|test|prod)\.json|flight_provider_contracts|public_airline_contract_ready" backend scripts
```

最后执行一次启动 smoke，并检查：

- `/api/health`
- `/api/data-sources/status`
- 一次铁路规划任务
- 一次航班规划任务；无可用真实 Provider 时必须明确返回 `FLIGHT_PROVIDER_DISABLED` 或更具体配置错误，不得生成模拟航班。

## 完成记录

- 状态：已完成。
- 完成时间：2026-07-16 21:49:56 +08:00。
- 实现提交：`4bb293f`。
- 配置结果：数据源注册、类型化校验和 Provider 构造已统一到 ENV 不可变快照；三个 JSON 配置文件及 `flight_provider_contracts.py` 已删除。
- 航班结果：10 个未实现的官方航司源保持禁用并 fail-closed，不能通过 ENV 伪造技术就绪状态，也不会生成模板航班。
- 自动验证：后端全量 `214 passed`；公共真实 API 配置校验通过；旧 JSON/航班合同符号引用检查为空；`git diff --check` 通过。
- 启动验证：`/api/health` 返回 200，`/api/data-sources/status` 返回 200 并列出 26 个数据源；航班 gate 连续 3 次通过。
- 真实接口验证：地图、地点解析和天气 smoke 通过；12306 一次真实 smoke 收到上游非 JSON 响应，未伪报成功，铁路 Provider 与规划回归仍由全量测试覆盖并通过。
- 兼容性：未修改 API schema version，未修改数据库和前端，不需要数据库迁移。
