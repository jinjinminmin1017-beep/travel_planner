# 架构测试任务（2026-07-26）

## ARC-TEST-20260726-01 异步规划假空态与渐进结果测试

来源：`docs/ARCHITECTURE.md`“异步规划假空态与渐进结果架构”。

完成状态：待测试；P0 回归必须在修复代码合入前先失败、合入后通过。

### 历史回归锚点

- `067b127`：覆盖 100 次轮询耗尽但服务端仍为 RUNNING 的场景。
- `b6c9a9b`：覆盖“error 非空且 response 存在”不能简单等价于“已有可用结果”。
- `7603cf3`、`1e4413f`、`c894873`、`03c8232`：覆盖真实地图/多航司串行耗时超过旧观察窗口时，前端仍保持正确状态。
- 测试目标是锁定状态语义，不要求回滚上述真实数据功能。

### 前端状态矩阵

- `RUNNING + WAITING_SOURCE + plans=[]` 只能显示规划中。
- `RUNNING + WAITING_SOURCE + plans非空` 显示真实结果与局部 loading。
- 本地观察窗口耗尽只显示“仍在规划/继续获取”，保留 job，不显示普通空态或系统失败。
- `RUNNING + plans=[] + error非空` 不得进入 `EmptyResults`。
- `COMPLETE/PARTIAL + plans非空 + 局部重试error` 必须保留结果并显示非阻断 error panel。
- `NO_MATCH + COMPLETE` 显示约束无匹配页面。
- `FAILED + FAILED` 显示失败与重试页面。
- `COMPLETE/PARTIAL + plans非空` 显示正常结果；选中计划仍存在时保持选择。

### 确定性超时回归

- 使用 fake timers/mock API 模拟第 100 次轮询后任务仍在运行、第 101 次读取变为 COMPLETE；测试不得真实等待 120 秒。
- 该测试必须调用抽出的状态机/轮询 helper 并断言页面状态，不得只用正则检查源码中存在某段字符串。
- 断言观察暂停后不会创建第二个 job；点击继续获取或 App 前台恢复只 GET 原 polling URL。
- 单次轮询网络失败保留最后快照和重试能力，不清空已有 plans。
- 取消与新建任务后，旧轮询响应不能覆盖当前 run。
- 只把 MAX poll 次数改大时，上述测试仍应能证明活动态不会被解释为空态。

### 后端渐进快照

- 首个铁路完整计划通过门禁后，job GET 返回 `RUNNING` 且 plans 非空、推荐为空。
- 后续航班结果扩充同一 job；progress 和 updated_at 单调前进。
- 未完成接驳、核心事实缺失、安全门禁失败和规则估算计划不能进入渐进 plans。
- 最终候选筛选与推荐覆盖渐进快照，终态计划集合符合既有排序与约束规则。
- 取消/重试 race 下，旧 generation 写入被拒绝，终态不可被 RUNNING 覆盖。
- 后端异步测试不得依赖 TestClient 自动执行完 BackgroundTasks 后立即得到终态；使用受控 progress sink/store 或同步屏障保留可断言的中间 RUNNING 快照。

### 服务端期限

- 观测模式只记录 would-timeout，不改变响应。
- 强制期限到达时：已有完整计划返回 PARTIAL；没有完整计划返回 FAILED 和稳定说明。
- Provider 单次 timeout 不得超过剩余总预算；期限判断使用单调时钟。
- 当前约 144 秒成功样例在未校准前不得被 30 秒默认值直接截断。

### 性能与回归

- 记录首个可用计划与最终结果两个延迟，确认指标值非负且前者不晚于后者。
- 对 Provider 使用计数 fake：相同 `起点坐标 + 终点坐标 + mode + Provider` 在同一规划任务中只调用一次，不因多个同站计划或渐进发布重复查询。
- 使用本次结构规模（4 个铁路计划、2 个航班计划、两端接驳、四种方式）构造回归；外部地图调用数必须等于唯一路线键数，而不是计划笛卡尔积数量。
- 至少增加一个慢 Provider 集成测试：首个计划在观察窗口内生成、最终结果在窗口后生成，验证渐进快照与最终结果均可取得。
- 执行：
  - `python -m pytest backend/app/tests`
  - `npm run typecheck`（`frontend/`）
  - `npm run test:helpers`（`frontend/`）
  - `python scripts/export_schemas.py` 并检查 schema diff
- 现有同步规划、NO_MATCH、重试、取消、交通方式入口和推荐结果不得回归。
