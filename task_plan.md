# 任务计划：魔兽地图提取工具

## 目标
用 Python（uv 管理）从零实现一个魔兽争霸 III 地图提取工具，最终打包成**单文件 exe 的图形界面程序**：
1. 把地图（MPQ 压缩包 .w3x/.w3m）解包出内部文件
2. 解析对象数据，提取 单位 / 物品 / 技能 / 科技 等信息（id + 名称 + 字段）
3. 提取地图脚本 war3map.j / war3map.lua
4. 支持战役图 .w3n（嵌套 MPQ：内含多个 .w3x，递归解包）
5. **GUI：打开地图后可对 单位/物品/技能/科技 做模糊搜索，查看详细信息，界面美观舒适**
6. **用 PyInstaller 打包成 exe**

**用途：自己研究地图 / 学做地图。** 不涉及改存档、过反作弊、开图等作弊功能。

## 环境（已确认）
- Python 3.14.4（64 位），用 **uv 0.11.18** 管理
- StormLib.dll 是 **32 位**，64 位 Python 无法直接调 → 因此不用它，纯 Python 实现
- clang/clang++ 64 位可用（暂不需要）
- 测试地图：`C:/Program Files (x86)/Warcraft III/war3/Maps/魔兽争霸杂交版1.00d.w3x`（28MB）
  - HM3W 头 512 字节，MPQ 起始偏移 512，**格式 v0（经典 MPQ v1）**，扇区 4096B，hash 2048，block 1131

## 阶段
| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1: 项目与环境搭建 | complete | uv init、目录结构、规划文件 |
| Phase 2: MPQ 读取核心 | complete | 头部/表解密/查找/listfile，真实地图验证通过 |
| Phase 3: 解压与解包 | complete | zlib/bzip2/PKWARE explode 全部跑通，war3map.j 解出有效 JASS |
| Phase 4: 对象数据解析 | complete | w3u/w3t/w3a/w3q/w3b/w3d/w3h 全解析，缓冲完整消费 |
| Phase 5: 脚本提取 | complete | war3map.j/lua/wts/wtg/wct 文本导出 |
| Phase 6: 战役 .w3n 支持 | code-done | 递归解包已写，待真实 .w3n 验证 |
| Phase 7: 名称解析 | complete | wts + TRIGSTR 解析，中文名正确还原 |
| Phase 8: GUI（模糊搜索+详情） | complete | CustomTkinter 深色风，搜索/分类/详情/导出，冒烟测试通过 |
| Phase 9: 打包 exe | complete | PyInstaller 单文件 exe(13MB)，实测启动运行正常 |
| 备份 | complete | 地图提取工具_备份_v1_可用版（源码+exe） |
| Phase 10: 地形渲染 | complete | w3e 解析→俯视彩色底图(289x353)，湖/草/路/建筑可辨 |
| Phase 11: 放置单位+掉落 | complete | doo 212单位解析(剩余0字节)；本图无编辑器掉落(脚本控制)，已如实标注 |
| Phase 12: 地图视图GUI | complete | 画布平移缩放+200标记可点击，截图验证视觉效果良好 |
| Phase 13: 隐藏指令扫描 | complete | 扫出104条指令(含-isee/-kill等)，前缀/精确+脚本提示 |
| Phase 14: 重新打包 exe | complete | 单文件 exe(18.9MB)，含地图视图+指令，实测运行正常 |
| Phase 15: 原版名称表 | complete | 从游戏MPQ提取2028个 码→中文名，nckb→邪恶的科多兽等正确 |
| Phase 16: 多图物品测试 | complete | 测10张图：自定义物品全提取(最多1237)；0物品图是真无w3t(用原版/脚本物品) |
| Phase 17: 合成配方识别 | complete | script_scan.scan_recipes：YDWE移除料+添加成品锚点法；316821准确提2配方 |
| Phase 18: 重新打包 exe | complete | 单文件 exe(19.0MB)，4标签页(对象/地图/指令/合成)，实测运行 |

## 关键技术点
- MPQ 表用固定 crypt table 加密，需实现 hash/decrypt（标准算法）
- 文件按扇区存储，每扇区独立压缩，首字节是压缩方法掩码
- WC3 常用 PKWARE DCL implode（0x08）压缩 → 需自己实现 explode（移植 blast.c）
- 对象数据格式 w3u/w3t/w3a/w3q 有公开文档（original + custom 表）

