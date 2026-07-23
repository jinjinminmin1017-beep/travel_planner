# ARC-20260722-02 航班 Provider 完整交换证据日志

来源：用户指出 429/业务错误只存摘要、无法事后解释且复现可能不一致。架构设计见 `docs/ARCHITECTURE.md`“航班 Provider 完整交换证据日志”。

状态：待开发。

## 1. 目标

- 每一次航班 Provider 请求都保存完整脱敏请求与响应证据，覆盖成功、空结果、429、WAF、4xx/5xx、业务错误、解析错误、超时和连接失败。
- 响应证据必须在任何风险/状态码/业务码/解析判断之前落盘。
- 普通文本日志只写 `exchange_id` 和摘要；完整内容进入受控 SQLite 证据库。
- 不把 Cookie、Token、设备材料、动态签名或个人信息明文写入任何日志。
- 外部 API V1.17 不变，前端不改。

## 2. 新增 evidence store

新增 `backend/app/data_sources/flight_evidence_store.py`：

- 定义 exchange/outcome/redaction 数据模型。
- 在 `logs/flight_harvest.sqlite3` 创建 additive 表 `flight_provider_exchanges` 和索引。
- 支持先写请求、后补响应、最后回写 outcome 的完整生命周期。
- 请求/响应正文经确定性脱敏后使用 gzip/zlib 压缩保存，不截断。
- 保存原始 body SHA-256、脱敏 body SHA-256、长度、Content-Type、parser/redaction version。
- SQLite 使用 WAL、busy timeout 和短事务；远程请求不放在事务内。
- 保留旧 `flight_raw_snapshots`，不删除、不覆盖。

## 3. 脱敏要求

- Headers：`Authorization`、`Cookie`、`Set-Cookie`、各类 token/signature/device 字段保留字段名，值替换为类型、长度和 HMAC 指纹。
- URL/query、JSON、表单、HTML、纯文本分别处理；未知格式使用保守文本脱敏。
- HMAC key 由 Secret 环境变量注入，不写入 `.env.example` 示例值、日志或数据库。
- 导出前再次执行敏感模式扫描；发现疑似明文 Secret 时拒绝导出并返回明确错误。
- 业务 message、HTTP 状态、响应结构、航线、日期和非敏感正文必须保留，禁止因脱敏整段删除。

## 4. Provider 接入

- 为每次外部交换生成新 `exchange_id`，多阶段 Provider 的 INIT/SEARCH 各自记录并通过 request/correlation id 关联。
- 在发送前写请求证据。
- 收到 `httpx.Response` 后立即持久化 status/headers/body，再调用 `_raise_for_airline_risk_response()`、`raise_for_status()` 和业务解析。
- 捕获 timeout/connect error 时完成无响应 exchange，保存阶段、耗时和稳定错误码。
- 业务码、Empty、parse outcome 在判断后回写同一 exchange。
- 春秋 429 必须能导出当时完整脱敏正文和 headers；青岛航空 `code=0/message=未查询到航班` 必须保存并分类为 EMPTY。
- 证据写入失败且 `TRAVEL_FLIGHT_EVIDENCE_REQUIRED=true` 时阻断 Provider，返回 `FLIGHT_EVIDENCE_PERSISTENCE_FAILED`。

## 5. 配置

在类型化 settings 与 `.env.example` 增加：

```env
TRAVEL_FLIGHT_EVIDENCE_BACKEND=sqlite
TRAVEL_FLIGHT_EVIDENCE_PATH=logs/flight_harvest.sqlite3
TRAVEL_FLIGHT_EVIDENCE_REQUIRED=true
TRAVEL_FLIGHT_EVIDENCE_SUCCESS_RETENTION_DAYS=90
TRAVEL_FLIGHT_EVIDENCE_FAILURE_RETENTION_DAYS=180
TRAVEL_FLIGHT_EVIDENCE_HMAC_KEY=
```

- 示例 key 留空并说明通过 Secret Manager/部署环境注入。
- 生产 `REQUIRED=true`；本地测试可显式使用临时 key 和临时数据库。
- 配置非法或 required 模式缺 key 时启动失败，不得运行中静默降级。

## 6. 导出与清理

- 新增 `scripts/export_flight_exchange.py --exchange-id <id>`，输出完整脱敏证据和哈希。
- 新增 `--cleanup-expired` 或独立清理命令，按批次删除过期记录。
- 导出/清理写结构化审计日志，不记录正文或 Secret。
- 不新增公开 HTTP 下载接口。

## 7. 目标文件

- `backend/app/data_sources/flight_evidence_store.py`（新增）
- `backend/app/data_sources/flight_providers.py`
- `backend/app/data_sources/browser_worker_client.py`
- `backend/app/data_sources/provider_registry.py`
- `backend/app/data_sources/config_loader.py`
- `browser_worker/src/airlines/*` 与内部契约（仅证据元数据传递所需）
- `.env.example`
- `scripts/export_flight_exchange.py`（新增）
- 对应后端/worker 测试
- `docs/PROJECT_INDEX.md`、`docs/Dev/code_change_log.md`

## 8. 验收标准

- 429 响应在异常抛出后仍能按 exchange_id 导出完整脱敏 headers/body/status/hash。
- HTTP 200 + 业务错误和 HTTP 200 + EMPTY 均保存原始业务码/message，并具有不同 outcome。
- JSON 解析失败保存原始完整脱敏正文，不被空字符串替代。
- timeout/connect error 保存完整请求证据和无响应状态。
- 同一请求重试生成新 exchange，不覆盖旧记录，可比较 body hash 和 HMAC 指纹。
- Secret、Cookie、Token、动态签名和个人信息扫描无明文命中。
- required 模式证据写入失败时 Provider fail-closed，且错误可见。
- 旧 `flight_raw_snapshots` 和 `flight_canonical_offers` 数据仍可读取。

## 9. 建议验证

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_data_sources.py -q
npm --prefix browser_worker test
npm --prefix browser_worker run typecheck
.\.venv\Scripts\python scripts/export_flight_exchange.py --exchange-id <fixture-id>
git diff --check
```

真实 smoke 只允许一次低频批准来源查询；测试 429/WAF/业务错误优先使用 fixture，不重复触发官网风控。

## 10. 非目标

- 不记录或还原明文 Cookie、Token、设备指纹、动态签名。
- 不新增管理后台或公网日志下载接口。
- 不改变航班推荐、价格或外部 API schema。
- 不通过保存证据绕过验证码、WAF 或限流。
