# 内嵌 SLK 对象数据解析设计（slk_objects.py）

> 来源：「魔兽ID拖入无反应解决方法」工具包的本职是把对象数据转成 SLK 重打包
> （Wc3SLKOpt / Wc3MapMax++）。本工具能读二进制 .w3a/.w3u 与 INI 文本对象，
> 但读不了**内嵌的 *Data.slk 对象数据** → SLK 优化图(此工具包的产物)字段/引用读不全。
> 本次补上：让工具能完整 X 光这类图。承接 [[references-feature]]。

## 现状缺口（实证）
U9 失落的宿命图：自定义技能名字来自 `Units\*AbilityStrings.txt`(已解析)，但真正的字段数据
与引用(如 `AHwe → UnitID1:hwat` 召唤水元素)藏在 `Units\AbilityData.slk`(未解析)。
现有 `slk.py` 实测能干净解出(1271 技能)。

## 模块 w3xtool/slk_objects.py
- **分类 → SLK 文件**：
  - 技能=AbilityData.slk　物品=ItemData.slk　增益=AbilityBuffData.slk
  - 可破坏物=DestructableData.slk　科技=UpgradeData.slk　装饰物=Doodads.slk
  - 单位=UnitData.slk(+UnitBalance/UnitUI/UnitWeapons/UnitAbilities 同码合并)
  - 在 MPQ 里按 根 / `Units\` / `Doodads\` 不区分大小写查找。
- **每行 → 候选**：键=对象码(行键)；字段={SLK列名→值}(常用列给中文标签，其余原样列名)；
  WTS/WESTRING 在候选阶段解析，最终名字由统一对象管线从全部来源的获胜字段重建。
- **引用**：复用 `references.extract_refs_by_column(fields, 分类)`(上轮为文本对象做的，按 SLK 列名抽
  BuffID/EfctID/UnitID1/Requires…)，天生匹配 SLK 列。

## 合并语义（不重复计数）
- SLK、Func/Strings、二进制和基础对象先转换为不可变候选，再按 `(分类, 对象码)` 一次合并。
- SLK 补充二进制未修改的字段和引用；同一非显示字段由二进制获胜，显示字段由 Strings 获胜。
- 最终统一重建 `GameObject`、分类 bucket 和仅含真实 `obj_id` 的索引。
- 跳过明显的表头/非对象行(行键非 4 字符 / 等于列名占位)。

## 接入
- `map_loader.load_map` 先收集地图级与战役级全部候选，再调用一次统一对象管线；
  随后 `build_reference_graph` 使用最终 `ref_fields`。

## 价值与诚实边界
- 主价值：恢复 SLK 优化图的**字段数据 + 对象引用**；低覆盖自检多半 True→False。
- 次要：孤立误报进一步降；但若该图根本没带某类引用文件(如 UnitAbilities.slk)，那条边仍读不到，
  低覆盖提醒按实保留。

## 测试 tests/test_slk_objects.py
- 合成 SLK：行→对象、列→字段、引用列(BuffID/UnitID1)被 extract_refs_by_column 抽出。
- U9 真图断言：AbilityData.slk 解出 ≥1000 技能、`AHwe` 带 UnitID1 引用、合并后无重复码、技能有字段。

## 不做
- 不做 SLK 多级字段(DataA1/DataA2 的 metadata 后缀分级推导)精确还原——按列名原样展示足够 X 光；
  引用列(单值/逗号列表)已能抽。
- 不回写/不优化/不裁剪(改图越界)。