| Phase 19: 全图提取排查 | complete | 诊断14张图：1张因w3a尾部4字节报错致整图加载失败 |
| Phase 20: 容错修复+重打包 | complete | 解析容忍尾部多余字节+单文件失败不拖垮整图；14图0崩溃0空白；exe(19MB) |
| Phase 21: 逆向box实现 | complete | PE分析：StormLib=读MPQ(已复刻对等)；Get.dll=注入游戏读内存(外挂核心,不复刻) |
| Phase 22: 脚本对象兜底 | complete | scan_object_refs按native类型提物品/单位码；41553CA6 0→451物品/433单位(183有名)；GUI标〔脚本〕 |
| Phase 23: $hex码+scripts\回退 | complete | 学密码查看器：支持$XXXXXXXX十六进制码(西方世界0→351物品/464单位)；MPQ查找回退scripts\子目录(1AC5F345脚本恢复);切图清空详情；exe(19MB) |
| Phase 24: CAME/KKWE保护图静态恢复 | complete | 千风物语：修复CAME头signed hash/block偏移；导出w3i/mmp/blp/空j + protected_blocks里的KKWE载荷、PE loader、匿名JASS loader、manifest；支持导入合法解密脚本/dump补提对象/指令/配方 |
| Phase 25: 搜索AND+OR + JetBrains字体 | complete | 四个搜索框支持空格=且/竖线\|=或；全局字体改 JetBrains Mono |
| Phase 26: 精简回归正常提取器 | complete | **删除**地图视图(mapview/w3e/doo/w3i)、运行时提取器(runtime_dump/CLI/spec/exe)、整套千风/保护图子系统(CAME头恢复/KKWE静态恢复/匿名block/外部解密脚本/describe_extraction/analyze命令/protected字段)；删保护图测试。工具回归纯粹"正常未加密地图提取器" |

| Phase 27: 评审优化(TDD) | complete | 修路径穿越(_safe_export_path)、解压炸弹封顶(_decompress_sector/explode max_output)、消除重复打开MPQ(commands_from_map/recipes_from_map复用md.scripts)、异常打日志、打包关UPX+excludes；测试 0→14 例全过 |
| Phase 28: BLP向量化+补测试(TDD) | complete | BLP调色板解码改PIL"P"模式(43x提速,输出一致)；fuzzy_score抽到search.py；补 w3obj/textobj/search/blp 单测；测试合计 36 例全过 |
| Phase 29: MPQ头DoS硬化+游戏MPQ缓存(TDD) | complete | _validate_header 拒绝非法表大小(hash非2的幂/越界/4billion卡死)；icons._open_game_mpq 进程级缓存大档(57ms→0.002ms)；测试 40 例全过 |
| Phase 30: 打包 onefile→onedir | complete | spec 改 COLLECT，产物 dist/魔兽地图提取器/(exe+_internal)，消除启动期 ~20MB 临时解压；窗口 1.77s 出现；分发改打 zip 文件夹 |
| Phase 31: 战役(.w3n)完整提取(TDD) | complete | A:war3campaign.*共享对象(206774:2050个) B:子地图浏览+三页切换+图标跨档查找 C:export递归子图内部+全部导出改写TMP(tmp_extract_dir)。端到端实测7子图可切换；测试46例全过 |
| Phase 32: UI两级导航+美化 | complete | 一级「对战图｜战役图」分段控件；左侧列表按模式切(对战=文件夹图/战役=共享+子图)，撤顶栏下拉；树行高32/字号11/滚动条/默认窗口1380详情可见；_LAYOUT_VERSION 守卫旧分隔条；测试47例全过 |
| Phase 33: 战役图选择目录+树形列表 | complete | 战役图也加「选择地图目录」；左侧改树形：目录里 .w3n 战役为父节点，展开懒加载列出子地图(★共享+各关卡)；_scan_dir 拆分对战图/战役；_node_map+_on_tree_open+_load_campaign_node；测试49例全过 |
| Phase 34: 目录/交互细节(用户反馈) | complete | 每模式各记目录各扫列表(不互相覆盖)+两模式目录持久化；战役选目录零解析(点战役才加载)；左侧地图列表改双击加载；右键复制/粘贴(_attach_ctx_menu)；测试51例全过 |
| Phase 35: 子图脚本引用取共享真名+全图审计 | complete | _add_script_refs 加 shared_index 回退(子图引用 war3campaign.* 对象显示真名,XSHZ-1光秃秃33→0)；逐文件审计2战役+对战图:对象文件零失败/名字解析96~99%/无漏掉的数据文件类型；测试52例全过 |
| Phase 36: 去无名原版对象噪声 | complete | _add_base_objects 跳过无显示名的原版对象(BASE_OBJECTS有但*Strings没名的6个系统内部码 edol/Ansp等)；战役子图光秃秃清零；测试54例全过 |
| Phase 37: 补评审缺口 | complete | Lua FourCC("xxxx")识别;聊天指令支持...ChatEventBJ封装;_build_objects失败打告警不全静默;explode实测占0%划掉;测试62例全过 |
| Phase 38: 表格右键复制 | complete | _attach_tree_copy/_copy_tree_row：隐藏指令/合成配方/对象四列 右键复制选中行到剪贴板；测试65例全过 |
| Phase 39: 搜索竖线两侧空格修复 | complete | "敏捷 \| 全属性" 因先按空格切分,竖线被切成独立 token 后丢弃→退化为 AND；search.py 切分前先吃掉竖线两侧空格；测试67例全过 |
| Phase 40: 对象格式版本3兼容(初版) | complete | 新编辑器(1.32+/重制版)存的 w3u/w3t/w3a… 格式版本3：旧解析错位致整文件丢弃只剩脚本；初版按"跳过8字节"处理(仅 sets==1 正确)；村庄守护者152 由0对象→单位677/物品433/技能882…；测试71例全过 |
| Phase 41: 版本3 sets 分组正解(deep-research校正) | complete | superpowers 深度研究(99 agents,3票对抗验证)查权威实现 mdx-m3-viewer：版本3 是 oldId+newId 后先读 **sets 数量**,再循环每个 set=setsFlag(u32 位掩码,HD/SD皮肤分组)+该set修改数+修改项。"跳过8字节"只在 sets==1 成立。w3obj 改成真正的 sets 循环,把各 set 的 mods 全收进对象；Downloads 23 张图实测 22 成功(剩1张 Zombie_Defense_w3p 是 1337 混淆保护图,与千风同类,不支持);maxsets 实测均为1但代码已健壮支持>1。测试72例全过 |
| Phase 42: 指令提示 TRIGSTR 还原 | complete | 实测狼人图 -brewing 提示显示 TRIGSTR_3482 未还原；commands_from_map 用 md.scripts 里的 war3map.wts 解析字符串表,把指令提示的 TRIGSTR_n 查回真文本(_map_wts+resolve);狼人图24条指令 TRIGSTR 未解析 0；测试74例全过 |
| 研究结论存档 | note | MPQ 容器**所有 WC3 版本恒为 v1**(无需分版本分支),HM3W 包裹头通用;压缩按扇区掩码字节派发(zlib0x02主,PKWARE0x08,bzip2,huffman/adpcm音频)与游戏版本无关;w3i 版本阈值18/25/28/31/33(脚本JASS/Lua由v28+ scriptMode标识,本工具读 .j/.lua 已覆盖);对象数据 sets 是唯一版本特有的对象层分支 |

