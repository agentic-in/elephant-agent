# Elephant Agent Sandbox 设计方案

> 融合 Hermes + OpenClaw + Issue #11
>
> 状态：Draft（review 修订版） · 2026-05-18
>
> 本版修订重点：**缩小 Phase 1 范围、保留现有工具契约、避免安全回退、把实现路径改成真正可落地的分阶段方案**。

## 一、设计结论

这版方案的核心结论是：**sandbox 应该作为执行后端层插入现有工具运行时，而不是重写现有工具 handler 的业务语义。**

具体来说：

- `ToolRuntime`、`SecurityApprovalGateway`、现有工具注册机制保持不变
- Phase 1 拆成两个可验证阶段：
  - **Phase 1A**：只沙箱化 `tool.terminal.exec` 的**前台执行路径**
  - **Phase 1B**：保留 `tool.code.execute` 的 AST 校验、`project/strict` 模式和受限 tool RPC，只把它的**子进程启动点**迁入 sandbox
- 现有 `tool.terminal.exec background=true` 和 `tool.process.manage` 继续走当前实现，放到后续阶段再统一抽象
- 环境变量清洗沿用现有的**白名单前缀 + secret 过滤**策略，不能退化成“只排除 secret 名称”
- `ApprovalClass.EXEC.required_controls=("sandbox", ...)` 仅表示**策略语义要求**，真正的 sandbox 仍需由 runtime 显式实现和验证

## 二、Issue #11 验收标准映射

| # | 验收标准 | 修订后的设计覆盖 |
|---|---------|------------------|
| 1 | 沙箱威胁模型和隔离保证已文档化 | §四 威胁模型 + §九 安全层纵深 |
| 2 | 代码执行在隔离环境中运行，明确的 I/O 路径 | **Phase 1B**：保留 `tool.code.execute` 语义，仅替换子进程运行位置；§七.2 |
| 3 | 敏感主机路径和凭证默认不被暴露 | `SecurityGuard` 的 env 白名单、敏感路径校验、默认无额外挂载；§六 |
| 4 | 强制执行资源限制和超时处理 | **Phase 1A/1B**：wall timeout、stdout/stderr 限长、文件大小/进程数/内存上限；本地后端用 `setrlimit`，容器后端用 cgroup；§七.3 |
| 5 | 测试覆盖允许/拒绝/超时/失败诊断 | §十一 测试矩阵 |

> 说明：**Issue #11 的“代码执行隔离”验收闭环以 Phase 1A + Phase 1B 合并完成为准。** 单独的 Phase 1A 只解决终端执行隔离，不单独宣称完成全部 AC。

## 三、现有实现约束

方案必须服从当前 repo 里已经存在的工具运行时契约，而不是另起一套并行语义。

### 3.1 `ToolRuntime` 的真实扩展点

当前 `ToolRuntime` 通过 registry + executor 工作；注册 builtin 工具时，会调用 executor 的 `bind()` 绑定 handler。因此 sandbox executor 不能只实现 `execute()`，还必须透明代理：

- `bind(tool_id, handler)`
- `unbind(tool_id)`
- `execute(definition, invocation)`

否则 builtin handler 不会注册成功。

### 3.2 `SecurityApprovalGateway` 只给出“需要 sandbox”的策略标签

现有安全策略里，`ApprovalClass.EXEC` 会产出 `required_controls=("sandbox", "explicit-approval")`。这说明：

- 安全策略已经把执行类工具标记为需要 sandbox
- 但这**不等价于** sandbox 已经在 runtime 中被强制执行
- sandbox 是否真的开启、在哪条执行路径上生效，必须由工具运行层显式保证

### 3.3 `tool.terminal.exec` 的现有语义不能被偷偷改掉

当前 `tool.terminal.exec` 已支持：

- `cwd`
- `env`
- `timeout_seconds`
- `background=true`
- 与 `tool.process.manage` 的联动

