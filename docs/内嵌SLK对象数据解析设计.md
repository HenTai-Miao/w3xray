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
- **每行 → 对象**：键=对象码(行键)；字段={SLK列名→值}(常用列给中文标签，其余原样列名)；
  名字优先取已解析 txt 对象名 → SLK `Name` 列(WESTRING/wts 还原) → base_names → 码。
- **引用**：复用 `references.extract_refs_by_column(fields, 分类)`(上轮为文本对象做的，按 SLK 列名抽
  BuffID/EfctID/UnitID1/Requires…)，天生匹配 SLK 列。

## 合并语义（不重复计数）
- 码已在 `obj_index`(来自二进制 .w3a 或 txt) → **增补**：SLK 字段/引用并进现有对象，名字保留原有。
- 码不存在 → 新建 `GameObject(ext='slk')`，并入对应分类与 obj_index。
- 跳过明显的表头/非对象行(行键非 4 字符 / 等于列名占位)。

## 接入
- `api.load_map`：`_add_text_objects`/`_add_binary_objects` 之后加 `_add_slk_objects(md, archive, wts)`；
  随后 `build_reference_graph` 自动吃到新 ref_fields。

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
