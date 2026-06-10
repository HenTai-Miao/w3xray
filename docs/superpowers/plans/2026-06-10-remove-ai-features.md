# 删除全部 AI + 本地诊断功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「魔兽地图提取器」回退成纯提取/浏览工具，删除所有 AI 调用层与只为喂 AI 而存在的本地诊断层。

**Architecture:** AI 与诊断是上层附加物，只有 `w3xtool/gui.py` 引用它们；底层提取链路（mpq/api/w3obj/...）零依赖。删除 = 整删独立模块/测试/提示词 + 在 `gui.py` 摘掉两段连续方法块和若干 UI 钩子 + 清理 README 与打包 spec。

**Tech Stack:** Python 3.14、customtkinter、pytest、PyInstaller、uv。

**前置事实（已核实）：** 除 `gui.py` 外无任何保留源码 import `audit`/`aicli`；除被删测试外无任何保留测试 import 它们；无 conftest。故删除是隔离的。

---

### Task 1: 删除 AI 调用层、诊断层、提示词、相关测试与 AI 设计文档（整文件删除）

**Files:**
- Delete: `w3xtool/aicli/__init__.py` `w3xtool/aicli/autopt.py` `w3xtool/aicli/config.py` `w3xtool/aicli/improve.py` `w3xtool/aicli/runner.py`
- Delete: `w3xtool/audit.py` `tools_audit.py`
- Delete: `prompts/annotate.md` `prompts/attribution.md` `prompts/autopt.md`
- Delete: `tests/test_aicli_autopt.py` `tests/test_aicli_config.py` `tests/test_aicli_improve.py` `tests/test_aicli_runner.py` `tests/test_gui_ai.py` `tests/test_audit.py`
- Delete: `docs/superpowers/specs/2026-06-10-ai-cli-self-improvement-design.md`

- [ ] **Step 1: 用 git rm 删除所有上述文件（含整目录）**

```bash
git rm -r w3xtool/aicli prompts \
  w3xtool/audit.py tools_audit.py \
  tests/test_aicli_autopt.py tests/test_aicli_config.py tests/test_aicli_improve.py tests/test_aicli_runner.py \
  tests/test_gui_ai.py tests/test_audit.py \
  docs/superpowers/specs/2026-06-10-ai-cli-self-improvement-design.md
```

- [ ] **Step 2: 确认这些路径已不在版本控制中**

Run: `git status --short`
Expected: 上述文件均显示为 `D`（deleted），`w3xtool/aicli/` 与 `prompts/` 目录下无残留。

- [ ] **Step 3: 暂不提交**（gui.py 仍 import 这些模块，整体导入会失败；与 Task 2 一起提交，保持每次提交可运行）

---

### Task 2: 从 `w3xtool/gui.py` 摘除全部 AI/诊断引用

**Files:**
- Modify: `w3xtool/gui.py`

> 注：行号为当前快照参考，编辑请用唯一字符串锚定（前一处编辑会使后续行号上移）。

- [ ] **Step 1: 删除 4 行 AI/audit import（当前 23–27 行）**

删除这一整段：

```python
from .aicli.config import load_config as load_ai_config, save_config as save_ai_config, \
    get_active as get_active_ai, AIConfig
from .aicli.runner import AIProfile, run_ai
from .aicli.improve import annotate as ai_annotate, attribute as ai_attribute
from .audit import audit_loaded
```

- [ ] **Step 2: 删除构造器里的 AI 状态初始化（当前 80–82 行）**

删除这三行：

```python
        self._ai_config = load_ai_config()   # AI CLI 配置（命令模板/当前选择）
        self._settings_win = None
        self._ai_busy = False                # AI 任务进行中标志（防并发 git 操作互相破坏）
```

- [ ] **Step 3: 删除顶栏「⚙ 设置」按钮（当前 108–110 行）**

删除这一段（设置对话框是纯 AI CLI 配置，按钮一并删）：

```python
        ctk.CTkButton(bar, text="⚙ 设置", font=(FONT, 13), width=70, height=38,
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self._open_settings).pack(side="left", padx=4)
```

- [ ] **Step 4: 删除顶栏「AI 质检」按钮（当前 113–115 行）**

删除这一段：

```python
        ctk.CTkButton(bar, text="AI 质检", font=(FONT, 13), width=84, height=34,
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self._on_ai_audit).pack(side="right", padx=6)
```

- [ ] **Step 5: 删除第一段连续 AI 方法块**

删除从注释 `# ---------- AI 设置 / 质检 ----------`（当前 126 行）起，到 `_on_ai_autopt` 方法体结束、`def _build_tabs(self):`（当前 424 行）之前的一整块。这一块包含且仅包含这些方法：`_open_settings` `_settings_find` `_settings_load_sel` `_settings_form_profile` `_settings_save_silent` `_settings_save` `_settings_new` `_settings_delete` `_settings_test` `_ai_suggestions_dir` `_ai_precheck` `_on_ai_audit` `_on_ai_attribute` `_on_ai_autopt`。删除后 `def _build_topbar` 的下一个方法应直接是 `def _build_tabs`。

- [ ] **Step 6: 在 `_build_tabs` 中删除「AI 质检」标签页（当前 439、443 行）**

删除这两行：