因此 Phase 1 不能简单把它“整体替换成一个新命令执行器”，否则会破坏现有后台进程语义。

### 3.4 `tool.code.execute` 的现有语义也必须保留

当前 `tool.code.execute` 并不是“跑一段 Python 命令”这么简单，它已经包含：

- AST 静态校验
- `project` / `strict` 两种模式
- safe import / safe builtins 限制
- 文件目录式受限 tool RPC
- 嵌套工具调用上限
- `tool.terminal.exec` 参数黑名单

因此 Phase 1B 不能通过 executor 直接拦截 `tool.code.execute` 并改写成 `env.execute(command)`。更稳妥的方式是：**保留 `run_code_execute()` 和 `_run_code_subprocess()` 的语义，只把“子进程怎么启动”抽象出来。**

## 四、威胁模型

### 4.1 保护目标

本方案要抵御的是以下几类高频风险：

- **环境泄露**：主机上的 token、credential、私密环境变量被执行面直接读取
- **路径逃逸**：命令或代码访问不应暴露的宿主路径、凭证目录或敏感挂载
- **任意外连**：执行面默认可进行不受控的网络访问
- **资源耗尽**：死循环、fork bomb、大输出、大文件写入或高内存占用拖垮宿主机
- **语义绕过**：绕过现有 `tool.code.execute` 的 AST 校验、模式隔离和受限 tool RPC

### 4.2 Phase 1 不承诺的能力

Phase 1 是一个**本地后端的最小可行隔离层**，不承诺以下强隔离能力：

- 内核级别 namespace / seccomp / AppArmor 隔离
- 容器镜像级只读根文件系统
- 后台进程的完整虚拟化管理
- 跨 session 的共享 sandbox 生命周期管理
- GPU、远程 SSH、云端沙箱等高阶能力

这些能力统一放在 Docker / SSH / SDK backend 阶段处理。

## 五、修订后的总体架构

### 5.1 总体链路

```text
ToolRuntime.invoke()
  -> SecurityApprovalGateway.authorize()
  -> SandboxToolExecutor.execute()
       -> [sandbox hit]   SandboxEnvironment.execute(...)
       -> [sandbox miss]  delegate.execute(...)
```

### 5.2 关键原则

- **不改变 `ToolRuntime` 接口**
- **不改变 builtin 工具注册方式**
- **不改变 `tool.code.execute` 既有语义**
- **先解决前台执行，再扩展后台执行**
- **先实现本地后端的可验证最小隔离，再扩展容器/远程后端**

## 六、核心模块设计（`packages/sandbox/`）

新增 `packages/sandbox/` 包，但它应只承载**执行环境与安全边界**，不承载工具业务语义。

### 6.1 `types.py`

建议保留以下抽象：

- `SandboxOutput`
  - `stdout`
  - `stderr`
  - `returncode`
  - `cwd`
  - `timed_out`
  - `diagnostics`
- `SessionHandle`
  - `session_id`
  - `backend_id`
  - `sandbox_root`
  - `cwd`
  - `snapshot_path`
  - `cwd_file`
  - `attachments`
- `EnvironmentBackend`
  - `create_session(...)`
  - `run_command(...)`
  - `kill_process(...)`
  - `read_cwd(...)`
  - `cleanup_session(...)`
  - `health_check()`

这里的 `ProcessHandle` 可以继续做 duck typing，但**资源回收、输出采集和 kill 语义必须通过 backend 暴露的显式接口协调**，不要在 governor 里直接假设所有后端都支持同一种 kill 方式。

### 6.2 `config.py`

建议保留统一配置对象，但把可实施状态写清楚：

- `mode`: `off | all | non-main`
- `backend`: `local | docker | ssh`
- `scope`: `session | agent | shared`
- `workspace_access`: `none | ro | rw`
- `resource_limits`

其中：

- **Phase 1 实际启用的模式只有 `off` 和 `all`**
- `non-main` 先保留为配置位，但暂不默认实现，直到 runtime 中存在稳定的 main-session 判定信号
- `scope` 和 `workspace_access` 在 Phase 1 只作为结构预留，不把它们写成“已完整生效”的能力承诺

