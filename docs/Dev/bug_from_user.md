## 2026-07-14 真实规划任务因高德公交空费用失败

- 用户提问时间：2026-07-14。
- 问题描述：异步规划任务 `job_65889cd392e0` 在铁路、地点和出租车事实已成功返回后仍进入通用 `FAILED`；高德公交/地铁响应中的 `transits[0].cost` 为 `[]`。
- 问题根因：`AmapRouteProvider._parse_payload()` 将空数组交给 `_yuan_to_money()`，旧实现通过 `float(value)` 转换金额并触发未捕获的 `TypeError`；地图 Provider 调度边界未隔离该字段类型异常。
- 解决方式：金额转换改为严格的 `Decimal` 解析；空费用表达为未知并保留真实距离、时长和步行距离；非法结构返回 `MAP_ROUTE_RESPONSE_INVALID`；Provider 边界捕获字段转换异常并继续后备 Provider，单一接驳方式失败不再中断其他方式或异步规划任务；新增完整回归测试与日志脱敏断言。
- 问题修改提交：`5da3564859b66e1d33c7f0ffab4dbc878bb52f81`。

## 2026-07-14 席别调整错误传播到不同车次

- 用户提问时间：2026-07-14。
- 问题描述：只有一个中转方案时，在 K597 选择硬座后，系统因为同一方案的 G834 不提供硬座而提示“1个方案不提供该席别”；业务预期是多个方案包含同一车次时同步该车次席别，不同车次互不影响。
- 问题根因：结果集席别传播器以“计划中的全部铁路段”为应用范围，并把车次级选择写入全局 `TravelRequest.preferred_rail_seat`，导致同一方案内其他车次和结果集内不同车次被错误要求提供同一席别。
- 解决方式：传播键改为规范化 `train_number`；只更新结果集中同车次铁路段并使用各段自己的合法 option_id 和价格；不同车次保持原席别与推荐资格；不再改写全局铁路席别偏好；补充同车次跨方案及 G834 + K597 回归测试。
- 问题修改提交：`a8c9c91a786e12969eb177926beb1a0df8e92ccd`。

## 2026-07-24 春秋官网有航班但规划结果没有航班选项

- 用户提问时间：2026-07-24。
- 问题描述：上海嘉定格林公馆到大连海事大学的规划任务 `job_2905e377ffef` / `req_1665ef7e5c04` 只返回铁路方案；春秋公开查询实际返回 9C8843、9C8977、9C7157、9C8981 四个 `PVG -> DLC` 航班。
- 问题根因：春秋请求使用 `SHA` 表达上海城市范围，但解析器把响应实际起飞机场 `PVG` 与请求城市码 `SHA` 做严格机场相等比较，导致合法航班全部被丢弃并误报 `FLIGHT_PROVIDER_EMPTY`；机场目录又在 top-N 前保留无 IATA 的重复虹桥种子，Planner 仍按查询候选而非响应实际机场构建接驳。
- 解决方式：新增城市/机场查询范围模型并固定 Provider scope；分离城市码、允许机场集合和响应实际机场；机场目录先按 IATA canonical 化再排序；非空候选零 offer 返回 `FLIGHT_PARSER_REJECTED_ALL`；Planner 按每个航段实际机场生成首末程及跨机场接驳，无法验证实际机场或接驳时 fail-closed；新增四航班脱敏 fixture 与门到门回归测试。
- 问题修改提交：`03c82326075fd54714318b5921f95a8a03f408d8`。

## 2026-07-26 后端已有方案但前端显示“暂无可用方案”

- 用户提问时间：2026-07-26。
- 问题描述：真实异步请求的客户端约 120 秒观察窗口先结束，后端约 144 秒完成并持久化 6 个方案；客户端保留 `RUNNING + plans=[]` 中间快照，却显示终态“暂无可用方案”。
- 问题根因：前端固定轮询 100 次后停止，并以 `plans.length === 0` 独立推导空态；后端只在全部 Provider 与 LLM 完成后保存最终快照，已形成的完整铁路方案没有渐进发布；同一规划重复地点和地图路线请求又放大了最终延迟；声明的服务端超时配置没有进入执行链路。
- 解决方式：前端新增单一规划状态机和 `OBSERVATION_PAUSED`，继续获取/前台恢复复用原 job；后端新增安全门禁后的渐进快照与 generation 比较写入；规划内复用地点/路线并有界并行铁路和航班族；新增首方案/最终结果指标；服务端期限先观察、再允许显式强制，强制到期保留完整方案为 `PARTIAL`。
- 问题修改提交：`92d7e08`、`e2043c9`、`0e66dd2`、`17c3748`。

