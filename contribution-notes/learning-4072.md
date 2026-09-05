# 修复学习总结：#4072

## 修复概况

- 候选名称：#4072 restricted `ExecTool` 可通过相对符号链接逃逸工作区
- 候选评分：80+ 候选（本地工作树未保留审计时的精确分数）
- 技术正确性信心：94/100
- 合并信心：84/100
- 本地 commit：包含本笔记的本地 commit
- 是否已推送：否
- 影响入口：`ExecTool._prepare_command()`、workspace restriction、exec sandbox 配置
- 验证命令与结果：
  - `uv run --no-sync pytest tests/tools/test_exec_security.py tests/tools/test_exec_platform.py tests/tools/test_exec_session_tools.py tests/agent/test_workspace_scope.py -q` — 177 passed, 10 skipped
  - `uv run --no-sync ruff check nanobot/agent/tools/shell.py tests/tools/test_exec_security.py tests/tools/test_exec_platform.py tests/agent/test_workspace_scope.py` — passed

## 问题与根因

- 用户或系统观察到的失败：受限工作区内的 `cat link.txt` 可以跟随指向工作区外部文件的相对符号链接；旧实现只检查命令文本中提取出的绝对路径。
- 触发条件：`restrict_to_workspace=True`、没有 OS 级 sandbox，且 shell 命令通过相对路径、shell 展开或符号链接访问文件。
- 根因：shell 命令在执行前可能经过变量展开、命令替换和 symlink traversal；静态字符串解析无法证明最终访问路径。
- 违反的 invariant、契约或生命周期规则：workspace restriction 应是不可绕过的访问边界，而不是只对少数命令写法有效的提示性检查。
- 为什么已有测试没有发现：已有测试覆盖绝对路径、命令替换和直接 guard 函数，但没有把相对符号链接放入真实执行路径；同时旧文档允许无 sandbox 时继续运行 native shell。

## 值得学习的实现点

### 当前语言/框架

Python 的 `pathlib.Path.resolve()` 能解析单个路径，但不能替代 shell 的完整语义分析。这里的关键不是再增加一个正则，而是在异步 subprocess 启动前建立明确的 policy gate：有效 workspace restriction 必须有 bwrap 或明确标记的外部 sandbox，否则返回错误，不创建进程。已有的 best-effort guard 仍先运行，以保留 deny/SSRF 错误的可观测性；只有 guard 放行后才进入 fail-closed 检查。

### Java 对照

Java 服务中对应的是在 `ProcessBuilder.start()` 前检查 capability/policy，而不是尝试解析任意 shell 字符串。若需要边界，应使用容器、namespace、`ProcessHandle` 所属的外部执行器或专门的 sandbox；`Path.normalize()`/`toRealPath()` 只能帮助处理应用自己的路径参数，不能证明 `sh -c` 内部的所有访问都受控。Windows 的 unsupported backend 也应拒绝启动，而不是记录 warning 后降级执行。

## 软件工程与架构启示

- 哪个模块应该拥有这个状态或责任：`ExecTool` 拥有命令启动前的执行策略；sandbox backend 拥有进程隔离实现；workspace resolver 只提供有效 workspace scope。
- 哪个 invariant 应该在边界处被保护：任何 effective restricted shell command 在 subprocess 创建前必须已经处于 OS 级或显式外部 sandbox 边界内。
- 这是权限边界和 fail-safe/fail-closed 问题，也涉及平台能力声明；不是单纯的路径格式问题。
- 测试从“guard 返回值”扩展到了真实 `execute()` 入口，并同时覆盖相对 symlink、无 sandbox、Windows bwrap fallback 和 Full Access 行为。
- 轻量修复只增加一个启动前 policy gate，没有重写 shell parser，也没有引入新的 sandbox 抽象，复杂度与安全收益匹配。
- 更大系统可能使用 seccomp、容器运行时、Windows Job/AppContainer 或独立 command broker；nanobot 目前只需要把现有 bwrap/外部 sandbox 的契约落实到入口。

## 面试表达

### 60 秒版本

问题是 restricted `ExecTool` 通过字符串扫描检查绝对路径，但 `cat link.txt` 这种相对路径会由 shell 解析并跟随工作区外的 symlink，导致应用层检查不是可靠边界。根因是我们试图用命令文本证明任意 shell 行为的文件访问范围。修复是在 subprocess 启动前增加 fail-closed gate：只要 effective workspace access 是 restricted，就必须使用 Linux bwrap 或明确标记的外部 OS sandbox；Windows 上配置 bwrap 也不再降级为 native shell。原有 deny/SSRF guard 仍保留并先执行。测试覆盖了真实执行入口、相对 symlink、平台 fallback、scope cwd，并同步更新安全文档。取舍是没有 sandbox 的 restricted exec 会停止工作，但这是为了避免把 best-effort 检查误当成安全隔离。

### 可能追问

1. 追问：为什么不继续完善 `_extract_absolute_paths()`？
   回答：shell 有变量、命令替换、重定向、工作目录变化和 TOCTOU；继续补 parser 只能扩大覆盖率，不能证明完整安全性。安全边界应交给 OS sandbox。

2. 追问：为什么先执行原有 guard 再 fail closed？
   回答：这样已知的 deny pattern/SSRF 仍能返回具体、可观测的错误；guard 放行后仍绝不允许无 sandbox 的 restricted command 启动。

3. 追问：为什么 Windows 配置 bwrap 要拒绝而不是兼容？
   回答：bwrap 依赖 Linux namespace。继续执行会让用户以为有隔离但实际上没有，安全上属于危险降级；明确拒绝更符合 fail-closed 契约。

### 诚实边界

- 已证明的性质：当前 Python 入口在无可用 sandbox 时不会为 effective restricted access 创建 subprocess；相对 symlink 回归测试在支持 symlink 的平台上不会读出外部内容。
- 尚未证明或仍存在的限制：本地 Windows 无法运行 POSIX symlink 用例；bwrap 的真正隔离能力仍依赖主机 kernel、安装状态和外部容器策略；Full Access 本身不是 sandbox。
- 如果重做，最可能调整的地方：将“外部 sandbox 已 enforced”的能力探测进一步集中到 workspace policy 对象，避免 ExecTool 直接读取环境标记。

## 复盘

- 这次最容易误判的点：看起来只需修正相对路径扫描，但那会把安全边界继续绑定在不完整的 shell parser 上。
- 下次审查应优先检查什么：任何 `shell=True`、脚本解释器、插件执行器是否把应用层路径检查误当作进程隔离；先确认 fail-open/fail-closed 契约。
- 是否需要新增回归测试、文档或候选评分规则：需要真实入口失败路径测试，并且文档必须明确无 sandbox 时 restricted exec 的行为；候选评分应提高“安全边界是否可证明”权重。