### 6.3 `security_guard.py`

`SecurityGuard` 的职责应是**前置校验与环境裁剪**，而不是取代工具层对路径和参数的业务校验。

建议提供：

- `sanitize_env(base_env, extra_env=None)`
- `validate_bind_mounts(...)`（Phase 2 激活）
- `validate_network_mode(...)`（Phase 2 激活）
- `validate_sensitive_host_path(...)`

#### 环境变量策略

这里必须沿用当前 `tool.code.execute` 已经验证过的模型：

- 先按 `_SAFE_PREFIXES` 做**白名单前缀放行**
- 再按 `_SECRET_FRAGMENTS` 做**敏感片段排除**
- 最后叠加 sandbox 自己需要的显式变量（例如 snapshot 路径、runner 参数）

不能改成“只要名字不像 secret 就全部传入子进程”，否则会引入当前实现没有暴露的新环境面。

#### 路径策略

- 前台 terminal 的 `cwd` 解析继续复用现有 `resolve_allowed_path(...)`
- `SecurityGuard` 只负责补充“敏感宿主路径默认拒绝”的通用策略
- 不再在设计稿里引入一个完全独立的 `_resolve_safe_cwd()` 取代现有 allowed-roots 体系

## 七、执行层设计

### 7.1 `SandboxEnvironment`

`SandboxEnvironment` 仍然是协调器，但职责要收紧为：

1. 建立 session 级 sandbox 工作目录
2. 执行 Hermes 风格的 snapshot + spawn-per-call 包装
3. 维护 `cwd` 回写
4. 调用 governor 做 timeout / 限流 / kill / 输出采集
5. 把结果归一化成 `SandboxOutput`

#### Session 根目录

不要把 snapshot/cwd 文件直接放在全局可预测路径，例如：

- `/tmp/elephant-snap-{session_id}.sh`
- `/tmp/elephant-cwd-{session_id}.txt`

更稳妥的实现是：

- 为每个 sandbox session 创建独立目录，例如 `tempfile.mkdtemp(prefix="elephant-sandbox-")`
- 所有 snapshot、cwd、stdout、stderr、request/response 文件都落到这个 session 根目录里
- `cleanup_session()` 负责统一清理

#### Snapshot 机制

Hermes 风格的 snapshot 机制保留，但要明确：

- login shell bootstrap 只在 session 初始化时运行一次
- 后续命令使用 snapshot 恢复环境并更新 cwd
- 如果 snapshot 初始化失败，执行面可以降级为无 snapshot 模式，但必须留下诊断信息，不应默默吞掉失败原因

### 7.2 `SandboxToolExecutor`

推荐把适配器明确实现为一个**委托式 executor**，而不是只写一个“概念上的包装层”。

职责：

- 透明代理 `bind()` / `unbind()` 到内部 `InMemoryToolExecutor`
- 在 `execute()` 中基于 tool id、参数和配置判断是否命中 sandbox
- 未命中时无损委托给原执行器

推荐的命中策略：

- **Phase 1A**：只命中 `tool.terminal.exec` 且 `background != true`
- **Phase 1B**：`tool.code.execute` 仍由原 handler 执行，但 handler 内部改为使用 sandbox child launcher
- `tool.process.manage` 在 Phase 1 始终不命中 sandbox executor

伪代码如下：

```python
class SandboxToolExecutor(ToolExecutionBackend):
    def __init__(self, delegate: InMemoryToolExecutor, config: SandboxConfig, backend: EnvironmentBackend):
        self._delegate = delegate
        self._config = config
        self._backend = backend

    def bind(self, tool_id: str, handler: ToolHandler) -> None:
        self._delegate.bind(tool_id, handler)

    def unbind(self, tool_id: str) -> bool:
        return self._delegate.unbind(tool_id)

    def execute(self, definition: ToolDefinition, invocation: ToolInvocation) -> ExecutionResult:
        if not self._should_sandbox_terminal_foreground(definition, invocation):
            return self._delegate.execute(definition, invocation)
        return run_sandboxed_terminal_exec(definition, invocation, config=self._config, backend=self._backend)
```

