# AI CLI 集成与解析自改进 — 设计

日期：2026-06-10
状态：已确认（brainstorming）

## 目标

给 w3xtool 加入 AI CLI（claude code / codex / opencode 等）集成，用途两类：

- **开发期自改进**：AI 对地图解析的「诊断报告」做归因，提出修复补丁 / 提示词 / md 文档草稿，**人工审阅后应用**。
- **运行时增强**：解析地图后，AI 解释 / 标注结果中的异常（**只读标注，绝不修改解析代码**）。

## 关键决策（brainstorming 结论）

1. **面向对象**：开发者自改进 + 终端用户运行时（分两期做）。
2. **质检机制**：**工具自查 + AI 归因**。把现有 `tools_audit.py` 升格为 `audit.py` 产出结构化诊断；AI 只对「诊断报告 + 源码」做归因。**不**让 AI 直接解析二进制 MPQ（不可行），**不**做差分参考实现（慢/重/依赖外部库）。
3. **CLI 接入**：**通用命令模板 + 三个预设**（claude/codex/opencode）。登录交给各 CLI 自己（用户先在终端登录好），本工具只存命令模板，不碰密钥。
4. **自改尺度**：**AI 提补丁 + 人工应用**。AI 不直接改代码，产出存到审阅目录，走现有 git + 测试门禁。

## 架构（三阶段，按 1a → 1b → 2 顺序建）

### Phase 1a — 共享 AI-CLI 调用层 + 诊断模块（核心，无 GUI）

- `w3xtool/aicli/runner.py`
  - `AIProfile`：`{name, command, cwd, timeout, input_mode}`，`command` 为参数列表，含占位符 `{prompt}` / `{prompt_file}`；`input_mode ∈ {arg, stdin, file}`。
  - `run_ai(profile, prompt) -> AIResult{ok, stdout, stderr, exit_code, duration}`：渲染命令 → `subprocess` → 超时/捕获。prompt 过大时走临时文件（`{prompt_file}`）或 stdin。
- `w3xtool/aicli/config.py`
  - 内置 `PRESETS`（claude/codex/opencode 命令模板）。
  - `load_config()/save_config()`：profiles + 当前选择，存 `~/.w3xray/ai_config.json`（与现有设置一致的位置）。
- `w3xtool/audit.py`
  - `audit_map(path) -> MapDiagnostic`：结构化诊断（各类别计数、文件存在但 0 对象、裸 ID 率、解析告警、编码/压缩标志、file 类型覆盖、脚本/指令/配方数）。
  - `batch_audit(dir) -> list`。`tools_audit.py` 改为薄包装调用本模块。
- `prompts/`（版本化提示词目录）
  - `attribution.md`：开发期归因提示词（输入诊断报告 + 源码摘录 + WC3 格式要点，要求输出「疑似漏解析点 + 具体修复 diff + md 草稿」）。
  - `annotate.md`：运行时标注提示词（要求只解释/标注异常，不提代码改动）。

### Phase 1b — 设置 UI + 开发自改进流程

- GUI 加「设置」入口（对话框）：AI profiles 增删改、测试连通按钮、选当前 profile、提示词目录路径。登录提示「请先在终端登录对应 CLI」。
- 开发自改进流程（脚本或 GUI 开发按钮）：`audit` → 组装 prompt（报告 + 相关源码摘录 + 格式参考）→ `run_ai` → 把 AI 产出（patch / md 草稿 / 提示词改进）存到 `ai_suggestions/<日期>/`，**人工审阅应用**，不自动改代码。

### Phase 2 — 运行时用户增强

- 解析一张图后，若启用 AI 且选了 profile：**opt-in** 触发 → `audit` 本图 → `annotate` 提示让 AI 解释/标注异常 → 结果显示在面板。
- 用户机器上**只做结果层标注**，绝不自改解析代码。显示耗时/费用提示。

## 数据流

```
开发期：地图 → audit.py → 诊断报告 → prompt(报告+源码摘录+格式参考) → runner → AI
        → ai_suggestions/<date>/{patch.diff, notes.md} → 人工 review + 应用 → 测试门禁
运行时：地图 → load_map + audit → annotate prompt → runner → 标注文本 → GUI 面板
```

## 安全 / 边界

- 运行时**绝不**自改代码（只读标注）。
- 开发期 AI 产出存 `ai_suggestions/`，人工 review + 应用，走现有 82 测试门禁。
- **不**把地图二进制直接喂 AI（太大/无意义）；只喂诊断报告 + 必要源码摘录。
- 密钥/登录不由本工具管（交各 CLI），配置只存命令模板与路径。
- 子进程：强制超时、捕获 stdout/stderr、错误优雅降级（AI 不可用不影响正常解析）。

## 测试策略

- `runner`：用一个**假 CLI**（echo / 小 python 脚本）验证模板渲染、stdin/arg/file 三种输入、超时、退出码与 stdout 捕获——不依赖真实 AI、可离线跑。
- `config`：预设加载、存取往返、缺省/损坏配置容错。
- `audit`：用现有已知图断言诊断字段（counts、0对象文件检测、裸ID率）。
- UI / 运行时：冒烟测试（设置对话框可建、字段读写）。

## 不做（YAGNI）

- 不做差分参考实现（慢/重/外部依赖）。
- 不做 AI 全自动改代码（风险高、可能过拟合单图）。
- 不直接调 LLM API（只走用户已有的 CLI）。
- 运行时不自改解析逻辑。

## 本次起步范围

Phase 1a 先做完整并上线验证（runner + config + audit + prompts，全部带测试），再决定 1b / 2。
