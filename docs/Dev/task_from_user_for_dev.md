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

## 开发任务：Codex Task Dock 桌面开发任务工具

- 日期：2026-08-14。
- 用户需求：实现与旅行业务无关的浅色桌面任务工具，停靠在 Codex 左侧并随窗口尺寸自适应；自动读取开发任务、逐条交给 Codex、用状态灯反映真实代码、支持单任务 Revert 与删除。
- 用户确认：采用方案 B，不提供添加任务入口；每 3 秒从 `docs/Dev/task*.md` 同步，并避免每轮遍历或重读全部文件。
- 完成状态：已完成。
- 实现位置：`tools/codex-task-dock/`。
- 核心结果：目录 mtime 与已知文件 stat 增量策略、隔离 worktree、独立 binary patch、Git 正反向校验状态、受保护的 Revert 与任务源删除、顺序执行的“一键开发全部”队列、Win32 自适应停靠、浅色焦点任务界面。
- 业务隔离：未修改旅行 API、数据库、业务服务或前端业务页面。

## 2026-07-19 — 完成全部常驻浏览器航司任务

- 用户要求：所有任务都要开发完成，不接受只完成东航代码基线。
- 已继续完成：东航真实结果页与含税 DOM、独立 Edge Chromium worker、loopback API、总超时取消、官方风险响应识别、page/context/browser 分级恢复测试、按航司比率与 cold/warm 延迟指标、无缓存伪成功的 50 次验收工具。
- 当前门禁：首批前 5 次成功后连续 3 次超时；第二批按 10 秒额外间隔仍连续 3 次超时并自动停止，可见浏览器同样无法完成结果页。东航官方条款未授予自动化查询与数据复用许可。
- 未完成原因：架构任务明确要求东航先达到 50 次、≥95% 成功率及许可门禁，再依次实现 CA/CZ/ZH/HO/SC。当前不得伪造验收、许可或越过 Phase 1 门禁批量启用 Phase 2。

## 2026-08-21 — iOS 上线第一阶段配置

- 用户需求：优先上线 iOS，执行第一阶段 App 身份、图标与 EAS 发布配置。
- 状态：已完成。
- 实现：
  - 新增 iOS Bundle ID `com.chuxingdazi.app`、构建号、竖屏和 iPhone-only 配置。
  - 新增原创高分辨率正方形 App Store 图标并纳入 Expo 资产，构建时由 Expo 生成所需的 iOS icon set。
  - 新增 EAS `preview` / `production` iOS 构建与 production submit profile。
  - 生产 API origin 改为由 EAS environment 注入，不在仓库内写死 localhost。
- 验收：Expo config、TypeScript、helper tests、Expo export 与 Expo Doctor。

## 2026-08-23 — 隔离 G6130 并继续铁路时刻导入

- 用户需求：先隔离阻塞导入的 G6130，记录该车次时刻，然后从现有 checkpoint 继续导入后续车次。
- 完成状态：已完成并启动低频单线程续跑。
- 实现：新增“额外停站无法唯一对账”专用异常；导入器只隔离命中该异常的单一服务，从可激活发现集合及完整性计数中移除，同时保留车次、服务日、始发终到站、始发终到时间、发现/详情站数与 UTC 隔离时间。
- 实际记录：2026-09-02 G6130，深圳北 18:22 发、长沙南 21:52 到；发现摘要 5 站，详情返回 8 站，隔离原因 `AMBIGUOUS_EXTRA_STOPS`。
- 续跑结果：从 7,347 趟 checkpoint 恢复后，G6130 已写入隔离区，后续车次已继续写入 STAGING 批次，未再次在 G6130 失败。
- 代码提交：`2c24bcf`。
- 验证：铁路定向测试 24 passed；后端全量测试 301 passed；真实 checkpoint 与 SQLite STAGING 计数均已越过原故障点。

## 2026-08-31 — 建立铁路导入自动续跑机制

- 用户需求：导入跳过 G6130 后仍因后续网络传输失败退出，需要建立独立于 Codex 窗口的自动续跑机制。
- 完成状态：已完成代码、测试和 Windows 计划任务支持。
- 实现：将连接/超时/5xx 临时错误映射为独立退出码 3；启用 `--auto-resume-transient` 后按 5、10、20、40、60、60 分钟最多 resume 6 次。每次复用 checkpoint，并从最后完成车次继续。
- 安全边界：访问控制退出码 2 和确定性错误退出码 1 均立即停止；不绕过 429、验证码或安全挑战。Windows Task Scheduler 使用 `IgnoreNew` 防止重复进程。
- 本机部署：已安装并启动 `TravelPlannerRailTimetableRefresh`，每天 03:30 触发；首次运行已进入 2026-09-14 发现阶段并持续更新 checkpoint。
- 代码提交：`afb78cc`。
- 验证：铁路定向测试 29 passed；后端全量测试 306 passed；PowerShell 安装脚本语法检查和 `git diff --check` 通过。