### 7.3 `ResourceGovernor`

`ResourceGovernor` 必须从“示意代码”提升到真实可执行的约束层。

#### Phase 1 真实要做的限制

- **wall timeout**
- **stdout/stderr 限长**
- **文件大小上限**
- **进程数上限**
- **内存上限**
- **超时后的 process-group kill**

#### Phase 1 本地后端推荐实现

- 启动前在子进程里设置：
  - `setsid()`
  - `resource.setrlimit(resource.RLIMIT_FSIZE, ...)`
  - `resource.setrlimit(resource.RLIMIT_NPROC, ...)`
  - `resource.setrlimit(resource.RLIMIT_AS, ...)` 或等价内存限制
- governor 负责：
  - 按 deadline 轮询
  - 超时时通过 `backend.kill_process(session, proc)` 终止整个进程组
  - 从 stdout/stderr 文件或流中采集有限输出
  - 截断并在 diagnostics 中写出原因

> 这里不要在设计稿中提前承诺 cgroup；cgroup 是 Docker 后端阶段的能力。

### 7.4 `backends/local.py`

本地后端是 Phase 1 的 MVP 后端，但也必须和当前 runtime 上下文对齐。

要求：

- `create_session(...)` 使用调用方传入的 `cwd` 与 `env`
- `run_command(..., cwd=...)` 必须尊重每次调用传入的 `cwd`
- session 根目录使用临时目录，不使用可预测全局路径
- `kill_process()` 对进程组生效，而不是只 kill 单个 pid
- `read_cwd()` 从 session 内部状态文件读取
- `cleanup_session()` 清理整个 sandbox session 目录

## 八、与现有工具的集成策略

### 8.1 Phase 1A：只处理 `tool.terminal.exec` 的前台路径

这是第一阶段最重要的收敛点。

#### 范围

只覆盖：

- `tool.terminal.exec`
- `background=false`（默认前台）
- 已有 `cwd` / `env` / `timeout_seconds` 参数

不覆盖：

- `background=true`
- `tool.process.manage`
- 后台长生命周期进程

#### 做法

- 沿用 `handlers_filesystem.py` 里现有的参数解析和 `resolve_allowed_path(...)`
- 只把最终的“前台命令执行”替换到 `SandboxEnvironment`
- 返回结果仍然组装成当前 `tool_summary(...)` 期望的结构

这样可以保证：

- `cwd` 语义不变
- `allowed_roots` 语义不变
- `env` 叠加语义不变
- `background=true` 仍由 `InMemoryProcessManager` 管理，不会半途失效

### 8.2 Phase 1B：保持 `tool.code.execute` 契约不变，只替换子进程启动点

这是本方案最关键的修订点。

#### 不能做的事

Phase 1B **不能**：

- 直接在 executor 层拦截 `tool.code.execute`
- 跳过 `_validate_python_snippet(...)`
- 跳过 `project/strict` 模式分支
- 跳过受限 tool RPC 和调用上限控制
- 把 Python 片段拼成 shell 命令直接执行

#### 正确做法

保留：

- `run_code_execute(...)`
- `_validate_python_snippet(...)`
- `_run_code_subprocess(...)` 的总体语义
- 现有 request/response 目录式 tool RPC

重构：

- 把 `_run_code_subprocess(...)` 中的子进程创建逻辑提取为一个小接口，例如：
  - `_spawn_code_process_local(...)`
  - `_spawn_code_process_sandbox(...)`
  - 或 `CodeExecutionLauncher`
- 由 sandbox launcher 负责在 sandbox session 中运行 `runner.py`
- `project` / `strict` 仍然由现有 handler 决定
- tool RPC 继续通过当前 request/response 目录和 `runtime.invoke(...)` 完成

