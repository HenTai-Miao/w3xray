# SLK 字段可读性设计（收尾会话12）

> 会话12 让 SLK 优化图的对象显示真实字段，但一个对象会堆 ~70 列：含编辑器噪声列
> （comments/version/sort/code…）和一堆英文裸列名（Cast2/DataA1/BuffID1）。本次纯展示层
> 改进，借鉴工具包 `Config.ini [AlwaysEmpty]`（每个 SLK 文件可丢弃的编辑器列清单）。

承接 [[references-feature]] / `slk_objects.py`。只动展示层，不碰解析。

## ① 隐藏编辑器噪声列（来自 [AlwaysEmpty]，按分类）
`SLK_NOISE_COLS = {分类: set(噪声列)}`，取自 `[AlwaysEmpty]`：
- 技能：comments,version,useInEditor,hero,item,sort,race,InBeta
- 物品：comments,scriptname,version,InBeta
- 增益：comments,isEffect,version,useInEditor,sort,race,InBeta
- 可破坏物：comments,EditorSuffix,InBeta,version
- 装饰物：comment,InBeta,version
- 科技：comments,sort,version,InBeta
- 单位：sort,comment,comments,InBeta,version,sortBalance,sort2,sortUI,inEditor,hiddenInEditor,sortWeap,sortAbil
- 全类再加冗余 `code`（对象自己的码）。
`api._add_slk_objects` 构建/增补字段时跳过这些列。

## ② 等级后缀列的中文标签
`SLK_BASE_LABELS = {基名: 标签}`：Cast→施法间隔、Cool→冷却、Cost→魔法消耗、Dur→持续时间、
HeroDur→英雄持续、Area→作用范围、Rng→施法距离、BuffID→buff效果、EfctID→效果、
UnitID→召唤/创建单位、DataA..I→数据A..I、targs→目标类型、Requires→依赖、dmgplus→攻击力加成。
`slk_col_label(col)` 升级：
1) 精确表 SLK_COL_LABELS 命中→用之；
2) 否则末位是数字且去掉后基名在 SLK_BASE_LABELS → `「基名标签 (等级N)」`；
3) 都不中→原样列名（不乱改未知列）。
为一致性：把 SLK_COL_LABELS 里带等级的精确项（Cost1/Cool1/Area1/Dur1/Cast1/Rng1）删掉，统一走后缀逻辑。

## 测试 tests/test_slk_objects.py（补充）
- `slk_col_label`：精确(Name)/后缀(Cast2→施法间隔(等级2)、BuffID1→buff效果(等级1))/未知(原样)。
- 噪声过滤：合成 SLK 含 comments/code/version → 构建后这些标签不出现。
- U9 真图：AHbz 字段数较会话12下降、且不含「数据来源」之外的 code/comments；含中文等级标签。

## 诚实边界
- 噪声列严格只取 [AlwaysEmpty] + code，不擅自再删（checkDep/Buttonpos/Animnames 等保留原样列名，
  宁可多显示也不误删有意义字段）。
- 不改解析、不改引用抽取（BuffID1/UnitID1 等仍正常进引用图）。