## 2026-08-02 真机调试行程规划因 FlyAI CLI 无法启动而失败

- 用户提问时间：2026-08-02。
- 问题描述：真机调试中的上海格林公馆到温州永嘉梨村规划连续失败；所有铁路、航班和混合方案均返回 `FLIGGY_EXECUTION_FAILED`，没有形成可验证计划。
- 问题根因：Windows 启动配置指向无扩展名的 `node_modules/.bin/flyai` POSIX shim，Python `subprocess.run(shell=False)` 无法执行该文件并返回 `FileNotFoundError / WinError 2`；同目录的 Windows `flyai.cmd` 可以启动。
- 解决方式：在 `scripts/device-debug.ps1` 启动后端前默认启用 FlyAI，把 `node_modules\.bin\flyai.cmd` 的绝对路径写入子进程环境并校验固定依赖存在；保留 `-SkipFlyAI` 回退开关。
- 问题修改提交：`3a272a7`。

## 2026-08-02 真机调试行程规划因 FlyAI CLI 异常退出而失败

- 用户提问时间：2026-08-02。
- 问题描述：修复 CLI 启动路径后再次规划上海格林公馆到江苏宜兴，异步任务 `job_4860d87f88f9` 最终为 `FAILED`，方案数为 0。
- 直接根因：当前 Windows 10、Node 24.14.0、`@fly-ai/flyai-cli@1.0.16` 组合中，航班和铁路命令均以 `3221226505` 异常退出；后端按严格门禁拒绝非零退出进程的 stdout，因此没有可验证票务事实。
- 放大因素：一次请求累计 33 次同类 FlyAI 失败，缺少 job/source 级确定性崩溃熔断；数据源状态接口仍按静态配置把 FlyAI 显示为 OK 并伪造当前时间为最近成功时间。
- 架构结论：不能忽略非零退出；需优先修复 CLI 成功路径的强制退出竞态，再增加启动 readiness、运行时健康状态和来源级熔断。切换 Node/OS 仅作为诊断或临时规避手段，不再作为首要修复。
- 任务文档：`docs/Dev/task_from_arc_for_dev_20260802_flyai_windows_runtime.md`、`docs/Test/task_from_arc_for_test_20260802_flyai_windows_runtime.md`。
- 状态：代码修复完成；目标环境 50+50 在线发布门禁未通过。

### Core dump 补充结论

- 2026-08-02 23:58 使用无 Key 最小铁路查询和 ProcDump 捕获了同码 full dump；无 Key 与正式请求均为 `0xC0000409`，排除 API Key 为直接原因。
- stderr：`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c, line 76`。
- 崩溃线程：`V8Worker -> WebAssembly BackgroundCompileJob -> NodePlatform::PostDelayedTaskOnWorkerThreadImpl -> DelayedTaskScheduler::PostDelayedTask -> uv_async_send -> abort`。
- 同时主线程：`ReallyExit -> Environment::Exit -> DefaultProcessExitHandler -> NodePlatform::Shutdown -> WorkerThreadsTaskRunner::Shutdown -> uv_thread_join`。
- CLI bundle 已确认航班、铁路成功分支在输出 JSON 后直接调用 `process.exit(0)`；该强制退出与尚未完成的 V8 background compile 形成 shutdown race，是直接根因。
- 更正方案：优先由 FlyAI 上游把成功路径改为设置 `process.exitCode=0` 并返回、等待自然排空；环境兼容矩阵降为验证手段，不再作为第一根因修复。
- 解决方式：对固定 `@fly-ai/flyai-cli@1.0.16`、官方 bundle SHA 和补丁后 SHA 实施构建期精确补丁；认证 Windows runtime 直接以 Node `--single-threaded` 无 shell 参数数组执行 patched bundle；真机启动前增加 bundle 校验与航班/铁路 readiness。后端新增 fatal/ordinary exit、stderr、timeout、rate limit、business/JSON 分类，共享来源级立即/阈值熔断、短冷却、半开恢复和真实 runtime health registry。
- 问题修改提交：`2d632d7`、`526bbca`。
- 修复验证：真实 readiness 曾完成航班、铁路 exit 0；100 次在线低频门禁未再出现 `3221226505`，证明 fatal shutdown race 已消除。门禁仍因 16 次上游普通 exit 1、1 次业务错误及随后的 36 次保护性熔断而失败；门禁后再次 readiness 被普通 exit 1 正确阻止，当前不得发布为稳定真实票务环境。