这样才能确保 Issue #11 需要的“代码执行隔离”实现后，既不破坏当前安全语义，也不破坏产品行为。

### 8.3 `tool.process.manage` 的处理

Phase 1 明确不修改 `tool.process.manage`。

原因：

- 它当前绑定的是 `InMemoryProcessManager`
- 它依赖 `tool.terminal.exec background=true` 返回的宿主进程句柄
- 如果在没有统一后台进程抽象的前提下提前迁移，会导致 terminal/process 两个工具行为脱节

因此：

- **Phase 1**：后台终端执行继续走现有实现
- **Phase 2+**：再决定是把后台进程也迁到 sandbox，还是显式限制它不进入 sandbox

## 九、安全层纵深

修订后的纵深关系如下：

```text
请求
  -> Tool visibility / availability
  -> SecurityApprovalGateway
       -> required_controls 包含 sandbox（策略要求）
  -> SandboxToolExecutor / code child launcher
  -> SecurityGuard
       -> env 白名单
       -> 敏感路径校验
       -> bind/network 校验（Phase 2 激活）
  -> SandboxEnvironment
       -> snapshot + cwd 维护
  -> EnvironmentBackend
       -> local: process-group + setrlimit
       -> docker: namespace + cgroup + network=none
       -> ssh: 远程隔离
  -> Tool-specific guards
       -> tool.code.execute AST 校验与受限 tool RPC
```

重点在于：

- sandbox 是**执行边界层**
- AST 校验、tool RPC allowlist 仍然是 **tool-specific guard**
- 两者是叠加关系，不是替代关系

## 十、配置入口

建议通过 runtime state 配置加载，但明确标注 Phase 1 的有效字段：

```yaml
sandbox:
  mode: "off"          # Phase 1 实际支持 off / all；non-main 预留
  backend: "local"     # Phase 1 仅 local
  scope: "session"     # 结构预留
  workspace_access: "none"  # 结构预留；terminal cwd 仍由 allowed_roots 控制
  resource_limits:
    max_wall_seconds: 120
    max_memory_mb: 512
    max_processes: 64
    max_file_size_mb: 50
    max_stdout_bytes: 50000
    max_stderr_bytes: 10000
```

## 十一、实施路径

### Phase 0：设计清理与接缝抽象

目标：把实现接缝找准，不急于扩面。

变更面：

- `packages/sandbox/__init__.py`
- `packages/sandbox/types.py`
- `packages/sandbox/config.py`
- `packages/sandbox/security_guard.py`
- `packages/sandbox/resource_governor.py`
- `packages/sandbox/environment.py`
- `packages/sandbox/registry.py`
- `packages/sandbox/backends/local.py`
- `packages/sandbox/executor.py`
- `packages/tools/factory.py`

交付结果：

- 可插拔 local backend
- 可委托的 sandbox executor
- 白名单 env sanitize 组件
- 可被 terminal/code 复用的 governor

### Phase 1A：前台 terminal exec 沙箱化

目标：在不破坏现有后台进程能力的前提下，先把前台命令执行纳入 sandbox。

变更面：

- `packages/tools/handlers_filesystem.py`（仅前台 terminal 执行分支）
- `packages/tools/factory.py`
- `tests/test_sandbox_terminal_exec.py`
- `tests/test_sandbox_security_guard.py`
- `tests/test_sandbox_resource_governor.py`
- `tests/test_sandbox_local_backend.py`
- `tests/test_sandbox_executor.py`

验收：

- `tool.terminal.exec background=false` 走 sandbox
- `background=true` 保持现状
- timeout / output truncation / cwd 限制 / env 白名单全部可测

### Phase 1B：`tool.code.execute` 子进程沙箱化

目标：在保留既有语义的情况下完成代码执行隔离闭环。

变更面：

