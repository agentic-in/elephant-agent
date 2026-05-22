# Skill Optimization from Historical Tool Trajectories

> Issue: [#10 — Add reflect skill optimization from historical tool trajectories](https://github.com/agentic-in/elephant-agent/issues/10)
> Branch: `feat/skill-optimization`
> Worktree: `.worktrees/skill-optimization`
> Status: Implementation Complete (validated locally on 2026-05-19)

---

## 1 总体设计目标

### 1.1 问题陈述

当前 Elephant Agent 的 Reflect 系统 `skills` feature 仅执行**静态 skill 审计**——在 reflect 过程中检查 skill catalog，并写入 `world.skills.affinity.*` Personal Model fact。它不具备从历史 tool 使用轨迹中提取模式、识别 skill 优化机会的能力。

具体差距：

1. **无跨 episode 聚合**：现有 `skills` feature 主要基于当前 supplied evidence 和 active affinity 做静态判断，无法发现跨多次会话重复出现的 tool 使用模式。
2. **无 trajectory 信号提取**：`Step` 中记录了 `call_tool` 的 `metadata.tool_name`，`Loop` 中记录了 `outcome`，但无管道将这些原始事件聚合为 skill 优化候选。
3. **无审核闭环**：从 trajectory 信号到 skill 内容更新的全链路不存在——没有“发现模式 → 生成优化候选 → 人工审核 → 更新 authored skill”的流水线。
4. **无中间态持久化**：发现的优化候选没有 durable 存储层，后续 reflect 无法复用既有结论、做 supersede、做 reject suppression、或给人工运营面板展示。
5. **无 operator 边界**：现有设计里没有明确区分“可自动生成候选”与“只有 operator 才能 apply 到 authored skill”的边界。

### 1.2 设计目标

| # | 目标 | 衡量标准 |
|---|------|----------|
| G1 | 从跨 episode 历史 tool trajectory 中提取 skill 优化信号 | 端到端：给定 10+ 个包含相似 tool 序列的 closed episode，系统能自动发现并输出至少 1 条优化候选 |
| G2 | 优化候选经 operator 明确审核后，可落地为 **authored skill** 内容更新 | 端到端：`review_status=approved` 且目标 skill 为 authored skill 时，系统能通过 `tool.skill.manage action=update` 应用更新 |
| G3 | 不破坏现有 Reflect 系统的 feature-composition 架构 | 新 feature 作为独立 `Feature` 注册；不把 trajectory 计算硬塞进现有 7 个 feature |
| G4 | 隐私约束：trajectory 聚合不暴露原始对话内容 | 聚合层只输出统计摘要和模式标签；不包含用户原文、assistant 原文、tool arguments |
| G5 | 资源可控：trajectory 分析只在 dream/空闲时段或手动 trigger 触发 | 不在 `episode_close` 主路径新增 LLM 调用；signal extraction 全程纯 Python |
| G6 | 候选写入后不污染核心对话提示词 | 优化候选以 `recall_policy=review` + `retention_lifecycle=draft` 持久化，不进入 core prompt |

### 1.3 非目标

- 不实现自动 skill 内容生成后直接发布；**必须经过 operator 明确审核**。
- 不实现 skill 版本回滚；由 `tool.skill.manage` 现有 authored-skill 管理能力覆盖。
- 不实现 trajectory 的实时流式分析；本方案仅做 batch / offline-style 聚合。
- 不修改 `Step` / `Loop` / `Episode` 的 contracts 和底层表结构。
- 不扩展 `tool.personal_model.search` 新参数（如 `topic_prefix`）；方案必须建立在现有工具能力之上。
- 不承诺直接更新非-authored skill；这类候选仅生成建议，不自动 apply。

---

## 2 详细方案设计

### 2.1 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                     Reflect Agent Runner                        │
│                                                                 │
│  ┌──────────┐  ┌───────────────┐  ┌──────────┐  ┌────────────┐  │
│  │  dream   │  │skill_opt feat │  │  skills  │  │ other feat │  │
│  │ feature  │  │               │  │ feature  │  │            │  │
│  └────┬─────┘  └──────┬────────┘  └────┬─────┘  └────────────┘  │
│       │               │                │                         │
│  ┌────▼───────────────▼────────────────▼─────────────────────┐   │
│  │                    Evidence Builder                        │   │
│  └─────────────────────────┬─────────────────────────────────┘   │
└────────────────────────────┼─────────────────────────────────────┘
                             │
              ┌──────────────▼────────────────┐
              │     Trajectory Signal Layer    │
              │   (pure Python, no LLM)        │
              │                                │
              │  ┌──────────────┐              │
              │  │ Signal       │              │
              │  │ Extractor    │              │
              │  └──────┬───────┘              │
              │         │                      │
              │  ┌──────▼───────────────┐      │
              │  │ Candidate Aggregator │      │
              │  └──────┬───────────────┘      │
              └─────────┼──────────────────────┘
                        │
        ┌───────────────▼──────────────────────────┐
        │ PM facts: world.skills.optimization.*    │
        │ review_status=pending/approved/applied/  │
        │ rejected                                 │
        └──────────────────────────────────────────┘
```

**关键原则**：

- **Trajectory Signal Layer** 只做 deterministic 统计和聚合，不触发 LLM。
- **Reflect Feature** 只消费 evidence，并调用现有工具形成或推进候选状态。
- **Operator Review** 是状态推进的唯一授权路径：候选可自动生成，但不能自动 apply。
- **Authored Skill Boundary** 明确：只有 authored skill 才能被 `tool.skill.manage update` 更新。

### 2.2 新 Feature：`skill_optimization`

在 `apps/reflect/features/` 新增 `skill_optimization.py`：

```python
FEATURE = Feature(
    feature_id="skill_optimization",
    tools=(
        "tool.skill.list",
        "tool.skill.view",
        "tool.skill.manage",
        "tool.personal_model.search",
        "tool.personal_model.update",
    ),
    sop_fragment="""...""",  # 见 2.6
    constraints="""...""",   # 见 2.6
    requires=("skills",),
)
```

**触发方式**：

- `dream` trigger 自动捆绑 `skill_optimization`（与 `skills`、`diary` 并列）。
- 新增可选 trigger `skill_review`，供 CLI / operator 手动触发。 
- `episode_close` 不自动触发 `skill_optimization`，避免把 trajectory 分析耦合进主对话收尾路径。

**Feature 注册变更**：

```python
# apps/reflect/features/__init__.py
TRIGGER_FEATURES = {
    ...
    "dream": ("dream", "questions", "skills", "skill_optimization", "diary"),
    "skill_review": ("skill_optimization", "skills"),
}
```

### 2.3 Trajectory Signal Layer

#### 2.3.1 信号提取器（Signal Extractor）

从 repository 中提取跨 episode 的 tool 使用信号，**纯 Python 计算，不消耗 LLM token**。

**输入**：`RuntimeStorageRepository` + `personal_model_id`

**输出**：`ToolTrajectorySignal` 数据结构列表

```python
@dataclass(frozen=True, slots=True)
class ToolTrajectorySignal:
    """A single signal extracted from cross-episode tool trajectory analysis."""

    signal_id: str
    signal_type: str
    tool_names: tuple[str, ...]
    episode_ids: tuple[str, ...]
    occurrence_count: int
    confidence: float
    summary: str
    metadata: Mapping[str, str] = field(default_factory=dict)
```

**信号类型定义**：

| 信号类型 | 检测逻辑 | 优化方向 |
|----------|----------|----------|
| `recurring_sequence` | 同一 tool 序列在 ≥3 个 closed episode 中出现 | 将序列编码为 skill procedure step |
| `error_recovery` | `call_tool` step 的 `status=failed` 后紧跟另一 tool call | 在 skill 中增加错误处理指引 |
| `tool_combination` | 特定 tool 组合高频共现（≥5 次跨 episode） | 在 skill 中补充组合使用策略 |
| `skill_gap` | 已存在 active affinity，但实际轨迹绕过 skill 所覆盖的 procedure | 更新 skill 触发条件/入口语义 |
| `outdated_pattern` | skill instruction 中引用的 tool/顺序与实际高频轨迹长期偏离 | 更新 skill 中的 tool 引用或步骤顺序 |

**提取算法**（`packages/reflect/trajectory_signals.py`）

```python
def extract_trajectory_signals(
    repository: RuntimeStorageRepository,
    *,
    personal_model_id: str,
    lookback_episodes: int = 30,
    min_occurrences: int = 3,
) -> tuple[ToolTrajectorySignal, ...]:
    """Extract tool trajectory signals from recent closed episodes.

    Repository currently exposes list_episodes(), list_loops(), list_steps()
    without personal_model/status/limit filters, so the extractor must:

    1. Load all episodes from repository.list_episodes()
    2. Filter by personal_model_id and status == "closed"
    3. Sort by started_at DESC and keep the latest N
    4. For each episode, load loops and steps from repository
    5. Detect recurring sequences, error recoveries, tool combinations
    6. Cross-reference with active skill definitions / affinity facts
    7. Return deduplicated signals sorted by confidence
    """
```

**关键实现细节**：

1. **Episode 过滤**：当前 `repository.list_episodes()` 只支持 `state_id` 过滤，不支持 `personal_model_id`、`status`、`limit` 过滤；因此 extractor 需要在内存中二次过滤并截断 lookback window。
2. **Tool 序列提取**：遍历 episode 下的 loops，再遍历每个 loop 的 steps，按 `sequence` 排序，仅提取 `action == "call_tool"` 的 step，从 `metadata.tool_name` 获取工具名。
3. **错误恢复检测**：识别 `status == "failed"` 的 `call_tool` step 后的后继 tool call，生成 `error_recovery` signal。
4. **序列模式检测**：使用 n-gram 滑动窗口（优先 n=2,3）统计跨 episode 的重复序列。
5. **Skill 交叉引用**：通过 active `world.skills.affinity.*` facts、`tool.skill.list` 和 `tool.skill.view` 输出建立“信号 → skill”的对齐关系。
6. **隐私约束**：signal summary 只能使用统计描述，如“`tool.terminal.exec -> tool.file.read` 在 5 个 episode 中重复出现”；禁止写入 user query / assistant response / tool arguments。

#### 2.3.2 候选聚合器（Candidate Aggregator）

将多个 `ToolTrajectorySignal` 聚合为 `SkillOptimizationCandidate`，供 reflect feature 处理。

```python
@dataclass(frozen=True, slots=True)
class SkillOptimizationCandidate:
    """A candidate skill optimization derived from aggregated trajectory signals."""

    candidate_id: str
    target_skill_id: str | None
    target_index_id: str | None
    optimization_type: str
    supporting_signals: tuple[str, ...]
    confidence: float
    summary: str
    suggested_action: str
    candidate_key: str
    metadata: Mapping[str, str] = field(default_factory=dict)
```

**聚合逻辑**：

1. 将 signal 按 `target_skill_id` 分组；若无法匹配 skill，则视为 `create_new` 分组。
2. 同一 skill 的多个 signal 聚合为单个候选，但**不同 `optimization_type` 必须拆为不同候选**。
3. 通过 `optimization_type + normalized tool set + signal fingerprint` 生成 deterministic `candidate_key`，避免同 skill 下的不同候选互相覆盖。
4. 输出按 confidence 降序排列，限制最多 5 个候选。
5. 对被 operator 明确 rejected 的旧候选做 suppress：
   - 若新证据与旧 rejected 候选指纹相同，则不再重复生成。
   - 若新证据显著增强（如 `occurrence_count` 提升、tool set 变化、candidate_key 变化），允许生成新候选并在 metadata 中标注 supersedes。

### 2.4 PM Fact 存储与候选标识

优化候选以 PM fact 形式持久化，复用现有 `personal_model_facts` 表。

#### 2.4.1 Topic 设计

**Topic 格式**：

- 匹配到已有 skill：`world.skills.optimization.{target_scope}.{candidate_key}`
- 未匹配到 skill（建议新建）：`world.skills.optimization.new.{candidate_key}`

其中：

- `target_scope` = `skill_index_id`
- `candidate_key` = 稳定、可重复计算的候选键，例如 `update_procedure_ab12cd34`

**为什么不使用 `world.skills.optimization.{skill_index_id}` 单段格式**：

- 同一 skill 可能同时存在 `update_procedure` 和 `add_error_handling` 等多个候选；单 topic 会互相覆盖。
- `create_new` 候选没有现成 `skill_index_id` 可复用。
- 需要支持 supersede / reject suppression / 审计时保留多个候选版本。

#### 2.4.2 Metadata 规范

```json
{
  "topic": "world.skills.optimization.python_dev.update_procedure_ab12cd34",
  "skill_id": "python-development",
  "index_id": "python_dev",
  "target_scope": "python_dev",
  "candidate_id": "cand_01jskillopt",
  "candidate_key": "update_procedure_ab12cd34",
  "projection_policy": "skill_optimization_candidate",
  "optimization_type": "update_procedure",
  "signal_type": "recurring_sequence",
  "occurrence_count": "5",
  "confidence": "0.82",
  "review_status": "pending",
  "retention_lifecycle": "draft"
}
```

**写入策略**：

- `tool.personal_model.update action=remember`
- `lens=world`
- `topic=world.skills.optimization.{...}`
- `recall_policy=review`
- metadata 中包含 `retention_lifecycle=draft`

这样可以确保候选**不会进入核心对话提示词**，同时仍然能通过 PM API / Dashboard / inventory search 被查询和审计。

#### 2.4.3 Fact text 示例

> `python-development` skill 的历史工具轨迹显示 `tool.terminal.exec -> tool.file.read` 序列在 5 个 closed episode 中反复出现，建议将该序列沉淀为 procedure step，并补充失败后的替代路径提示。

**文本规范**：

- 允许包含 tool 名称、出现次数、趋势判断。
- 不允许包含 user query、assistant 原文、tool 参数、文件路径内容、对话原文引用。

### 2.5 审核状态机

#### 2.5.1 Authoritative Lifecycle

唯一允许的状态流转：

- `pending -> approved -> applied`
- `pending -> rejected`

**说明**：

- `pending`：reflect 自动生成，等待 operator 审核。
- `approved`：operator 已明确批准，但尚未 apply 到 skill。
- `applied`：候选已经成功应用到 authored skill，并保留审计记录。
- `rejected`：operator 明确拒绝；候选保留用于审计与 suppress 重复生成。

#### 2.5.2 为什么 rejected 不 delete / forget

- 需要保留 reject 记录以避免下次 reflect 重复生成同一候选。
- 需要给 operator / dashboard 留审计线索。
- 因为本方案使用 `recall_policy=review` + `retention_lifecycle=draft`，rejected 候选不会污染核心 prompt，不需要通过 `forget` 清除。

#### 2.5.3 状态推进方式

- reflect feature 只负责生成 `pending` 候选，或消费已存在的 `approved` 候选执行 apply。
- operator 审核可通过手动工具流、CLI 包装命令、或后续 Dashboard 操作将 `review_status` 从 `pending` 改为 `approved` / `rejected`。
- 对已有候选做 `correct` / `restore` / `delete` 时，必须先通过 `tool.personal_model.search` 获取**精确 ref**。

### 2.6 Feature SOP 与约束

#### SOP Fragment

```
- Call tool.personal_model.search mode=inventory lens=world status=all to inspect existing world.* topic inventory.
- Call tool.personal_model.search lens=world topic=world.skills.affinity status=active only as a broad hint; use evidence + exact topic lookups for actual writes.
- Call tool.skill.list to inspect the available skill catalog.
- For each relevant skill candidate, call tool.skill.view to inspect its current authored instruction text.
- Review the supplied trajectory signals and pre-aggregated optimization candidates in the evidence packet.
- For each new candidate:
  - Derive an exact topic in the format world.skills.optimization.{target_scope}.{candidate_key} or world.skills.optimization.new.{candidate_key}.
  - Call tool.personal_model.search lens=world topic=<exact_topic> status=all to check whether the candidate already exists and to capture exact ref if it does.
  - If no existing candidate exists, write one pending candidate with tool.personal_model.update action=remember, recall_policy=review, and metadata.retention_lifecycle=draft.
  - If a pending candidate already exists and the new evidence supersedes it, call tool.personal_model.update action=correct with the exact ref.
  - If a rejected candidate already exists with the same candidate_key and the evidence is not materially stronger, do not recreate it.
- For an approved candidate:
  - Only proceed if the target skill is an authored skill.
  - Call tool.skill.manage action=update to apply the change.
  - After a successful apply, call tool.personal_model.update action=correct with the exact ref to set review_status=applied.
- For approved candidates targeting non-authored skills:
  - Do not call tool.skill.manage update.
  - Preserve the candidate as approved and keep suggested_action for operator follow-up.
```

#### Constraints

```
- Only generate optimization candidates from trajectory signals with confidence >= 0.6 and occurrence_count >= 3.
- Do not include any user conversation text in optimization summaries — use only statistical patterns.
- Do not automatically apply optimizations unless review_status=approved and the target skill is authored.
- All candidate writes MUST use recall_policy=review.
- All candidate writes MUST include metadata.retention_lifecycle=draft.
- topic MUST follow one of these formats:
  - world.skills.optimization.{skill_index_id}.{candidate_key}
  - world.skills.optimization.new.{candidate_key}
- lens MUST be world.
- metadata MUST include candidate_id, candidate_key, projection_policy, optimization_type, signal_type, occurrence_count, confidence, and review_status.
- projection_policy MUST be skill_optimization_candidate.
- rejected candidates MUST be retained for audit; do not forget/delete them merely to hide them.
- Before action=correct, action=restore, or action=delete on a candidate fact, resolve the exact ref through tool.personal_model.search.
- When trigger=dream, prioritize consolidating or applying existing candidates over creating many new ones.
- When trigger=skill_review, prioritize generating fresh pending candidates from recent trajectory signals.
```

### 2.7 Evidence Builder 扩展

在 `apps/reflect/evidence.py` 的 `build_evidence()` 中扩展 `skill_optimization` feature 的 evidence 构建：

```python
if "skill_optimization" in feature_ids:
    signals = extract_trajectory_signals(
        runtime.repository,
        personal_model_id=job.personal_model_id,
    )
    candidates = aggregate_signals(
        signals,
        runtime.repository,
        personal_model_id=job.personal_model_id,
    )
    lines.extend([
        "",
        "## Trajectory Signals",
        f"signals: {len(signals)}",
        *(f"- [{s.signal_type}] {s.summary} (confidence={s.confidence:.2f}, count={s.occurrence_count})" for s in signals[:15]),
        "",
        "## Optimization Candidates",
        f"candidates: {len(candidates)}",
        *(f"- [{c.optimization_type}] {c.suggested_action} (confidence={c.confidence:.2f})" for c in candidates[:5]),
    ])
```

**注意**：Evidence 中只能放 summary，不得嵌入用户原文或完整对话片段。

### 2.8 文件结构

```
apps/reflect/features/skill_optimization.py      # Feature 定义（SOP + constraints）
apps/reflect/features/__init__.py                # 注册 feature 与 trigger
apps/reflect/evidence.py                         # 注入 trajectory evidence
apps/reflect/prompts.py                          # 补充 optimization topic 规范
packages/reflect/__init__.py                     # 导出 trajectory API
packages/reflect/types.py                        # ToolTrajectorySignal, SkillOptimizationCandidate
packages/reflect/trajectory_signals.py           # 信号提取器
packages/reflect/aggregation.py                  # 候选聚合 / candidate_key / suppress 逻辑
packages/understanding/personal_model_governance.py  # optimization topic helper（可选但建议）
tests/unit/reflect/test_skill_optimization.py    # feature 注册测试
tests/unit/reflect/test_trajectory_signals.py    # 信号提取单元测试
tests/unit/reflect/test_aggregation.py           # 聚合与 suppress 单元测试
tests/unit/reflect/test_optimization_lifecycle.py # PM fact 生命周期测试
tests/integration/reflect/test_skill_opt_e2e.py  # 端到端集成测试
```

### 2.9 现有代码变更范围

| 文件 | 变更类型 | 变更内容 |
|------|----------|----------|
| `apps/reflect/features/__init__.py` | 修改 | 注册 `skill_optimization` feature，更新 `TRIGGER_FEATURES` |
| `apps/reflect/evidence.py` | 修改 | 添加 `skill_optimization` evidence 构建分支 |
| `apps/reflect/prompts.py` | 修改 | 明确 `world.skills.optimization.*` topic 的规范与用途 |
| `packages/understanding/personal_model_governance.py` | 修改（建议） | 增加 optimization topic helper，避免硬编码 prefix |
| `packages/reflect/` | 新增 | trajectory 信号提取、候选聚合、candidate key、suppress 逻辑 |
| `packages/kernel/generation_context.py` | 无强制代码变更 | 通过 `recall_policy=review` 与 `retention_lifecycle=draft` 即可保证候选不进 core prompt |
| `apps/dashboard/.../PersonalModelMapPage.tsx` | 无强制代码变更 | 现有 PM map 可以展示任意 topic；仅需验证 optimization facts 可见 |

---

## 3 实施计划

### Phase 1：数据模型与信号提取层（P1）

**目标**：建立 trajectory 信号提取的纯计算层，不涉及 LLM 调用。

**任务**：

1. 创建 `packages/reflect/types.py`：定义 `ToolTrajectorySignal` 和 `SkillOptimizationCandidate` 数据类。
2. 创建 `packages/reflect/trajectory_signals.py`：
   - `load_recent_closed_episodes()`：基于 `list_episodes()` 结果做 `personal_model_id + status + lookback` 二次过滤
   - `extract_tool_sequences()`：从 Episode → Loop → Step 提取 tool 序列
   - `detect_recurring_sequences()`：n-gram 重复序列检测
   - `detect_error_recoveries()`：失败 → 后继调用模式检测
   - `detect_tool_combinations()`：高频 tool 共现检测
   - `extract_trajectory_signals()`：主入口，组合以上检测器
3. 创建 `packages/reflect/aggregation.py`：
   - `match_signals_to_skills()`：将 signal 与 skill / affinity 对齐
   - `build_candidate_key()`：为每个候选生成稳定键
   - `aggregate_signals()`：聚合为 `SkillOptimizationCandidate`
4. 编写 `tests/unit/reflect/test_trajectory_signals.py`：覆盖所有检测器。
5. 编写 `tests/unit/reflect/test_aggregation.py`：覆盖聚合逻辑、候选拆分、candidate key 稳定性。

**产出**：

- `packages/reflect/` 纯 Python 包，无外部依赖。
- 单元测试覆盖率 ≥ 90%。
- 所有检测器可独立调用验证。
- 候选的 `candidate_key` 可稳定重算，不依赖随机 UUID。

### Phase 2：Feature 注册、Topic 对齐与 Evidence 集成（P2）

**目标**：注册 `skill_optimization` feature，扩展 evidence builder，并补齐 optimization topic 规范。

**任务**：

1. 创建 `apps/reflect/features/skill_optimization.py`：Feature 定义（SOP + constraints）。
2. 修改 `apps/reflect/features/__init__.py`：
   - 导入 `skill_optimization` feature
   - 注册到 `ALL_FEATURES`
   - 更新 `TRIGGER_FEATURES`：`dream` 捆绑 `skill_optimization`，新增 `skill_review` trigger
3. 修改 `apps/reflect/evidence.py`：
   - 添加 `skill_optimization` evidence 构建分支
   - 调用 `extract_trajectory_signals()` 和 `aggregate_signals()`
4. 修改 `apps/reflect/prompts.py`：补充 `world.skills.optimization.*` topic 规范，避免 feature 提示词与新 topic 脱节。
5. 视实现需要，在 `packages/understanding/personal_model_governance.py` 增加 optimization topic helper。
6. 编写 `tests/unit/reflect/test_skill_optimization.py`：验证 feature 注册、trigger 解析和 evidence 构建。

**产出**：

- `skill_optimization` feature 注册完成。
- `dream` trigger 自动包含 `skill_optimization`。
- `skill_review` trigger 可手动触发。
- evidence 包含 trajectory signals 和 optimization candidates。
- reflect 的 topic 说明与新设计保持一致。

### Phase 3：PM Fact 生命周期与审核闭环（P3）

**目标**：实现优化候选的 PM fact 持久化、ref-based 更新和 operator 审核闭环。

**任务**：

1. 实现 `write_optimization_candidate()`：
   - 将候选写为 `world.skills.optimization.*` PM fact
   - 强制使用 `recall_policy=review`
   - metadata 带 `retention_lifecycle=draft`
2. 实现 `find_candidate_by_topic()` / `find_candidate_ref()`：基于 exact topic + `tool.personal_model.search` 结果获取候选 ref。
3. 实现 `load_candidates()`：按 topic prefix / status 聚合出 pending / approved / rejected 候选。
4. 实现 `mark_candidate_review_status()`：推进 `pending -> approved`、`pending -> rejected`、`approved -> applied`。
5. 实现 `apply_approved_optimization()`：
   - 仅对 authored skill 调用 `tool.skill.manage action=update`
   - apply 成功后，将候选状态更新为 `applied`
6. 实现 `should_suppress_candidate()`：对 rejected / superseded 候选做抑制。
7. 编写 `tests/unit/reflect/test_optimization_lifecycle.py`：覆盖完整审核生命周期、ref 要求、authored skill 限制。

**产出**：

- 优化候选可持久化为 PM fact。
- 生命周期明确：`pending -> approved -> applied` / `pending -> rejected`。
- rejected 候选被保留且可抑制重复生成。
- 只有 authored skill 能被 apply。

### Phase 4：端到端验证与集成（P4）

**目标**：端到端验证完整链路，确保从 trajectory 信号到 skill 更新的闭环可用。

**任务**：

1. 编写 `tests/integration/reflect/test_skill_opt_e2e.py`：
   - 构造 10+ 个包含相似 tool 序列的 closed episode 数据
   - 触发 `skill_review` reflect job
   - 验证 trajectory signals 被正确提取
   - 验证 optimization candidates 被写入 PM facts
   - 模拟 operator 审核通过
   - 验证 approved candidate 可更新 authored skill
2. Dashboard 集成验证：确认 `world.skills.optimization.*` facts 在 PM map 页面可见。
3. CLI 集成验证：确认 `elephant reflect --trigger skill_review --features skill_optimization` 可手动触发。
4. 性能验证：确保 signal 提取在 30 个 episode 内完成时间 < 5s（纯计算）。
5. 回归验证：确保现有 7 个 reflect feature 行为不受影响。

**产出**：

- 端到端集成测试通过。
- Dashboard 可展示优化候选。
- CLI 可手动触发 `skill_review`。
- 非-authored skill 候选不会被误 apply。

---

## 4 分阶段验收指标

### Phase 1 验收指标

| # | 指标 | 验证方法 |
|---|------|----------|
| P1-1 | `ToolTrajectorySignal` 和 `SkillOptimizationCandidate` 数据类可实例化且 frozen | 单元测试 |
| P1-2 | `load_recent_closed_episodes()` 能从全量 episode 中正确筛出指定 `personal_model_id` 的最近 closed episode | 单元测试 |
| P1-3 | 给定 3+ 个含相同 tool 序列的 episode，`detect_recurring_sequences()` 输出至少 1 个 signal | 单元测试：构造重复 `[terminal.exec, file.read]` 序列 |
| P1-4 | 给定含 failed tool call 后紧跟恢复调用的 episode，`detect_error_recoveries()` 输出 signal | 单元测试：构造 failed → recovery 步骤 |
| P1-5 | 给定 5+ 个含相同 tool 组合的 episode，`detect_tool_combinations()` 输出 signal | 单元测试：构造高频共现 |
| P1-6 | `extract_trajectory_signals()` 对空 episode 列表返回空 tuple | 单元测试 |
| P1-7 | `aggregate_signals()` 对同一 skill 的不同 `optimization_type` 生成不同候选 | 单元测试 |
| P1-8 | `build_candidate_key()` 对相同输入稳定产出相同 key | 单元测试 |
| P1-9 | 所有信号检测器单元测试覆盖率 ≥ 90% | `pytest --cov` |

### Phase 2 验收指标

| # | 指标 | 验证方法 |
|---|------|----------|
| P2-1 | `skill_optimization` feature 注册到 `ALL_FEATURES` | 单元测试：`assert "skill_optimization" in ALL_FEATURES` |
| P2-2 | `dream` trigger 的默认 feature 集包含 `skill_optimization` | 单元测试：`resolve_features("dream")` 包含 `skill_optimization` |
| P2-3 | 新 `skill_review` trigger 可解析 | 单元测试：`resolve_features("skill_review")` 包含 `skill_optimization` |
| P2-4 | `skill_optimization` feature 的 tools 不依赖新加 search 参数 | 单元测试 / 代码审查：不出现 `topic_prefix` 等不存在参数 |
| P2-5 | evidence builder 在 `skill_optimization` feature 激活时包含 `Trajectory Signals` 节 | 单元测试：调用 `build_evidence()` 验证输出 |
| P2-6 | evidence 不包含任何用户原文或 assistant 原文 | 单元测试：验证输出不含对话内容 |
| P2-7 | `apps/reflect/prompts.py` 明确记录 `world.skills.optimization.*` 主题规则 | 单元测试 / 文档断言 |

### Phase 3 验收指标

| # | 指标 | 验证方法 |
|---|------|----------|
| P3-1 | `write_optimization_candidate()` 写入 PM fact 后可通过 exact topic 查询到 | 单元测试：写入后 search 验证 |
| P3-2 | 写入的 PM fact topic 符合 `world.skills.optimization.{target_scope}.{candidate_key}` 或 `world.skills.optimization.new.{candidate_key}` 格式 | 单元测试 |
| P3-3 | 写入的 PM fact 使用 `recall_policy=review` 且 metadata 包含 `retention_lifecycle=draft` | 单元测试 |
| P3-4 | `mark_candidate_review_status()` 只允许 `pending -> approved`、`pending -> rejected`、`approved -> applied` | 单元测试：非法转换抛异常 |
| P3-5 | `apply_approved_optimization()` 仅对 authored skill 调用 `tool.skill.manage action=update` | 单元测试：mock authored / non-authored skill |
| P3-6 | 非-authored skill 的 approved candidate 不会触发 apply，状态保持为 approved | 单元测试 |
| P3-7 | rejected candidate 被保留且后续相同 `candidate_key` 会被 suppress | 单元测试 |
| P3-8 | 对候选进行 `correct` / `delete` / `restore` 前必须先拿到 exact ref | 单元测试：缺 ref 场景报错 |
| P3-9 | optimization candidates 不进入 core prompt | 集成单测：验证 generation context 不渲染这些 facts |

### Phase 4 验收指标

| # | 指标 | 验证方法 |
|---|------|----------|
| P4-1 | 端到端：10+ 含相似 tool 序列的 episode → `skill_review` reflect → 输出至少 1 条 optimization candidate | 集成测试 |
| P4-2 | 端到端：optimization candidate 写入 PM fact → Dashboard PM map 可见 | 手动验证 / E2E 测试 |
| P4-3 | 端到端：approved candidate → `tool.skill.manage update` 更新 authored skill instruction_text | 集成测试 |
| P4-4 | 端到端：skill 更新后，下次 `tool.skill.view` 返回更新后的内容 | 集成测试 |
| P4-5 | 端到端：approved candidate 指向非-authored skill 时，不会调用 `tool.skill.manage update` | 集成测试 |
| P4-6 | CLI `elephant reflect --trigger skill_review --features skill_optimization` 执行成功 | 手动验证 |
| P4-7 | Signal 提取在 30 个 episode 内完成 < 5s | 性能测试 |
| P4-8 | 现有 7 个 feature 的测试不受影响 | `pytest tests/unit/reflect/` 全通过 |

---

## 5 总体验收指标（端到端）

### 5.1 功能验收

| # | 端到端场景 | 验收标准 |
|---|-----------|----------|
| E2E-1 | **跨 episode 模式发现** | 在 10 个历史 episode 中注入 `[terminal.exec, file.read, terminal.exec]` 序列，`skill_review` 触发后系统生成 `recurring_sequence` 类型候选 |
| E2E-2 | **优化候选持久化** | candidate 在 PM fact 表中以 `world.skills.optimization.*` topic 存储，且 `review_status=pending` |
| E2E-3 | **人工审核 → authored skill 更新** | operator 将 candidate 标记为 `approved` 后，系统调用 `tool.skill.manage action=update` 将建议写入 authored skill instruction |
| E2E-4 | **非-authored skill 保护** | approved candidate 若指向非-authored skill，只保留建议，不执行 apply |
| E2E-5 | **隐私保护** | candidate 的 summary、PM fact text、evidence 中均不包含任何用户对话原文或 tool 参数 |
| E2E-6 | **Dream 整合** | `dream` trigger 触发时 `skill_optimization` feature 自动激活，与 `skills`、`diary` 并行执行 |
| E2E-7 | **无 skill 匹配 → 新 skill 建议** | 无 active affinity 匹配的 recurring sequence 生成 `world.skills.optimization.new.{candidate_key}` 候选 |
| E2E-8 | **Rejected suppression** | 已 rejected 且证据未显著变化的候选，在后续 reflect 中不会重复生成 |
| E2E-9 | **Approved apply 审计** | 候选被成功 apply 后状态变为 `applied`，且审计记录仍可查询 |

### 5.2 质量验收

| # | 指标 | 标准 |
|---|------|------|
| Q-1 | 新代码单元测试覆盖率 | ≥ 85% |
| Q-2 | 现有 reflect 单元测试 | 全部通过，无回归 |
| Q-3 | Lint | `make agent-lint` 通过 |
| Q-4 | Signal 提取层无新引入的 LLM 调用 | `extract_trajectory_signals()` 与聚合模块全程纯 Python |
| Q-5 | PM fact 存储遵循现有 governance | lens/topic/metadata 通过现有验证 |
| Q-6 | optimization candidates 不进入 core prompt | generation context 渲染中不可见 |
| Q-7 | 不依赖不存在的 PM search 参数 | 代码与 SOP 中不出现 `topic_prefix` / wildcard topic 假设 |

### 5.3 架构验收

| # | 指标 | 标准 |
|---|------|------|
| A-1 | Feature-composition 架构不变 | `skill_optimization` 通过标准 `Feature` dataclass 注册 |
| A-2 | 现有 feature 无侵入式重写 | 不将 trajectory 提取逻辑并入 `skills` / `dream` 原 SOP |
| A-3 | 信号提取层与 reflect runner 解耦 | `packages/reflect/` 可独立调用 |
| A-4 | 新 trigger 不影响现有 trigger | `skill_review` 不改变 `episode_close` / `manual` / `dream` 行为 |
| A-5 | Operator 边界清晰 | 自动化只能生成 / 推进候选；只有 approved + authored skill 才能 apply |

---

## 附录 A：与 Hermes Agent 设计的对照

| 设计要素 | Hermes Agent | Elephant Agent 本方案 |
|----------|-------------|---------------------|
| 信号来源 | 当前会话（Background Review Fork） | 跨 episode 历史 trajectory |
| 信号分类 | 用户纠正、工作流修复、技巧、过时 | recurring_sequence、error_recovery、tool_combination、skill_gap、outdated_pattern |
| 候选持久化 | 偏 skill 文件与 provenance 侧 | PM fact `world.skills.optimization.*` |
| 生命周期 | active → stale → archived | pending → approved → applied / rejected |
| 触发时机 | 每 N 次 tool 调用 / idle curator | dream/空闲时段 + 手动 `skill_review` |
| 优先级策略 | 更新已有 skill > 创建新 skill | 更新已有 skill > 创建新 skill |
| 自动 apply 边界 | 依实现而定 | 仅 authored skill + operator approval |

## 附录 B：数据流

```
Closed Episodes
    │
    ├── Steps (call_tool, metadata.tool_name, status)
    ├── Loops (outcome)
    │
    ▼
[Phase 1] Trajectory Signal Extraction
    │
    ▼
ToolTrajectorySignal[]
    │
    ▼
[Phase 1] Candidate Aggregation
    │
    ▼
SkillOptimizationCandidate[]
    │
    ▼
[Phase 2] Evidence Building
    │
    ▼
Reflect Agent Evidence Packet
    │
    ▼
[Phase 3] PM Fact Write
    │
    ├── pending candidate
    │     topic = world.skills.optimization.{target_scope}.{candidate_key}
    │     recall_policy = review
    │     retention_lifecycle = draft
    │
    ▼
[Operator Review]
    │
    ├── approved ──┬─ authored skill ──► tool.skill.manage update ──► review_status=applied
    │              └─ non-authored skill ──► retain approved candidate only
    │
    └── rejected ──► retain for audit + suppress future duplicate generation
```
