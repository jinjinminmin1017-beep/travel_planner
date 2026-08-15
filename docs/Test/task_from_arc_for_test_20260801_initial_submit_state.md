# 架构测试任务（2026-08-01）

## ARC-TEST-20260801-01 首次规划启动态回归

来源：`docs/ARCHITECTURE.md`“首次提交到异步任务响应之间的启动态架构”。

完成状态：待测试。

### 纯状态机矩阵

- `response=null + client phase=SUBMITTING + no error` -> `SUBMITTING`。
- `response=null + client phase=IDLE + no error` -> `IDLE`。
- `response=null + client phase=SUBMITTING + blocking error` -> `BLOCKING_ERROR`。
- RUNNING 空计划、RUNNING 有计划、PAUSED、NO_MATCH、FAILED、COMPLETE/PARTIAL 有计划保持现有结果，不因新增启动态回归。
- 状态矩阵应直接调用纯函数断言，不接受只用正则检查源码字符串。

### 可控 Promise 交互回归

1. 将 `planTripAsync()` 替换为未 resolve 的 deferred Promise。
2. 输入完整行程并点击“开始规划”。
3. 在 Promise 仍 pending 时断言：
   - 已离开输入页；
   - 显示“正在理解你的行程”或批准的等价启动文案；
   - 不显示“还没有规划结果”“去云起”“请输入目的地”或普通空结果；
   - 不存在伪造的结构化起点、目的地和进度。
4. resolve 为 RUNNING job 后断言使用响应中的真实 `travel_request` 并进入现有规划态。
5. resolve 为 COMPLETE/PARTIAL/NO_MATCH/FAILED 时断言直接进入对应服务端终态，不经过 IDLE。
6. reject 时断言进入 blocking error、保留原始输入，编辑和重试入口可用。

### 并发与保留结果

- 构造两个不同 run，使第一个 Promise 最后返回；断言旧结果不能覆盖第二个 run。
- 对 `preserveCurrentResults=true` 场景，断言旧结果在初始 POST pending 时仍可见，只显示局部 busy，不出现全屏首次启动态。
- 连续点击不应创建可同时覆盖页面的重复会话；至少验证按钮 busy/disabled 与 runId 防护。

### 可访问性与文案

- 启动态包含可识别的进行中语义；屏幕阅读器不会把它读成未填写错误。
- 原始输入摘要需要限制显示长度；不得写入新增日志、持久化或事件 metadata。
- 起点/目的地在服务端响应前只用中性说明，不做客户端自然语言解析。

### 执行

```powershell
cd frontend
npm run typecheck
npm run test:helpers
npm run build
```

结果要求：全部通过；现有规划状态机、观察暂停、取消、重试、NO_MATCH 和渐进结果用例无回归。
