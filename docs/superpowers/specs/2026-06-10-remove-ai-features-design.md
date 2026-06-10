# 设计：删除项目全部 AI + 本地诊断功能

日期：2026-06-10

## 目标

把「魔兽地图提取器」回退成纯粹的地图提取/浏览工具，删除所有 AI 相关功能，以及只为喂 AI 而存在的本地诊断层。删完后工具只保留：打开地图/战役、对象浏览、隐藏指令、合成配方、导出（全部文件/脚本/ID 列表）。

## 范围

### 整文件删除

| 路径 | 说明 |
|------|------|
| `w3xtool/aicli/`（`__init__/autopt/config/improve/runner`） | AI 调用层 |
| `w3xtool/audit.py` | 本地诊断（结构化「缺斤少两」信号，只为喂 AI/人审） |
| `tools_audit.py` | 诊断命令行入口 |
| `prompts/`（`annotate.md/attribution.md/autopt.md`） | AI 提示词模板 |
| `tests/test_aicli_autopt.py` `test_aicli_config.py` `test_aicli_improve.py` `test_aicli_runner.py` | AI 单测 |
| `tests/test_gui_ai.py` | GUI AI 交互测试 |
| `tests/test_audit.py` | 诊断单测 |
| `docs/superpowers/specs/2026-06-10-ai-cli-self-improvement-design.md` | AI 自改进设计文档 |

### 编辑 `w3xtool/gui.py`

- 删除 AI/audit 的 import（`from .aicli.* import ...`、`from .audit import audit_loaded`）。
- 删除构造器里 `_ai_config = load_ai_config()`、`_settings_win`、`_ai_busy` 的初始化。
- 删除顶栏「AI 质检」按钮；删除「⚙ 设置」按钮（设置对话框纯粹是 AI CLI 配置，一并删）。
- 删除所有相关方法：`_open_settings` 及其内部辅助（保存/测试/增删 profile）、`_on_ai_audit`、`_on_ai_attribute`、`_on_ai_autopt`、`_ai_precheck`、`_ai_suggestions_dir`、`_ai_set_text`、`_on_toggle_auto_audit`、`_build_ai_tab`。
- 删除「AI 质检」标签页：`self.tabs.add("AI 质检")` 与 `_build_ai_tab(...)` 调用，标签页从四个变三个。
- 删除解析后「自动质检」钩子（`if fresh and ... auto_audit: self.after(..., _on_ai_audit(auto=True))`）。
- 删除关窗时 `save_ai_config(self._ai_config)` 落盘。
- 保留：窗口几何/目录持久化走独立的 `_load_config/_save_config`，与 AI 配置无关，完全不动。

### 编辑 `README.md`

- 删除「AI 质检（可选）」整段（功能列表里那几条）。
- 删除功能表里 `audit.py` 和 `aicli/` 两行。

### 编辑 `魔兽地图提取器.spec`

- `datas = [('prompts', 'prompts')]` → `datas = []`（prompts 目录已删，不再打包）。

### 不改动

- `task_plan.md` / `findings.md` / `progress.md`：整个工具的历史规划日志，不是 AI 功能本身。
- 纯提取链路：`api / mpq / w3obj / slk / blp / wts / westrings / fields / base_names / base_objects / explode / huffman / icons / script_scan / search / textobj` 全部不碰。

## 验证标准

1. `uv run pytest` 全绿——剩余测试不依赖任何被删模块（删测试前先确认没有跨文件 import）。
2. `python -c "import w3xtool.gui"` 无 ImportError。
3. GUI 启动后顶栏只剩「打开地图/战役 + 导出三件套」，标签页只剩「对象浏览 / 隐藏指令 / 合成配方」。
4. `git grep -niE "aicli|audit|annotate|autopt|质检"` 在源码/测试/README/spec 中无残留（docs 历史日志除外）。
