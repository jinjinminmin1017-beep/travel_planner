# TEST-20260722-02 航班 Provider 完整交换证据验收

来源：`docs/Dev/task_from_arc_for_dev_20260722_flight_exchange_evidence.md`。

状态：待测试。

## 1. 完整性测试

- HTTP 200 成功：请求、响应 headers/body/status/hash、业务 outcome 全部存在。
- HTTP 200 空结果：完整保存业务码和 message，outcome 为 EMPTY。
- HTTP 200 业务错误：完整保存响应，outcome 为 BUSINESS_ERROR。
- HTTP 429/403/5xx：抛出业务异常后仍能通过 exchange_id 导出完整脱敏响应。
- 非 JSON/非法 JSON：保存完整脱敏原文，parse error 不覆盖证据。
- timeout/connect error：保存请求和异常，无伪造响应正文。
- 多阶段海航/青岛航空请求：每阶段独立 exchange，可由 request/correlation id 关联。

## 2. 顺序测试

- mock `save_response()`，证明其调用发生在风险检查、`raise_for_status()`、业务码判断和 parser 之前。
- evidence 写入失败且 required=true：Provider 不返回 offer，错误码为 `FLIGHT_EVIDENCE_PERSISTENCE_FAILED`。
- required=false 仅限明确测试配置；必须产生高优先级结构化告警，不得无记录继续。

## 3. 脱敏测试

- Authorization、Cookie、Set-Cookie、token、signature、device、手机号和身份证样本不以明文出现。
- 被脱敏字段仍保留字段名、类型、长度和 HMAC 指纹。
- 同一 Secret 使用同一 key 得到相同指纹，不同 Secret 不同；更换 key 后指纹改变。
- JSON、表单、URL query、HTML、纯文本和未知 Content-Type 均覆盖。
- 导出器二次扫描发现疑似 Secret 时拒绝导出。

## 4. 数据库与生命周期

- 新表和索引可在已有 `flight_harvest.sqlite3` 上增量创建，旧表数据不变。
- 正文压缩后可无损还原完整脱敏内容；大响应不被截断。
- 并发写入启用 WAL/busy timeout，不出现部分 exchange。
- 清理只删除 `expires_at` 之前记录，分批执行，不影响未过期和 canonical offers。
- 重试生成新 exchange_id，不覆盖第一次响应，可比较原始 body hash。

## 5. 回归与安全

- 春秋、海航、青岛航空成功/空结果/失败语义回归通过。
- 浏览器 worker 不把 Cookie、Token、设备材料传入普通日志或外部 API。
- 导出 CLI 不接受任意路径写出仓库外敏感原文，不提供 HTTP 下载。
- `logs/`、证据导出和真实 `.env` 保持 git ignored。

## 6. 建议执行

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_data_sources.py -q
npm --prefix browser_worker test
npm --prefix browser_worker run typecheck
git diff --check
```

## 7. 通过标准

- 所有自动测试通过。
- 使用 fixture 完成 200/EMPTY/429/WAF/非法 JSON/timeout 六类证据导出，并逐字段核对。
- 任一敏感明文、响应截断、异常先于证据写入或旧 exchange 被覆盖均判定失败。
