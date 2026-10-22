# GUI 交互惯例（详版）

> 摘要见 AGENTS.md「GUI 惯例纪律」七条；本文件给每条纪律配代码锚点，
> 新增 GUI 面时按锚点对照既有实现，不要重新发明。

## 1. 全持久化（fail-open）

- 进程级记忆字典 → 磁盘：`gui_pack_query.py` 的 `_save_memo/_load_memo`
  （写 `cache/gui-query-memo/{history,pinned,geometry}.json`，坏格式当空白）。
- 包目录记忆：`gui_export_actions.py` 的 `load_last_pack_dir/save_last_pack_dir`
  （写 `cache/gui-last-pack.txt`）。
- 规则：写失败静默降级（pass + 注释），绝不因记忆失败打断主流程。

## 2. 状态即视觉

- 地图相关按钮（minimap/guide/pack_query）启动即禁用：
  `gui_topbar.py` 顶栏创建处；`gui_lifecycle.py` `_render_map` 统一启用。
- 点击防御分支保留（双保险），但不要依赖它当唯一状态管理。

## 3. 语义命令智能路由

- `gui_shell_object_panel.py` `_pack_query_selected(host, command)`：
  技能→skills、单位+where→drop 反查、增益→buffs、科技/装饰物→doc。
- 新增语义命令时在此处加分支；CLI 侧对应 `pack_query_cli._code_home_hint`
  （miss 时提示改道命令）。

## 4. 否定输出必须带出路

- 总量提示（本图共 N 件）：`_query_item/_query_price/_query_shop/_query_tech`
- 改道命令（用 skills 查）：`_code_home_hint` + where/drop 互指
- 数据源指引（见哪个 TSV）：`_query_cmd/_query_refs`
- 部分命中明细（已出现码引用数）：`_query_locate`
- 口径：未找到 ≠ 死胡同；每处否定 return 前自问"用户接下来能干什么"。

## 5. 键盘流

- Ctrl+1..8 切模式 + 动态 placeholder：`gui_pack_query.py` `_switch_mode/_PLACEHOLDERS`
- 回车执行当前模式（非固定 doc）：`_run` 绑定处
- Ctrl+F 内搜（回车循环跳转+选区高亮+尾部回卷）：
  `gui_pack_query.py` `_find_next`、`gui_topbar.py` `_find_next`（攻略速查）
- Esc 关闭：两弹窗 `bind("<Escape>", ... destroy)`
- 空词防护：`_run` 开头按模式清单拦截（doc/export/search/diff 必填）。

## 6. 定位双通道

- 长文本区（结果/报告）必须有：段落快跳按钮条 + Ctrl+F 内搜。
- 当前段高亮：`gui_topbar.py` `_mark_active`（激活段实色，其余描边）。
- 内搜起点状态机：所有会改写输出内容的代码点（新查询/导出追加/清空）
  都必须重置 `_find_state["start"]`——加输出变更点时对着 grep `_find_state`。

## 7. 记忆层级取舍

- 用户资产（历史/收藏/包目录）→ 落盘 `cache/gui-query-memo/`
- 会话性状态（滚动位置/上次关键词/结果文本）→ 进程级字典
- 判据：重启后用户会不会期望它还在？会→落盘；不会→进程级。
- 落盘写点：查询执行/收藏变更/清空操作后调 `_save_memo()`。

## 8. 内容窗口标配（新弹窗 checklist）

- [ ] 标题带上下文（地图名/包名）
- [ ] 尺寸记忆（`_WINDOW_GEOMETRY`）
- [ ] 等宽字体结果区 + 右键复制/导出 .md
- [ ] 段落/结果定位双通道
- [ ] Esc 关闭 + grab_set 模态
- [ ] 长任务走 `_start_gui_worker`（后台不冻 UI，完成 `_post_gui_worker` 回主线程）
- [ ] stderr 耗时行展示（分隔线包裹）