## 2026-08-05 铁路时刻表详情因稀疏站序无法入库

- 用户提问时间：2026-08-05。
- 问题描述：首次 15 天铁路时刻表建库完成 2026-08-04 的 9857 趟车发现后，详情导入在第 17 趟 C1017 失败，批次状态为 FAILED，错误为 `stop_sequence must be contiguous and start at 1`。
- 问题根因：12306 `queryTrainInfo` 对部分车次保留父级服务的稀疏 `station_no`；C1017 的两行有效响应实际为 `01、07`。解析器直接把来源序号写入本地 `stop_sequence`，与本地表要求的相对、连续、从 1 开始的站序冲突。
- 解决方式：仍严格保留 12306 返回的行顺序，但把本地 `stop_sequence` 规范化为响应内从 1 开始的连续序号；不补造缺失停站，不放宽服务数、时间或批次完整性门禁；增加 `01、07 -> 1、2` 回归测试。
- 问题修改提交：`a8c7081`。
- 验证：真实 C1017 低频诊断请求 HTTP 200，并确认来源站序为 `01、07`；后端全量测试 290 passed。

## 2026-08-05 铁路终到站伪发车时间破坏时间单调性

- 用户提问时间：2026-08-05。
- 问题描述：稀疏站序修复后，bootstrap 在第 79 趟 C119 再次形成 FAILED 批次，错误为 `departure cannot precede the previous service event`。
- 问题根因：12306 对 C119 终到站香格里拉返回到达 `14:25`，同时残留 `start_time=14:24`；终到站不存在下一程发车，该字段是来源噪声，不应成为本地运行图事实。
- 解决方式：按服务边界把首站 arrival 和末站 departure 固定归一为空；中间站到发时间、day offset 和全程时间单调门禁保持严格，不吞掉中间站异常。
- 问题修改提交：`7b4022a`。
- 验证：真实 C119 低频诊断请求 HTTP 200，并确认终到站来源字段冲突；新增终到站伪发车回归，后端全量测试 290 passed。

## 2026-08-05 铁路详情包含本地目录缺失的新站点

- 用户提问时间：2026-08-05。
- 问题描述：bootstrap 详情推进至 139 趟后，遇到 `station code missing for timetable stop: 西安东` 并形成 FAILED 批次。
- 问题根因：仓库内 12306 站点目录快照早于西安东站收录时间；详情响应只提供站名，本地解析严格要求当前官方 telecode，因此拒绝猜测或写入空站码。
- 解决方式：使用项目既有 `scripts/import_transport_nodes.py --skip-airports` 从官方当前 `station_name.js` 刷新铁路站点目录，保留内部种子和机场数据；西安东解析为官方 telecode `XDY`。
- 问题修改提交：`5bfecb3`。
- 验证：更新后目录含 3397 个铁路站点；目录/地点/铁路定向测试 31 passed，后端全量测试 291 passed。

## 2026-08-05 铁路中间站跨午夜停站被误判为时间倒序

- 用户提问时间：2026-08-05。
- 问题描述：首次 15 天 bootstrap 推进至 2530 趟详情后，D10 在南京站触发 `departure cannot precede the previous service event`，当前批次按门禁进入 FAILED，未激活不完整数据。
- 问题根因：12306 返回南京站到达 `23:56`、出发 `00:02`，行内 `arrive_day_diff=0` 只描述到达事件且没有独立出发日字段；解析器错误地把到达、出发都赋为第 0 天，忽略了停站期间跨午夜。
- 解决方式：中间站到发时间均存在且出发时钟早于到达时钟时，仅把该站出发日偏移增加 1；跨站全程单调门禁、首末站边界和批次完整性门禁保持严格。
- 问题修改提交：`a0402c8`。
- 验证：真实 D10 低频诊断请求 HTTP 200，确认南京站原始字段为 `23:56 / 00:02 / arrive_day_diff=0`；铁路定向测试 14 passed；后端全量测试首次为 290 passed、1 个无关异步规划用例失败，单独重跑该用例 1 passed；Python compileall 与 `git diff --check` 通过。

## 2026-08-05 Bootstrap resume 重复处理已激活日期

