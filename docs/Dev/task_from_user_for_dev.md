## 2026-07-15 — Official airline anonymous-query verification

- User request: real anonymous sampling -> redacted request/response evidence -> independent airline contracts -> CAPTCHA/rate-limit checks -> terms approval -> continuous smoke.
- Implemented:
  - Saved redacted MU/CZ/SC browser evidence under `docs/flight_provider_evidence/2026-07-15/`.
  - Added three independent, fail-closed contract records; removed the guessed shared `/api/flight/search` default.
  - Added snapshot credential/token redaction, request-key fingerprinting, CAPTCHA fail-closed detection and explicit HTTP 429 handling.
  - Added repeated gate/live smoke runner.
- Governance result: `PENDING_REVIEW`, not approved. Browser access was verified, but no airline published automation license or documented server endpoint contract was found. Live server-provider smoke remains correctly blocked; safety-gate smoke is executable.

## 2026-07-15 — Expand official airlines and license-only activation

- User request: expand beyond three airlines and finish every preceding validation so activation only requires changing `LICENSE_STATUS`.
- Implemented:
  - Expanded the registry to 10 independent official-query systems covering 16 carrier codes.
  - Added per-source official host, known transport, request/response field evidence, dynamic-material, CAPTCHA/risk and technical-blocker records.
  - Added license-only activation ergonomics: changing a source to `LICENSE_STATUS=APPROVED` automatically enables it at 1 QPS unless an explicit enable/QPS override exists.
  - Added redacted HO, SC, HNA-micro and QW transport/contract evidence plus repeated safety-gate smoke across all 10 sources.
- Status: engineering configuration and fail-closed gates completed; external technical/legal prerequisites remain blocked. No source is marked executable because no source currently has both a replayable anonymous flight-level fare/cabin/availability response and affirmative automation/data-reuse approval. `LICENSE_STATUS` cannot override those facts.

## 2026-07-19 — 完成全部常驻浏览器航司任务

- 用户要求：所有任务都要开发完成，不接受只完成东航代码基线。
- 已继续完成：东航真实结果页与含税 DOM、独立 Edge Chromium worker、loopback API、总超时取消、官方风险响应识别、page/context/browser 分级恢复测试、按航司比率与 cold/warm 延迟指标、无缓存伪成功的 50 次验收工具。
- 当前门禁：首批前 5 次成功后连续 3 次超时；第二批按 10 秒额外间隔仍连续 3 次超时并自动停止，可见浏览器同样无法完成结果页。东航官方条款未授予自动化查询与数据复用许可。
- 未完成原因：架构任务明确要求东航先达到 50 次、≥95% 成功率及许可门禁，再依次实现 CA/CZ/ZH/HO/SC。当前不得伪造验收、许可或越过 Phase 1 门禁批量启用 Phase 2。