> **会话 4 起范围调整**：放弃加密保护图(千风物语类)提取，移除地图视图与运行时 dump。Phase 6/10-14/24 相关功能已删除，仅保留正常地图的对象/脚本/指令/配方提取与导出。

## 错误记录
| 错误 | 尝试 | 解决 |
|------|------|------|
| 地图视图全黑(只剩角落小红点) | 默认在对象页加载时画布宽高=1，按1px适配后不再刷新 | 画布宽≤1时不适配，绑 `<Configure>`/`<Map>` 待显示后自动适配；已重打包验证 |
| 地图视图平移卡顿/放大卡死 | 平移每次都重缩放+重建200标记；放大无上限致图片上亿像素 | 平移改 `canvas.move("all")` 不重绘；缩放上限≈11x(图≤4000px)；实测平移30步200ms |
| 部分图整体提取不出(加载失败) | 某些工具存的对象文件末尾多4字节，解析报"剩余字节"且未捕获→整图崩 | parse_object_data不再因尾部字节抛错；_build_objects每文件try兜底；14图全部成功 |
| 大量图物品/单位/技能全提不出(显示0或仅代码) | 这些图把对象数据存成"文本INI档"([码]Name=Tip=Ubertip=)，文件名非标准、我只读二进制w3t→全漏 | 新增textobj.py：按内容(非文件名)识别文本对象档+解析+按段首字母分类；14图全部带中文名提全(誓约0→910物品/686单位，西方世界650物品全描述) |
| 诸界竞拍之王物品列空(分类靠代码首字母,小写码afac判错) | classify只认I开头=物品，afac/amrc等小写码判成单位 | classify改"字段特征+默认物品"(单位看Propernames/Trains,技能看Order/TargetArt,科技R码)；全图0空列 |
| 大量对象只显示代码无名(文本路径没回退基础名表) | _add_text_objects只取Name字段,没回退BASE_NAMES | 文本路径补BASE_NAMES回退+EditorSuffix+*Func.txt；无名从几百→各图0~8个 |
| 可破坏物名显示WESTRING_DEST_..常量(超长名) | jass.slk加载游戏WorldEditStrings解析编辑器字符串 | 生成westrings.py(8065条)并在名称/字段解析WESTRING_；可破坏物→"石头之墙" |