```python
        self.tab_ai = self.tabs.add("AI 质检")
```
```python
        self._build_ai_tab(self.tab_ai)
```

删除后 `_build_tabs` 末尾应为：

```python
        self.tab_obj = self.tabs.add("对象浏览")
        self.tab_cmd = self.tabs.add("隐藏指令")
        self.tab_rec = self.tabs.add("合成配方")
        self._build_obj_tab(self.tab_obj)
        self._build_cmd_tab(self.tab_cmd)
        self._build_rec_tab(self.tab_rec)
```

- [ ] **Step 7: 删除第二段连续 AI 方法块（当前 445–476 行）**

删除 `_build_tabs` 之后、`def _build_obj_tab(self, parent):` 之前的三个方法：`_build_ai_tab` `_ai_set_text` `_on_toggle_auto_audit`。删除后 `_build_tabs` 的下一个方法应直接是 `_build_obj_tab`。

- [ ] **Step 8: 删除解析后「自动质检」钩子（当前约 1069–1072 行）**

删除这段（注释 + if 块）：

```python
        # 解析后自动 AI 质检（opt-in，静默填充 AI 标签页）。
        # 仅在「真正新打开一张图」时触发；战役子图来回切换(fresh=False)不重复烧 AI。
        if fresh and getattr(self._ai_config, "auto_audit", False):
            self.after(100, lambda: self._on_ai_audit(auto=True))
```

- [ ] **Step 9: 删除关窗时的 AI 配置落盘（当前约 819–823 行）**

删除这段：

```python
        try:
            save_ai_config(self._ai_config)   # AI 配置也一并落盘，下次启动自动恢复
        except Exception:
            pass
```

- [ ] **Step 10: 校验 `gui.py` 无 AI 残留**

Run: `git grep -niE "aicli|audit|annotate|attribut|autopt|_ai_|质检|run_ai|AIProfile|AIConfig|_settings_win|_open_settings|auto_audit" -- w3xtool/gui.py`
Expected: 无任何输出。

- [ ] **Step 11: 校验模块可导入**

Run: `uv run python -c "import w3xtool.gui; print('ok')"`
Expected: 打印 `ok`，无 ImportError / SyntaxError。

- [ ] **Step 12: 跑全套测试**

Run: `uv run pytest -q`
Expected: 全绿（被删的 AI/诊断测试已不存在；其余测试不依赖被删模块）。

- [ ] **Step 13: 提交 Task 1 + Task 2**

```bash
git add -A
git commit -m "refactor: 删除全部 AI 调用层与本地诊断功能

- 删 w3xtool/aicli/、w3xtool/audit.py、tools_audit.py、prompts/
- gui.py 摘除 AI 设置/质检/自动优化 UI 与所有相关方法、标签页、钩子
- 删对应测试与 AI 自改进设计文档"
```

---

### Task 3: 清理 `README.md` 与打包 `魔兽地图提取器.spec`

**Files:**
- Modify: `README.md`
- Modify: `魔兽地图提取器.spec`

- [ ] **Step 1: 删除 README「AI 质检（可选）」整段（当前 48–50 行）**

删除以 `- **AI 质检（可选）**` 开头的那条及其下两条子项（`AI 质检当前图` / `解析后自动质检`）。

- [ ] **Step 2: 删除 README 功能表里的 `audit.py` 与 `aicli/` 两行（当前 65–66 行）**

删除：

```
| `audit.py` | 解析诊断：结构化"缺斤少两"信号（供 AI 归因 / 人工审阅） |
| `aicli/` | AI CLI 集成：`runner`(通用命令模板调用) / `config`(预设+存取) / `improve`(诊断→提示→调AI→存建议/标注) |
```

- [ ] **Step 3: 改 spec 的 datas（当前第 4 行）**

把：

```python
datas = [('prompts', 'prompts')]   # AI 提示词模板，运行时 AI 质检要读
```

改成：

```python
datas = []
```

- [ ] **Step 4: 校验 README/spec 无 AI 残留**

Run: `git grep -niE "aicli|audit|质检|prompts" -- README.md 魔兽地图提取器.spec`
Expected: 无输出。

- [ ] **Step 5: 全仓最终校验（docs 历史日志除外）**

Run: `git grep -niE "aicli|annotate|autopt|run_ai|AIProfile|质检" -- '*.py' '*.md' '*.spec' ':!docs/*' ':!task_plan.md' ':!findings.md' ':!progress.md'`
Expected: 无输出。

- [ ] **Step 6: 提交**

```bash
git add README.md 魔兽地图提取器.spec
git commit -m "docs: README 与打包 spec 移除 AI 质检相关内容"
```

---

## Self-Review

- **Spec coverage：** spec 列的整文件删除 → Task 1；gui.py 各编辑点（import/构造器/两个按钮/两段方法块/标签页/自动质检钩子/关窗落盘）→ Task 2 step 1–9；README 两处 + spec datas → Task 3。四条验证标准 → Task 2 step 11–12（import/pytest）、Task 2 step 6 后标签页变三个、Task 3 step 5（grep 无残留）。全覆盖。
- **Placeholder scan：** 无 TBD/TODO，删除步骤均给出确切锚定字符串与确切命令/期望输出。
- **Type consistency：** 纯删除，不引入新符号；每个被删方法名都在现有 gui.py 中存在并已逐一列出。
