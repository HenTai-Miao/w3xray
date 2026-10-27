> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# 六程序与GameXRay逐记录适配交叉表

基线：main@ac18ec8d6e02dc36103d6c43cc0de61a0f83ab4e；83个现源能力条目。所有目标原记录/效果/证据/限制在crosswalk.json中原样保留。

统计的单位分别是功能/架构记录、功能族/发现、callback、层级条目、控件、字段、编码事件和配置动作。它们相互重叠，不能合计为独立功能数量。

| 目标 | 分母类型 | 记录数 | 已有 | 可直接新增 | 需要适配 | 边界外 | 无法判断 |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | functional_or_architecture_record | 38 | 3 | 10 | 7 | 17 | 1 |
| 2 | functional_family_or_finding | 37 | 6 | 8 | 9 | 13 | 1 |
| 2 | hotkey_callback | 50 | 0 | 0 | 1 | 49 | 0 |
| 3 | hierarchical_entry | 1009 | 18 | 187 | 361 | 422 | 21 |
| 4 | serialized_ui_control | 82 | 4 | 0 | 0 | 55 | 23 |
| 5 | encoded_ui_event | 15 | 3 | 0 | 1 | 9 | 2 |
| 5 | functional_family | 18 | 4 | 2 | 2 | 9 | 1 |
| 5 | runtime_field_row | 69 | 8 | 0 | 61 | 0 | 0 |
| 5 | serialized_form_or_control | 35 | 3 | 1 | 2 | 8 | 21 |
| 6 | configured_action | 28 | 0 | 0 | 0 | 28 | 0 |
| 6 | unimplemented_dispatch_stub | 1 | 0 | 0 | 0 | 0 | 1 |

## 判定限制

- 已有表示当前项目有对应读取/检索/数据/交互能力，不表示同目标数据、地址、版本或格式覆盖完全相同。
- 可直接新增是本地只读设计/数据/界面建议；需要适配包括新版本布局、平台、格式、运行时字段和被动重建；两者均未实现。
- 混合记录的读取与修改另分components；不得让业务read标签掩盖hook、远端写命令或临时创建游戏对象。
- T4按已追到的写链与仅UI/引用证据分开；未知控件意图再清楚也不升级为已证游戏效果。
- T5 69字段另列：坐标2项和六槽物品ID6项有现能力对应，其余61项需要运行时布局适配；技能静态目录不等于实时槽位。
- 原协议容量、时间/扫描/节点/字符串经验上限不带回项目全覆盖契约；真实编码bound、物理槽位、身份/路径/分配guard继续保留。
- x64/Reforged句柄链仍pending；CASC静态目录/文件浏览不证明运行时支持。

## 报告入口

- crosswalk-by-target/target-1.md / .json：完整逐记录对照。
- crosswalk-by-target/target-2.md / .json：完整逐记录对照。
- crosswalk-by-target/target-3.md / .json：完整逐记录对照。
- crosswalk-by-target/target-4.md / .json：完整逐记录对照。
- crosswalk-by-target/target-5.md / .json：完整逐记录对照。
- crosswalk-by-target/target-6.md / .json：完整逐记录对照。
- crosswalk.json：全部原始记录、分类依据、当前精确file:line、提议增量、效果和限制。
- fit-priorities.md：高价值只读增量的落地次序。
- input-snapshots/：输入JSON原始快照；所有主报告SHA256在crosswalk.json中固定。