- `packages/tools/handlers_code_execution.py`
- `tests/test_sandbox_code_execute.py`
- 复用前面已有的 `sandbox` 与 `governor` 组件

验收：

- AST 校验保持不变
- `project/strict` 模式保持不变
- 受限 tool RPC 保持不变
- child runner 在 sandbox 中运行
- Issue #11 的代码执行隔离 AC 达成

### Phase 2：Docker 后端与更强隔离

目标：把宿主级最小隔离扩展到容器级强隔离。

变更面：

- `packages/sandbox/backends/docker.py`
- `Dockerfile.sandbox`
- bind mount / network mode 真正激活
- `tests/test_sandbox_docker_backend.py`

新增能力：

- `network=none` 默认生效
- cgroup 资源限制
- 只读根文件系统
- bind mount 白名单

### Phase 3：后台进程、SSH、scope 管理

目标：补齐 Phase 1 故意延后的复杂能力。

候选范围：

- `tool.terminal.exec background=true` 的 sandbox 方案
- `tool.process.manage` 与 sandbox 进程句柄对齐
- `packages/sandbox/backends/ssh.py`
- `scope=session|agent|shared` 真正生效
- sandbox lifecycle CLI（如 list / prune）

### Phase 4：高级后端

候选范围：

- SDK Backend（Modal / Daytona 等）
- Browser sandbox
- Mirror workspace sync
- seccomp / AppArmor profile 强化

## 十二、测试矩阵

### 12.1 Phase 1A

- **允许路径**：前台 `tool.terminal.exec` 在合法 `cwd` 中成功执行
- **拒绝路径**：`cwd` 越界到非 allowed root 时被拒绝
- **环境收缩**：敏感环境变量不进入 sandbox 子进程
- **超时处理**：死循环或长命令被 timeout 并 kill 整个进程组
- **输出截断**：超大 stdout/stderr 被限长并带 diagnostics
- **委托完整性**：`bind/unbind` 正常工作，未命中 sandbox 的工具执行不受影响
- **后台兼容**：`background=true` 仍返回当前 `process_id` 语义

### 12.2 Phase 1B

- **AST 兼容**：unsafe import / `open()` / `eval()` 仍被拒绝
- **模式兼容**：`project` / `strict` 行为不变
- **tool RPC 兼容**：allowlist、生效次数上限、terminal 参数黑名单保持不变
- **隔离落地**：runner 确认在 sandbox child launcher 下执行
- **失败诊断**：启动失败、timeout、非零退出都能输出可诊断错误

### 12.3 Phase 2+

- **bind mount 校验**：敏感宿主路径默认拒绝
- **network 校验**：`host` 模式被拒绝，默认 `none`
- **容器限制**：内存、进程数、文件大小在容器层真正被强制执行

## 十三、开放问题

- 如何在当前 runtime 中稳定定义“main session”与“non-main session”
- 后台进程最终是完全纳入 sandbox，还是显式声明为非 sandbox 能力
- 本地后端是否足以满足 Issue #11 对“isolated environment”的最低预期，还是需要 Docker 作为 release gate
- sandbox diagnostics 应通过 `ExecutionResult.summary` 暴露多少细节，避免把实现细节泄漏给普通用户

## 十四、为什么这版更优雅

1. **不破坏现有工具契约**：`tool.code.execute` 和 `tool.terminal.exec` 的现有产品行为被完整保留
2. **没有安全回退**：env sanitize 继续沿用白名单模型，而不是放宽环境暴露面
3. **实现接缝正确**：对接 `ToolRuntime` 的真实扩展点是 executor delegation + child process launcher，而不是重写 handler 语义
4. **分阶段可验证**：Phase 1A、1B、2、3 各自都有可独立验收的范围与测试集
5. **与现有审批系统自然衔接**：安全策略继续表达“执行需要 sandbox”，runtime 再把这个要求真正做实
6. **为更强隔离留好了口子**：本地后端先闭环，Docker/SSH/SDK 后端后续无须推翻 Phase 1 设计