- 用户提问时间：2026-08-05。
- 问题描述：2026-08-04 已成为含 9857 趟车的 ACTIVE 批次；次日发现遇到访问控制并冷却后，整窗 `--resume` 从窗口首日重新进入详情流程，产生新的 STAGING 批次并重复请求 51 趟首日详情。
- 问题根因：`_resume_or_begin_batch()` 只识别 STAGING 和 FAILED checkpoint 批次，没有把 SQLite 中已经 ACTIVE 的服务日视为 bootstrap 的终态；它创建新批次并清空 checkpoint 的完成集合，导致从首趟重新抓取。
- 解决方式：非 refresh 的 bootstrap resume 在任何发现或详情网络调用前，以 SQLite ACTIVE 批次为权威；命中后修复 checkpoint 的 batch、状态、计数和完成集合，直接返回并继续下一服务日。Refresh 模式仍会按原设计刷新 ACTIVE 日期。
- 问题修改提交：`88d68c8`。
- 验证：新增损坏 checkpoint + 已有 ACTIVE 批次的零网络回归；铁路定向测试 15 passed，后端全量测试 292 passed，Python compileall 与 `git diff --check` 通过。

## 2026-08-05 铁路详情混入父级服务残留停站

- 用户提问时间：2026-08-05。
- 问题描述：次日详情导入推进至 2299 趟后，C824 在沙湾市 `16:44/16:46` 后返回石河子 `15:57/15:59`，触发 `stop times must be monotonic across the service` 并使批次进入 FAILED。
- 问题根因：发现接口声明 C824 共 3 个停站，详情接口却返回 4 行；多出的沙湾市行保留了父级服务时间。以首站出发时钟对照每行 `running_time`，该行偏差 65 分钟，而石河子和终点行均仅偏差 5 分钟。
- 解决方式：仅在详情行数超过发现计数时启动保守对账；只允许剔除中间行，并要求每个被剔除行偏差至少 30 分钟、所有保留行偏差不超过 15 分钟。证据不足或无法唯一解释时继续严格失败，不猜测站序或时刻。
- 问题修改提交：`6bd8100`。
- 验证：真实 C824 单次低频详情请求 HTTP 200，确认发现 3 站与详情 4 行的冲突及时间证据；铁路定向测试 16 passed，后端全量测试 293 passed，Python compileall 与 `git diff --check` 通过。

## 2026-08-06 Windows 短暂文件占用中断 checkpoint 原子替换

- 用户提问时间：2026-08-06。
- 问题描述：8 月 6 日详情导入推进至 5353 趟时，`rail_timetable_import_checkpoint.json.tmp -> rail_timetable_import_checkpoint.json` 的原子替换返回 `WinError 5`，当前批次进入 FAILED；异常处理的第二次保存成功，完成集合与数据库均保留 5353 趟。
- 问题根因：Windows 上读取器或安全扫描程序可短暂以不共享删除的方式持有目标文件；旧实现对单次 `os.replace` 共享冲突没有有限重试，把瞬时本地文件占用升级为整批失败。
- 解决方式：保持同一临时文件与原子替换边界，只对 `PermissionError` 最多重试 6 次并做 50～800ms 有界指数退避；持续占用、其他 I/O 错误和最终失败仍原样上抛。
- 问题修改提交：`2fae4e7`。
- 验证：新增前两次替换失败、第三次成功的回归；铁路定向测试 17 passed，后端全量测试 294 passed，Python compileall 与 `git diff --check` 通过。

## 2026-08-07 发现完成后撤回的铁路车次阻塞详情导入

- 用户提问时间：2026-08-07。
- 问题描述：8 月 10 日发现阶段完成 10089 趟车后，详情导入在第 951 趟 C4248 连续两次失败；checkpoint 记录该车临沧至昆明共 3 站，但详情接口返回 HTTP 200、业务成功且没有 `data.data`。
- 问题根因：车次发现和详情导入之间存在时间差；C4248 已从 8 月 10 日的当前精确发现结果中撤回，但完成态 checkpoint 仍保留早先发现的稳定任务键。Resume 会可靠地回到同一旧条目，因而形成确定性失败。
- 解决方式：详情不足两站时只增加一次同日期、同车次的低频精确复核；仅在复核返回 0 条时把旧条目标记为已撤回并从 checkpoint 发现集合移除。复核仍存在、身份不确定或 checkpoint 无法对账时继续失败关闭；其余服务仍必须至少两站并通过批次完整性校验。
- 问题修改提交：`d7a285c`。
- 验证：真实 C4248 详情响应无停站列表，精确发现返回 0 条；新增“确认撤回后继续”和“仍存在时失败关闭”回归，铁路定向测试 20 passed，后端全量测试 297 passed，Python compileall 与 `git diff --check` 通过。
