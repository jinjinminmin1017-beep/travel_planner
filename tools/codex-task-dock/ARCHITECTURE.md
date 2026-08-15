# Task Dock 技术结构

```text
docs/Dev/task*.md
        |
        v
IncrementalTaskScanner  <3 秒元数据轮询>
        |
        v
Local HTTP API  <127.0.0.1 + 会话令牌>
        |
        v
Edge App Panel  <Win32 跟随 Codex 窗口>

任务点击 -> 临时 Git worktree -> codex exec -> 独立 binary patch
                                      |
当前仓库 <- git apply 校验并应用 <--------+
当前仓库 -> reverse check -> 状态灯 / Revert
```

服务端只使用 Python 标准库。状态与补丁按仓库路径哈希隔离存放在 LocalAppData。前端不直接访问文件或执行命令，所有变更动作都需要启动时生成的随机会话令牌。
