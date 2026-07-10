# KKWE 提取增强清单（多代理分析汇总）

## #1 [done 2026-07-09] 全量 FIELD_LABELS：用 8 个 MetaData.slk 离线生成对象字段 4cc→中文映射（从 ~80 扩到 1100+）
**why**: w3xray fields.py 现仅手挑 ~80 个字段码，自定义对象/技能/科技/buff 的绝大多数字段在界面显示为原始 4cc。这是 w3obj.py 已解析二进制后最直接的可读性提升，且 w3xray 已具备全部所需基础设施（slk.py.parse_slk、westrings.py 8065 条），近乎零新增依赖。
**how**: 写一次性离线脚本（产物嵌进 fields.py，运行时零开销）：1) 用 latin-1 读取 KKWE 的 8 个文件 meta/units/{unitmetadata.slk, abilitymetadata.slk, upgrademetadata.slk, miscmetadata.slk, destructablemetadata.slk, abilitybuffmetadata.slk, upgradeeffectmetadata.slk} + meta/doodads/DoodadMetaData.slk；2) 对每个跑 slk.parse_slk()，得 {ID行键: {列名:值}}；3) 对每行取 code=ID(行键)、raw=row['displayName']，用下方 finding(rank2) 的 resolve() 把 WESTRING_* 解成中文；4) 合并 8 文件为 FIELD_LABELS[code]=中文，同 code 冲突保留首个；5) 同时产出 FIELD_TYPES[code]=row['type']。slk.py 按第1行列名动态定位 displayName 列，列顺序差异自动吸收，无需为各文件特判。NAME_FIELD 7 类已与这些表对应，不动。
**ref**: w3xray: w3xtool/fields.py:20-50(现 ~80 条), w3xtool/slk.py:12(parse_slk), w3xtool/westrings.py:4(WESTRINGS 8065 条); KKWE: plugin/.../script/meta/units/*.slk + meta/doodads/DoodadMetaData.slk
**result**: `build_field_labels.py` 离线生成 `w3xtool/field_meta.py`，提供 1444 个生成字段标签和 1521 个字段类型；`fields.label_for()` 采用精选标签优先、全量生成表兜底、原 4cc 兜底的三层显示，`field_type()` 供引用分析和列表化展示复用。

## #2 [done 2026-07-09] westring 多级解引用 + 控制符清理（FIELD_LABELS 生成的前置工具函数）
**why**: displayName 列的 WESTRING_* 可能链式别名（WESTRING_A→WESTRING_B→真实文本），现有 westrings.py 是合并产物但单次查表会漏链式键并残留控制符。是 rank1 落地的必需配套，成本极低。
**how**: 在生成脚本里实现 resolve(key)：若 key.upper() 不以 'WESTRING_' 开头直接原样返回；否则循环 k=WESTRINGS.get(k) or WESTRINGS.get(k.upper())，用 seen 集合防环，直到不再是 WESTRING_ 或查不到（查不到则回退原 4cc）；最后 re.sub(r'[\x00-\x1f]+','',k) 去控制符。仅用于离线生成，不进运行时。
**ref**: w3xray: w3xtool/westrings.py; KKWE: script/core/init.lua:81-119 (mt:get_editstring)
**result**: `build_field_labels.py::resolve_westring()` 已按链式 `WESTRING_*` 解引用生成 `field_meta.py`，生成结果运行时零额外开销。

## #3 [done 2026-07-09] war3map.wct 自定义脚本文本解析（导出每个触发器的 JASS/Lua 自定义代码）
**why**: 格式极简、成本极低，却能直接拿到地图作者手写的自定义 JASS/Lua 片段——对'看触发器'价值高。w3xray 现仅把 wct 原样导出。不依赖 TriggerData，独立可用。
**how**: 新建 wct.py，游标式读取：读 uint32 版本；若 >1 则该值==0x80000004，再读 uint32 真版本(断言==1)。然后全局块：cstr 注释 + int32 size（==0 空，否则 cstr 代码）。再循环触发器块（经典格式先 int32 count 循环 count 次；重制 0x80000004 格式无 count 循环到 EOF）：每块读 uint32 size，size==0 表示该触发器无代码（空串），否则读 size-1 字节为代码 + 跳 1 字节 NUL。复用 w3obj.py 的 _decode_str 做 UTF-8→GBK 回退。容错：size 越界/剩余不足即停，保留已解析部分。接入 api.py 的脚本展示。
**ref**: w3xray: w3xtool/api.py:26(SCRIPT_FILES 含 wct 但仅原样), w3obj.py:14(_decode_str); KKWE: script/core/slk/frontend_wct.lua:12-74
**result**: `w3xtool/wct.py` 解析全局和触发器自定义代码块，`api._add_wct()` 合成 `war3map.wct(自定义代码).txt`，GUI/导出脚本可直接读取可读文本。

## #4 [done 2026-07-09] war3map.w3i 地图信息完整逐字段解析（版本 18/25/28/31）
**why**: 用户最想看的'地图信息'——地图名/作者/描述/玩家数与种族/队伍/迷雾/载入屏/脚本语言(JASS/Lua) 等，w3xray 完全未做。KKWE 给的是实战验证、版本分支齐全的权威布局，纯翻译无新算法。
**how**: 新建 w3i.py，复用 doo.py 的 _Reader 模式（i32/u32/f32/u8/tag + cstr 找 \0）。按 KKWE frontend_w3i.lua 顺序逐字段：起始 i32 version；header(version>=28 多读 4×i32 war3 版本)；cstr 地图名/作者/描述/推荐玩家(均经 wts.resolve 还原 TRIGSTR)；8×f32 镜头边界+4×i32；i32 宽/高；u32 flag 位域；c1 主地表。version>=25 续读载入屏(i32 id+4×cstr)/game_data_set/序章/雾(i32 type+3×f32+4×u8)/环境(c4 weather+cstr sound+c1 light+4×u8)；version>=28 i32 脚本类型(0=JASS 1=Lua)；version>=31 额外 2×i32。version==18 走旧分支(载入屏/序章仅 i32 id+3×cstr)。玩家段 i32 count×{i32 id,type,race,fixStart,cstr name,2×f32 start,2×u32 ally,[v>=31:2×i32]}；队伍/升级/科技/随机组/随机物品段。升级/科技/随机段前 peek 单字节==0xFF 判空早停。结尾不 assert，对不上保留已解析部分（w3xray 容错风格）。flag 位域解成 bit 列表。把字段挂到 MapData 新增的 w3i 结构上供界面展示。
**ref**: w3xray: w3xtool/doo.py(_Reader 模式可照搬), w3xtool/wts.py:56(resolve), api.py:30(已列 w3i 为导出但未解析); KKWE: script/core/slk/frontend_w3i.lua:42-350
**result**: `w3xtool/w3i.py` 解析地图名、作者、描述、尺寸、脚本语言、玩家、队伍、flags 等；`api._add_w3i()` 写入 `MapData.w3i` 并优先采用 w3i 中的真实地图名，GUI“地图信息”和 CLI 摘要已展示。

## #5 [done 2026-07-09] 三层并集文件枚举：(listfile) + 内置静态名单 + imp 清单（补全无 listfile 的保护图）
**why**: w3xray mpq.list_files() 现仅读 (listfile)；保护图常删/伪造它，导致固定名地图文件与导入资源漏抓。三层并集成本低、对保护图覆盖率提升明显。imp.py 已能解析但产出未回流到枚举。
**how**: 在 mpq.py 加 enumerate_files()：mark=set(); files=[]; 依次遍历三来源，对每个 name 做 lname=name.lower() 去重，再 has_file(name) 验证存在才收。来源(a) 现有 (listfile)；(b) 硬编码 STATIC_MAP_FILES 常量(小写)：war3map.j/.doo/.imp/.mmp/.shd/.w3c/.w3e/.w3i/.w3r/.w3s/.w3a/.w3b/.w3d/.w3h/.w3q/.w3t/.w3u/.wct/.wpm/.wtg/.wts、war3mapextra.txt、war3mapmap.blp/.tga、war3mapmisc.txt、war3mapskin.txt、war3mapunits.doo、war3map.txt.ini、war3mappath.tga、(attributes)、(signature)、war3campaign.w3f/.imp/.wts；(c) imp.parse_imp 的每个 name 先试原名，has_file 失败再试 'war3mapimported\\'+name。把 list_files() 改为返回此并集（或新增方法并让 api.py 改用）。
**ref**: w3xray: w3xtool/mpq.py:495-509(list_files 仅 listfile), w3xtool/imp.py:16(parse_imp), api.py:378/410/569(用 list_files); KKWE: script/core/map-builder/load.lua:4-82, core/info.lua:128-149(impignore)
**result**: `MPQArchive.list_files()` 已委托 `w3xtool/mpq_files.py`，保持 `(listfile)` 未验证、固定名单验证、地图/战役导入表候选路径验证的三层并集语义；`(listfile)` 字节改用 `decode_warcraft_string()`，繁中 CP950/系统 ACP 老图的资源路径不再被 UTF-8 replacement 解坏。`war3campaign.imp` 现同样参与枚举、导出和导入摘要。

## #6 [done 2026-07-09] 轻量 JASS tokenizer 抽取全部 4cc 对象码（替代逐行正则 + 按 native 名硬分类）
**why**: script_scan.scan_object_refs 现按 native 名逐行正则，会漏跨行参数、漏裸 ID 常量、按 native 名猜类型易错分。词法级扫描更可靠且能统一产出 ids 集合再用已解析对象表反查归类。
**how**: 在 script_scan.py 加状态机 tokenizer 扫一遍 war3map.j：识别并跳过 //注释到行尾、整体跳过双引号字符串(避免误抓引号内文本)；对每个整数/rawcode 字面量产出候选 ID：(a) 'xxxx' rawcode 取引号内最多 4 字节原样；(b) 0x.. 或 $.. 十六进制 int(s,16)，若 >=0x41303030('A000') 则 struct.pack('>I',v) 得 4 字节码；(c) 十进制整数同阈值过滤后 pack('>I')。阈值 0x41303030 是关键去噪点。产出统一 ids 集合（不强分物品/单位），再用已解析的 w3u/w3t/w3a 等对象表反查归类。保留现有正则做聊天指令/配方（那部分仍有效），仅替换 scan_object_refs 的取码方式。
**ref**: w3xray: w3xtool/script_scan.py:82-93(_codes_in), 137-152(scan_object_refs); KKWE: script/core/slk/backend_searchjass.lua:92-142
**result**: 新增 `w3xtool/script_tokens.py`，生成保留偏移的脚本代码视图：抹掉 `//` / Lua `--` 注释和普通双引号字符串内容，保留 `FourCC("xxxx")`；`scan_object_refs()` 改为按平衡括号扫描 native 调用块，因此跨行 `CreateUnit(...)` 也能归类。`scan_all_referenced_codes()` 和 `save_analysis.py` 均改用代码视图，注释和用户显示字符串里的 `'A001'` / `StoreInteger(...)` 不再污染孤立判定和存档/ID 线索。

## #7 [done 2026-07-09] TRIGSTR 在 war3map.j / wtg / wct 文本中的内嵌还原（让触发器文本可读）
**why**: 现 resolve() 只处理对象数据里的 TRIGSTR 字符串字段；脚本与触发器文本里的 "TRIGSTR_NNN" 引用未还原，导出的触发器文本仍是占位号。配合 rank3(wct)/rank4(w3i) 提升整体可读性。
**how**: 在导出脚本/wct 文本时做两类替换（用现有 wts 表）：(1) war3map.j/.lua 文本：re 匹配 rb'"TRIGSTR_(\d{3,})"'，把带引号 token 整体替换为 wts 文本并做 jass 转义(\→\\、"→\")；(2) 二进制 wtg/wct：re 匹配 rb'TRIGSTR_(\d{3,})\x00'，用 wts[sid]+\0 替换。数字至少 3 位、wtg 以 \0 终止；缺失引用单点降级保留原 token（w3xray resolve 已是此安全行为）。可加可选开关，默认对导出文本生效。
**ref**: w3xray: w3xtool/wts.py:56-64(resolve 仅对象字段); KKWE: backend_convertwtg.lua:21-23, backend_convertjass.lua:25-28
**result**: 新增 `w3xtool/script_text_export.py`，对非 WTS 脚本文本中的 `"TRIGSTR_N"` 字符串字面量做 WTS 表还原，并转义反斜杠、双引号和换行；缺失引用保持原样。资料包新增 `脚本可读文本/`，GUI“导出脚本”也改用同一份可读化文本。

## #8 [done 2026-07-09] 对象字段值列表化显示（concat_types + FIELD_TYPES）
**why**: abilityList/unitList/buffList 等多值字段应按逗号/竖线拆分展示而非单值。锦上添花，依附 rank1 已产出的 FIELD_TYPES，几乎零额外成本。
**how**: 把 KKWE metadata.lua:9-76 的 concat_types 照抄为 Python CONCAT_TYPES dict（abilityList/unitList/buffList/targetList/effectList/intList/techList/itemList/stringList/unitClass/modelList/lightningList/unrealList/upgradeList/pathingListPrevent/pathingListRequire/tilesetList/attackTable/defenseTable=True，其余 False）。显示字段值时若 CONCAT_TYPES.get(FIELD_TYPES.get(code)) 为真，按逗号/竖线拆分展示，列表内 4cc 项可二次查 FIELD_LABELS/对象名。
**ref**: w3xray: rank1 产出的 FIELD_TYPES, w3obj.py:39(var_type); KKWE: script/prebuilt/metadata.lua:9-76
**result**: `fields.CONCAT_TYPES`、`is_concat_type()` 和 `api._expand_codes()` 已把 abilityList/unitList/buffList 等多值字段拆开，并把可识别 4cc 显示为“名称(码)”。

## #9 [done 2026-07-09] 地图名/作者优先取 w3i 的 MAP_NAME/AUTHOR（HM3W 头兜底）
**why**: HM3W 头名常是占位/旧名甚至 TRIGSTR；编辑器里设的真实名在 w3i 的 MAP_NAME（可能 TRIGSTR 需 wts 还原）。修正一批显示占位名/TRIGSTR 的地图。改动小，依附 rank4。
**how**: rank4 的 w3i 解析落地后，_map_name() 改为：先尝试 w3i 的 MAP_NAME（经 wts.resolve 还原 TRIGSTR），非空且非 TRIGSTR 残留则用之；否则回退现有 HM3W 头名；再否则文件名。quick_map_name 仍用 HM3W（不解析整 MPQ）保持目录列表快速。
**ref**: w3xray: w3xtool/api.py:272-296(_map_name/quick_map_name 仅 HM3W); KKWE: frontend_w3i.lua:59
**result**: `api._add_w3i()` 在 w3i 地图名非空且非 `TRIGSTR_` 残留时覆盖 HM3W 头名；战役则由 `api._add_w3f()` 在合适时用战役名兜底。

## #10 [done 2026-07-09] 提取完整性自检：枚举到的文件数 vs block 表有效条目数
**why**: 让保护图提取覆盖率对用户透明——抓不全时提示'存在 N 个无法按名定位的隐藏文件，可提供外部 listfile'。成本低，依附 rank5。
**how**: 在 mpq.py 暴露 number_of_files()=block 表中 flags 含 MPQ_FILE_EXISTS(0x80000000) 且非删除/非空洞的条目数。rank5 枚举完成后比较 len(recovered) 与该数，差值>0 输出告警。可选增强：对未命名 block 用 peek_block(已有) 读前 4 字节 magic 盲猜类型（HM3W=w3i、BLP1/BLP2=blp、MDLX=mdx、W3do=doo）。
**ref**: w3xray: w3xtool/mpq.py:461(peek_block 已有), block_table; KKWE: backend/cli/unpack.lua:136-145
**result**: 新增 `w3xtool/extraction_completeness.py`，统计命名文件、有效 MPQ block、命名覆盖率、无名块、`Unknown/` 可解包估算和 `UnknownRaw/` 原始负载兜底；GUI 分析新增“提取完整性”块，知识包新增 `提取完整性.txt`。

## #11 [done 2026-07-09] war3map.w3f 战役信息头部解析（6 字段）
**why**: w3xray 已处理战役(.w3n)但未解析 w3f，无法显示战役名/作者/难度/描述。头部 6 字段成本极低；战役占比少故价值中。
**how**: 在 w3i.py 或新 w3f.py 加最小头解析：i32 version；i32 campaign_version；i32 editor_version；cstr 战役名/难度/作者/描述（后三 cstr 经 wts.resolve 还原）。KKWE 自身也只解到头，后续战役地图列表段暂缺（需另找 HiveWE 规范，价值不足暂不做）。接入战役展示。
**ref**: w3xray: w3xtool/api.py(战役 .w3n 处理 381-401); KKWE: script/core/slk/frontend_w3f.lua:16-39
**result**: `w3xtool/w3i.py::parse_w3f()` 解析战役版本、名称、难度、作者和描述，`api._add_w3f()` 写入 `MapData.w3f`，GUI 信息页和 CLI 摘要可展示战役头信息。

## #12 [done 2026-07-09] extra_func / need_mark 两张 BJ→隐式对象引用静态映射表
**why**: 图作者用暴雪内置开局/随机刷怪 BJ(MeleeStartingUnitsHuman、ChooseRandomItem 等)时，引用的对象码写死在 BJ 内部，任何脚本扫描都抓不到。纯数据搬运，零算法成本，让'这张图实际用了哪些对象'更完整。
**how**: 把 KKWE backend_searchjass.lua:11-47 的 extra_func（~14 个 BJ 函数名→内置对象码列表，如 MeleeStartingUnitsHuman→hpea/Hamg/htow…）和 need_mark（ChooseRandomCreep/Item、InitNeutralBuildings 等→creeps/building/item/marketplace 标记）转成 Python dict 常量。在 rank6 tokenizer 扫到标识符 token 命中 extra_func 时把对应码加入 ids 集合；命中 need_mark 记 flag。
**ref**: w3xray: w3xtool/script_scan.py; KKWE: script/core/slk/backend_searchjass.lua:11-47
**result**: `BJ_FUNC_CODES` 已用于 `scan_script_features()` 和孤立判定；隐式码按 `base_objects` 分类并入 `scan_object_refs()`，因此 `MeleeStartingUnitsHuman`、`MeleeGrantItemsToHero` 会补出单位/技能/物品引用。`bj_ELEVATOR_CODE*` 常量按可破坏物归类。`script_mechanics.py` 增加 need_mark 报告，覆盖 `ChooseRandomItem*`、`ChooseRandomCreep*`、`ChooseRandomNPBuilding`、`InitNeutralBuildings` 等运行时默认池；GUI 新增“脚本机制”块，知识包新增 `脚本机制线索.txt`。

## #13 [done 2026-07-09] doo.py 装饰物 v8 的 4 字节格式变体兜底（暴雪改格式不改版本号）
**why**: 某些重制版图在 version>=8 时 7 个 float 后紧跟一个等于该条 type_id 的多余 4 字节，会导致 doo.py 错位。doo.py 已对等且更细，仅缺此一处健壮性补丁。
**how**: 在 doo.py 装饰物循环(约 107-125 行)读完 7 个 float 后、读 vis/life 之前，对 version>=8 加 peek：窥探下 4 字节是否等于刚读的 tid，若相等则跳过这 4 字节再继续。无 4 字节 peek 接口则用 r.d[r.p:r.p+4] 比较后手动推进 r.p。
**ref**: w3xray: w3xtool/doo.py:96-125; KKWE: script/core/slk/backend_searchdoo.lua:31-34
**result**: `doo.py` 对装饰物和单位预放置数据同时尝试经典布局与 Reforged skin 字段布局，选择能完整读完 count 的版本；测试覆盖 Reforged skin 字段和带掉落表场景。

## #14 [done 2026-07-09] WTS 解析加固：注释行处理 + 行首独占 { 定位 + ACP 编码回退
**why**: 三个低成本健壮性点合并：(a) 现用 data.find(b'{') 找正文起点，注释行 '// foo {bar}' 含 { 会错位；(b) 简中以外系统应优先系统 ACP 而非硬编码 gbk，繁中/日文老图否则全损。当前对纯简中环境无害，故价值中。
**how**: (1) parse_wts 中把 brace=data.find(b'{') 改为用行锚定位真正独占一行的 {：在 STRING 头之后逐行跳过可选空白+// 开头的注释行，遇到 strip 后==b'{' 的行作为正文起点（与 _CLOSE 的 (?m)^\}[ \t]*$ 对称）。(2) _decode_str 回退顺序改为 UTF-8 → mbcs(系统 ACP，仅 Windows 可用，非 Windows 跳过) → gbk(跨系统兜底) → utf-8 replace。同样可应用到 w3obj._decode_str/imp 解码。
**ref**: w3xray: w3xtool/wts.py:44(data.find b'{'), 19-27(_decode_str); KKWE: frontend_wts.lua:21-39, script/ffi/unicode.lua:7-22(CP_ACP)
**result**: 新增 `w3xtool/war3_encoding.py`，统一 `UTF-8 → 系统 ACP/mbcs → GBK/GB18030 → replace` 回退顺序；WTS、对象数据、IMP 导入路径、W3I/W3F、WCT、WTG、WGC、世界区域/镜头/声音和游戏平衡常数读取均改用同一策略。新增 CP950 用例覆盖繁中 ACP 先于 GBK 的行为。

## #15 [done 2026-07-09] 资料包复制资源/配置本体：图标、模型、音频、UI 文本、SLK/对象/地图配置
**why**: 资料包已有资源引用和资产索引，但只告诉用户“有哪些路径”，没有把可读取的 mdx/blp/mp3/wts/slk/w3u/w3i/wgc 等本体放进去；对照别人工具、整理图标资源、排查缺失导入时仍要再跑完整导出。
**how**: 新增 `w3xtool/knowledge_assets.py`，复用 `build_resource_inventory()` 的状态，只复制 `存在/已引用` 与 `存在/未引用` 的条目；输出到 `资源/素材文件/`，同时写 `资源/素材文件_manifest.tsv` 记录内部路径、导出相对路径、字节数和状态。路径落盘前拒绝空名、盘符和 `..` 穿越；源文件不可读、源内缺失、读取失败都只写 manifest，不中断整个资料包。
**ref**: w3xray: `w3xtool/knowledge_pack.py`, `w3xtool/resource_inventory.py`, `w3xtool/mpq.py`
**result**: `resources.py` 与 `resource_inventory.py` 的资源类型补齐到 PNG/JPG/BMP、OTF、FDF/TOC/TXT/INI、SLK；脚本和对象字段中的 UI 布局、载入图、字体、表格和文本配置路径会进入资源引用图，内部 `.toc` 会按“UI/文本”标记为存在资源。`save_analysis.py` 也改为跨行调用扫描，`StoreInteger(...)`、`UnitAddAbility(...)` 等换行写法不会再漏掉存档键和对象 ID。

## #16 [done 2026-07-09] 资料包审计总览 + 扩展文本配置资源覆盖
**why**: 用户要“一次都加上”时，需要能快速确认 UI 文本、资源、配置格式、存档/ID、提取完整性这些面是否都已经产出；同时优化图常把面板配置、皮肤和 AI 脚本放在 `.json`、`.plist`、`.skin`、`.ai`，此前会被资源图忽略。
**how**: 新增 `w3xtool/knowledge_audit.py` 汇总已有静态报告，不重新扫描运行时逻辑；资料包新增 `资料包审计.txt`，列出 UI 文本、资源资产、配置格式、存档/ID、地图/对象 ID、提取完整性计数。`resources.py` 和 `resource_inventory.py` 继续扩展资源路径识别与分类，`investigation_exports.py` 的配置格式索引同步识别文本配置和 AI 脚本。
**result**: 知识包现在同时包含分项 TSV/文本和一个总览审计文件；`地图与对象ID索引.tsv` 增加内部文件数、脚本文件数、对象总数和分类数量摘要；`.json/.plist/.skin/.ai` 会进入资源引用、资源资产索引、素材文件 manifest 和配置格式索引。

## #17 [done 2026-07-09] 地图文件身份指纹：大小 + CRC32 + SHA1
**why**: “地图 ID”不一定只来自 w3i 文本字段；很多平台/存档系统会把地图文件哈希或体积作为身份校验的一部分。静态资料包需要能把原始地图文件身份和脚本里的存档/平台键放在一起核对。
**how**: 新增 `w3xtool/map_identity.py`，仅对真实可读的地图文件流式计算文件字节数、CRC32 和 SHA1；目录源、缺失源或不可读源不猜测。`investigation_exports.py` 把身份指纹加入 `地图与对象ID索引.tsv`，`knowledge_audit.py` 在 `资料包审计.txt` 中给出地图身份摘要。
**result**: 知识包现在包含可复核的地图文件身份指纹；无法读取原始地图时仍保留原有路径/对象 ID/配置索引，并明确“源文件不可读”。

## #18 [done 2026-07-09] Hashtable native 家族覆盖：Save/Load/HaveSaved/RemoveSaved *Handle
**why**: Warcraft 的本地/哈希表存档 native 不止 `SaveInteger` 和 `SaveUnitHandle`；地图脚本常保存玩家、触发器、计时器、效果等 handle。此前这些 `SavePlayerHandle`、`LoadTriggerHandle`、`HaveSavedHandle`、`RemoveSavedHandle` 会漏出 `存档读写线索.tsv`。
**how**: 新增 `w3xtool/save_api_catalog.py`，把存档 API 目录从 `save_analysis.py` 拆出，并用规则覆盖 `Save*Handle`、`Load*Handle`、`HaveSaved*`、`RemoveSaved*` 等 hashtable native；`save_call_context.py` 复用同一判断提取父键/子键。
**result**: `存档读写线索.tsv` 和 GUI“存档/ID线索”现在能显示更完整的 hashtable 读写 native，并在详情里保留原始 API 名；`save_analysis.py` 从 212 行降到 147 行，后续扩展不会继续堆大表。

## #19 [done 2026-07-09] 地图与对象 ID 索引增加脚本/存档/预放置使用来源
**why**: 之前 `地图与对象ID索引.tsv` 只列对象表中的 ID 和地图摘要，无法直接看出某个单位/技能/物品 ID 是否真的被脚本、存档/ID 线索、对象字段或预放置数据使用，也看不到脚本里出现但对象表没有解析出的未知 4cc。
**how**: `investigation_exports.py` 复用 `scan_object_refs()`、`scan_all_referenced_codes()` 和 `build_save_report()`，为每个对象行增加 `使用情况` 与 `详情`；脚本中出现但不在对象表的 4cc 会输出 `脚本引用/未知` 行，带十进制 ID、来源脚本和“未在对象表中解析”说明。
**result**: 知识包的 `地图与对象ID索引.tsv` 现在能把“对象表 ID”和“实际使用来源”放在同一张表里核对，便于追地图 ID、物品/技能/单位 ID 以及漏解析对象。

## #20 [done 2026-07-09] 对象 ID 使用来源精确到脚本行号
**why**: 只知道 `war3map.j:技能` 不够定位问题；要追“为什么某个技能/单位被认为使用过”时，需要能直接回到脚本行，尤其是跨多个脚本文件、同一 ID 多处出现、或未知 4cc 需要人工核对时。
**how**: 新增 `w3xtool/object_id_usage.py`，在保留注释/字符串去噪的代码视图上逐行提取 4cc，并结合 `scan_object_refs()` 的分类结果生成 `来源:行号:分类` 详情；没有显式行号的 BJ 隐式码仍以“脚本隐式”标注。`investigation_exports.py` 只负责格式化，不再承载扫描逻辑。
**result**: `地图与对象ID索引.tsv` 的详情列现在会显示如 `war3map.j:12:单位`、`save.j:8:技能`，未知脚本码也保留行号和“未在对象表中解析”说明。

## #21 [done 2026-07-09] WTG 触发器目录和变量清单导出到知识包
**why**: 当时先交付不依赖游戏数据的触发器分类、触发器头、启用/自定义脚本状态和全局变量；此前只在 GUI/地图信息里显示摘要，资料包缺独立表格。
**how**: 新增 `w3xtool/trigger_exports.py`，把 `TriggerTreeSummary` 格式化为 `触发器树.tsv` 和 `触发变量.tsv`；保留分类 ID/父 ID、触发器父分类、启用状态、自定义脚本、初始关闭、初始化运行、变量类型/数组/初始值，并在 ECA 未展开时写明原因。
**result**: 知识包包含可筛选的触发器目录和变量清单；后续 #40 已补齐依赖 `TriggerData.txt` 的 ECA 函数体和依赖 `TriggerStrings.txt` 的语义本地化。

## #22 [done 2026-07-09] 资料包目录清单：需求面到产物文件的映射
**why**: 资料包已经输出 UI 文本、资源、配置、存档/ID、触发器、提取完整性等多份文件，但用户打开目录时仍要猜每个文件对应哪个调查面；这会降低“都加上”后的可用性。
**how**: 新增 `w3xtool/knowledge_manifest.py`，固定输出 `资料包目录.tsv`，列出“主题 / 文件 / 用途”；`knowledge_pack.py` 在导出开头写入该目录文件。
**result**: 知识包根目录现在有一个入口表，能直接看到 UI 文本、资源/图标、配置格式、存档/ID、地图/对象 ID、触发器、脚本和提取完整性分别该看哪个文件。

## #23 [done 2026-07-09] 世界编辑器区域/镜头/声音导出到知识包
**why**: `war3map.w3r/.w3c/.w3s` 已经能解析并在地图信息中显示摘要，但资料包缺可筛选明细；排查区域触发、镜头切换、导入音效/音乐时需要表格化数据。
**how**: 新增 `w3xtool/world_exports.py`，把 `MapData.regions/cameras/sounds` 格式化为 `世界区域.tsv`、`世界镜头.tsv`、`世界声音.tsv`；同步更新 `资料包目录.tsv` 的世界编辑器条目。
**result**: 知识包现在能直接查看区域范围/天气/环境声音、镜头坐标/角度/视野/裁剪距离、声音路径/变量名/循环/3D/音乐/导入标志。

## #24 [done 2026-07-09] 需求覆盖矩阵：用户原始需求到资料包产物的验收表
**why**: `资料包目录.tsv` 说明“哪个文件做什么”，但还不能直接按用户原始需求验收“UI 文本、图标/资源、配置格式、本地存档、地图 ID、物品/技能/单位 ID 是否都有对应产物”。继续做功能前需要一张覆盖矩阵，避免漏项或把静态线索误说成运行时能力。
**how**: 新增 `w3xtool/knowledge_requirements.py`，固定输出 `需求覆盖.tsv`，列出“需求 / 状态 / 主要产物 / 辅助产物 / 说明”；`knowledge_pack.py` 在根目录写入该文件，`knowledge_manifest.py` 同步把它加入目录清单。
**result**: 知识包现在可按需求面直接验收静态覆盖范围：UI 文本、图标/资源、配置格式、本地存档读写线索、地图 ID、物品/技能/单位 ID、触发器/变量、区域/镜头/声音和提取完整性。

## #25 [done 2026-07-09] 预放置单位/装饰物/掉落明细导出到知识包
**why**: `war3mapUnits.doo` 与 `war3map.doo` 已经解析并在 GUI 展示，但知识包缺可筛选的明细表；排查“地图上实际摆了哪些单位/物品/可破坏物”、掉落表和对象 ID 使用来源时仍要打开 GUI。
**how**: 先把 `knowledge_pack.py` 的对象、资源、脚本导出拆到 `knowledge_object_exports.py`、`knowledge_resource_exports.py`、`knowledge_script_exports.py` 和共享 `knowledge_io.py`，避免继续堆大编排文件；再新增 `knowledge_preplaced_exports.py`，输出 `预放置单位.tsv` 与 `预放置装饰物.tsv`。单位表包含序号、类型 ID、名称、玩家、坐标、角度、生命/魔法/金矿、英雄等级、物品栏和技能；装饰物表包含类型、坐标、角度、缩放、状态、生命和掉落。
**result**: 知识包现在能直接查看预放置单位、装饰物/可破坏物和掉落表，并把这些产物加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。

## #26 [done 2026-07-09] 对象 ID 使用摘要：按 ID 汇总脚本、存档、对象字段和预放置来源
**why**: `地图与对象ID索引.tsv` 已经能列出对象表与使用来源，但排查某个 ID 时仍要在脚本行号、存档线索、对象字段和预放置表之间来回查；预放置单位的物品栏/技能、装饰物掉落里的 ID 也应算作“预放置使用”。
**how**: 新增 `w3xtool/object_id_summary.py`，输出 `对象ID使用摘要.tsv`，每个 ID 汇总分类、名称、对象来源、脚本引用次数、存档/ID 线索次数、对象字段引用次数、预放置引用次数、状态和详情。`investigation_exports.py` 复用同一份预放置计数，`地图与对象ID索引.tsv` 现在也能把单位物品栏、单位技能、装饰物掉落中的 ID 标为预放置。
**result**: 知识包新增按 ID 聚合的来源计数表，适合快速判断某个单位/物品/技能/可破坏物 ID 是对象表孤立项、脚本引用、存档线索、对象字段引用，还是地图场景实际摆放/掉落引用。

## #27 [done 2026-07-09] 脚本调用清单：按函数汇总调用、对象码和字符串参数
**why**: 用户排查“地图怎么读写存档、哪里创建单位/物品/技能、哪些平台/同步键被用到”时，已有 `存档读写线索.tsv` 和对象 ID 表仍偏按主题拆分；需要一张按函数名聚合的调用清单，快速定位脚本 native/API、对象码和字符串参数。
**how**: 新增 `w3xtool/script_call_catalog.py`，在 `script_code_text()` 去掉注释和普通字符串内容后的代码视图上识别函数调用，复用 `extract_call_args()`、`save_api_catalog` 和 `_codes_in()` 提取机制、行号、对象码、字符串参数与示例；资料包新增 `脚本调用清单.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在可按函数查看脚本调用次数、来源行号、GameCache/Hashtable/Sync/PlatformSave/ObjectID 分类、对象码和字符串参数；注释或字符串里的伪调用不会被当成真实调用。

## #28 [done 2026-07-09] 脚本函数索引：函数范围、调用关系、机制和对象码
**why**: 只看全局调用清单仍要回脚本里定位函数边界；分析存档、地图初始化、物品/技能逻辑时，需要知道某个函数从哪行到哪行、内部主要调用了哪些 API、被其他函数调用几次，以及函数体涉及哪些对象码。
**how**: 新增 `w3xtool/script_function_index.py`，轻量识别 JASS `function ... endfunction` 和 Lua `function ... end` 范围；复用 `script_call_catalog` 的调用扫描结果，只统计每行主调用，汇总被调用次数、内部调用数、机制、对象码和调用函数。资料包新增 `脚本函数索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能按函数范围阅读脚本业务逻辑，快速定位存档读写、对象创建、技能/物品处理和平台存档线索所在函数；注释和字符串里的伪函数/伪调用不会进入索引。

## #29 [done 2026-07-09] 脚本字符串索引：字符串字面量、用途和函数上下文
**why**: UI 文本、资源路径、聊天指令、同步前缀和存档键很多都藏在脚本字符串里；只看调用清单会丢失逐条字符串的来源行、函数上下文和用途分类，排查本地存档/地图 ID/资源配置时仍要回脚本翻。
**how**: 新增 `w3xtool/script_string_index.py`，逐行抽取真实字符串字面量，跳过 `//`/`--` 注释和 JASS 单引号 4cc；复用 WTS 解析还原 `TRIGSTR_xxx`，复用函数索引定位函数范围，并按调用名/扩展名分类为 UI 文本、资源路径、聊天指令、同步前缀、存档/键、显示文本或普通字符串。资料包新增 `脚本字符串索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在可以直接筛选脚本字符串，看到来源文件、行号、函数、调用、用途、原始字符串和解析文本，补齐 UI 文本/资源/存档键的逐字符串追踪面。

## #30 [done 2026-07-09] 脚本全局变量索引：JASS globals 初值、对象码和存档键
**why**: 地图脚本常把单位/技能/物品 ID 常量、存档键、开关和玩家状态数组放在 `globals/endglobals` 块里；只看调用和字符串索引仍要回脚本翻变量声明，排查存档、地图状态和 ID 常量不够直接。
**how**: 新增 `w3xtool/script_global_index.py`，只解析 JASS `globals/endglobals` 声明块，跳过注释和函数内 local；导出来源、行号、名称、类型、数组/常量标记、初值、字符串值、对象码和用途。资料包新增 `脚本全局变量索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选 `HERO_ID = 'H001'`、`SAVE_KEY = "hero.level"`、数组状态和布尔开关这类全局线索，补齐脚本全局变量对存档/ID 分析的静态追踪面。

## #31 [done 2026-07-10] 脚本赋值索引：变量写入、状态变化和对象码
**why**: 初始 globals 只能说明变量默认值，很多地图会在初始化、刷怪、存档读写后用 `set` 改写状态变量、数组、对象 ID 或存档键；没有赋值索引时仍要回脚本逐行翻变量流转。
**how**: 新增 `w3xtool/script_assignment_index.py`，在去掉注释和普通字符串误报的代码视图上识别 JASS `set` 和简单 Lua 赋值，保留函数上下文、变量名、数组索引、右值、字符串值、对象码和用途。资料包新增 `脚本赋值索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选 `set udg_HeroId = 'H001'`、`set udg_SaveKey = "hero.level"`、数组状态和布尔开关，补齐脚本运行状态变化的静态追踪面。

## #32 [done 2026-07-10] 脚本变量使用索引：udg_/gg_/bj_ 全局变量读写位置
**why**: 赋值索引只覆盖写入语句，无法回答某个 `udg_` 用户全局变量、`gg_trg_` 触发器变量或 `gg_unit_` 预放置单位在哪些函数/API 中被读取；分析存档状态、触发器引用和预放置对象时仍要全文搜索。
**how**: 新增 `w3xtool/script_variable_usage_index.py`，在去掉注释和普通字符串误报的代码视图上识别 `udg_`、`gg_trg_`、`gg_unit_`、`gg_item_`、`gg_dest_`、`gg_rct_`、`gg_cam_`、`gg_snd_`、`bj_` 变量，导出来源、行号、函数、变量、读/写、类别、当前行调用和对象码。资料包新增 `脚本变量使用索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选脚本全局变量的读取/写入位置，定位 `SaveInteger(udg_hash, ...)`、`TriggerRegisterPlayerEvent(gg_trg_X, ...)`、`SetUnitOwner(gg_unit_X, ...)` 等状态和触发器引用。

## #33 [done 2026-07-10] 脚本对象码出现索引：rawcode 逐次位置和上下文
**why**: `对象ID使用摘要.tsv` 和 `地图与对象ID索引.tsv` 已能统计对象码来源，但排查“某个 H001/A001/I999 到底在哪一行、属于哪个调用或赋值”时仍需要回脚本全文搜索；同一 ID 在创建、保存、变量赋值里出现多次时也缺少逐次上下文。
**how**: 新增 `w3xtool/script_object_code_occurrence_index.py`，在 `script_code_text()` 去掉注释和普通字符串误报后的代码视图上逐行提取 `_codes_in()` 结果，结合函数索引、调用清单、对象表、原版名表和 `scan_object_refs()` 输出来源、行号、函数、对象码、十进制值、分类、名称、对象来源、上下文和机制。资料包新增 `脚本对象码出现索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选脚本 rawcode 的每次真实出现，区分 `CreateUnit('H001')`、`set udg_AbilityId = FourCC("A001")`、`SaveInteger(..., 'A001')` 和未知对象码 `I999` 这类不同上下文。

## #34 [done 2026-07-10] 脚本触发注册索引：事件、动作、条件和计时器入口
**why**: 触发器树只能说明 WTG 头部，脚本函数索引只能说明函数范围；要理解地图逻辑入口，还需要知道 `TriggerRegister*` 事件、`TriggerAddAction/Condition` 处理函数和 `TimerStart` 计时器回调是如何连接的。
**how**: 新增 `w3xtool/script_trigger_registration_index.py`，在 `script_code_text()` 去噪后的代码视图上扫描注册类调用，复用函数索引定位当前函数，导出来源、行号、函数、注册类型、触发器/计时器句柄、API、目标事件/处理函数、字符串参数和摘要。资料包新增 `脚本触发注册索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选 `TriggerRegisterPlayerEvent`、`TriggerRegisterPlayerChatEvent`、`TriggerAddCondition`、`TriggerAddAction` 和 `TimerStart` 等控制流入口，定位触发器事件、聊天指令、条件函数、动作函数和周期回调。

## #35 [done 2026-07-10] 脚本条件分支索引：if/elseif 条件里的存档、变量和对象码
**why**: 有了函数、调用、变量和对象码索引后，仍缺“判断条件”这一层；地图常在 `if LoadInteger(...)`、`elseif GetUnitTypeId(...) == 'H001'` 或状态开关里决定是否读档、发奖励、创建单位。
**how**: 新增 `w3xtool/script_condition_branch_index.py`，在 `script_code_text()` 去噪后的脚本视图上扫描 JASS `if/elseif ... then`，复用函数索引定位上下文，导出来源、行号、函数、分支类型、条件表达式、调用、变量、字符串、对象码、用途和摘要。资料包新增 `脚本条件分支索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选存档条件、对象 ID 条件、资源条件和状态变量条件；注释和显示字符串里的伪条件不会进入索引。

## #36 [done 2026-07-10] 脚本循环索引：loop/exitwhen/for/while/repeat/until 控制流
**why**: 刷怪、周期检测、玩家遍历和读档等待常藏在循环里；只有函数、调用和条件分支索引时，仍难直接定位 `loop`/`exitwhen`、Lua `while/for` 或 `repeat/until` 的重复执行逻辑。
**how**: 新增 `w3xtool/script_loop_index.py`，在 `script_code_text()` 去噪后的脚本视图上扫描 JASS `loop`、`exitwhen` 与 Lua `for/while/repeat/until`，复用函数索引定位上下文，导出来源、行号、函数、循环类型、表达式、调用、变量、字符串、对象码、用途和摘要。资料包新增 `脚本循环索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选存档循环条件、对象 ID 循环条件、状态变量循环条件和普通循环；注释和显示字符串里的伪循环不会进入索引。

## #37 [done 2026-07-10] 脚本返回值索引：return 里的存档、变量和对象码
**why**: 很多地图会把存档读取、对象 ID 常量或状态变量封装成小函数并通过 `return` 暴露；只看调用和赋值时，难判断某个函数实际返回的是读档值、单位/技能 ID 还是状态开关。
**how**: 新增 `w3xtool/script_return_index.py`，在 `script_code_text()` 去噪后的脚本视图上扫描 JASS/Lua `return`，复用函数索引定位上下文，导出来源、行号、函数、返回表达式、调用、变量、字符串、对象码、用途和摘要。资料包新增 `脚本返回值索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选存档返回值、对象 ID 返回值、资源返回值、状态变量返回值和普通返回值；注释和显示字符串里的伪 return 不会进入索引。

## #38 [done 2026-07-10] 脚本局部变量索引：函数内 local 初值、存档键和对象码
**why**: 地图常在函数开头把单位/技能/物品 ID、资源路径、存档键或开关缓存到 `local` 变量里；只有 globals、赋值和 return 索引时，仍要回脚本看局部声明才能判断变量含义。
**how**: 新增 `w3xtool/script_local_index.py`，在 `script_code_text()` 去噪后的脚本视图上扫描 JASS/Lua `local` 声明，复用函数索引定位上下文，导出来源、行号、函数、名称、类型、初值、字符串、对象码、用途和摘要。资料包新增 `脚本局部变量索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接筛选函数内对象码常量、资源路径、存档键和开关局部变量；注释和显示字符串里的伪 local 不会进入索引。

## #39 [done 2026-07-10] 脚本调用参数索引：逐次调用的存档键、资源路径和对象码
**why**: `脚本调用清单.tsv` 只按函数聚合，能看到某个 API 出现过哪些字符串/对象码，但排查存档和对象 ID 时还需要知道“第几行、哪个函数、哪个调用的第几个参数”里放了键名、资源路径或 rawcode。
**how**: 新增 `w3xtool/script_call_argument_index.py`，复用 `script_code_text()`、`extract_call_args()` 和函数索引，逐次导出调用参数的来源、行号、函数、调用名、参数序号、参数文本、字符串值、对象码、机制、用途和摘要。资料包新增 `脚本调用参数索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
**result**: 知识包现在能直接定位 `SaveInteger(... StringHash("hero") ...)`、`CreateUnit(... 'hfoo' ...)`、`BlzLoadTOCFile("ui\\panel.toc")` 这类参数级线索；注释和显示字符串里的伪调用不会被当成真实调用参数。

## #40 [done 2026-07-10] TriggerData.txt 语义化 ECA 文本
**why**: raw ECA 只列函数名和参数序号，排查触发器时仍要人工对照 World Editor 的中文模板。
**how**: 新增 `w3xtool/triggerdata.py` 和 TriggerData/TriggerStrings schema loader；`触发器ECA.tsv` 旧列顺序不变，追加 `语义文本` 列，并递归展开嵌套函数参数。WTG 头始终可读，ECA 函数体只在 `TriggerData.txt` 匹配时展开，本地化模板另需 `TriggerStrings.txt`。
**result**: 两份 schema 齐全时能看到编辑器式本地化句子；只有 TriggerData 时保留函数和参数语义；缺 TriggerData 时保留触发器头并结构化报告未展开入口，不猜参数字节。

## #41 [done 2026-07-10] 原生 CASC idx/data 路径映射回退
**why**: 只支持 CascView/casc-extract 散文件时，GUI 读取基础图标和 TriggerData 仍依赖用户先导出目录。
**how**: 新增 `w3xtool/casc_source.py`，在原生安装目录满足 `.build.info` + `Data/data/*.idx` + `data.###` 且存在 `w3xray-casc-paths.tsv` 路径映射时，按 idx 定位 data archive，解出非加密 BLTE `N/Z` 块。`game_data_source.open_game_data_source()` 统一返回散文件或 CASC 源。
**result**: 已能在可验证的本地 CASC fixture 上直读 `data.000` 中的非加密 BLTE 文件。这个纯 Python 回退不解析 Root/Encoding 或加密 BLTE；Windows 标准安装目录的接入由后续 #42 CascLib 后端承担。

## #42 [done 2026-07-10] Windows CascLib 原生安装目录后端
**why**: path-map 回退仍要求用户提前提供内部路径到 encoded key 的映射，不能直接从标准重制版安装目录读取 TriggerData、TriggerStrings 和基础图标。
**how**: 固定 CascLib 3.0 tag/commit/source SHA256，新增 `ctypes.c_bool` ABI 绑定、Unicode `CascOpenStorage`、窄字符 `CascOpenFile`、`CascGetFileSize64`、有界读取和句柄关闭；Windows 打包前校验 DLL SHA256 与 x64 PE，应用启动时不联网下载。`game_data_source` 优先 CascLib，失败后回退 path-map；散文件目录保持不变。
**result**: 已实现按已知游戏逻辑路径读取原生 CASC 的 Windows 后端；macOS fake-native、源码构建和打包验证通过。后续 #43 已补完整 Root 枚举。真实 Windows 魔兽安装测试仍是显式环境测试且本轮未执行，因此不声明真机读取已经验证。

## #43 [done 2026-07-10] CascLib 完整 Root 枚举与未知身份导出
**why**: 已知路径读取不能回答“客户端里还有哪些文件”，也无法浏览 Root 没保存原始路径的 encoding 条目。
**how**: 按固定 CascLib 3.0 ABI 接入 `CascFindFirstFile/Next/Close`，保留 `CASC_FIND_DATA` 的 NameType、FileDataID、CKey、EKey、大小和本地状态；GUI 每页 200 条，CLI 清单按约 64 KiB 分块写 stage，未知条目按 CascLib 返回的 `FILE%08X.dat`/CKey/EKey 合成名重开和安全导出。
**result**: fake-native ABI、分页、流式清单和未知身份重开契约已自动化；Windows acceptance 会从真实 Root 找一个本地未知条目重开并核对大小。真实安装是否通过只以 self-hosted 报告为准。

## 不建议做
- 真正数据级加密/运行时解密地图：只做静态诊断，`提取完整性.txt` 会提示大量匿名加密块不可恢复；不做运行时内存 dump、调试器绕过或平台/保护绕过。
- 再从 KKWE 借鉴 war3map.w3e 解析：KKWE 本身没有 w3e 解析器，只把地形当二进制保留；w3xray 后续已依据独立格式资料实现 W3E 头、tilepoint、纹理、坐标范围和场景边界统计，因此这里没有可继续复用的 KKWE 逻辑。
- 完整 JASS PEG/AST parser（grammar.lua/parser.lua/checker.lua）：几千行文法+语义+检查，远超'静态抽对象码'目标；KKWE 自己抽码也不用它而用轻量 searchjass。rank6 的词法级 tokenizer 已足够。仅 Integer256/Char16 的四种整数边界定义可作 tokenizer 校准参考。
- metadata.lua 的 parse_id/characters 后缀推导与 repeat 分级：仅用于 SLK/INI 文本格式的派生列名（DataA、_2 等）；w3xray 读二进制 .w3a/.w3u 时 field_id 就是 MetaData 的 ID 行键本身，可直接查 FIELD_LABELS，无需此推导。w3xray 也不导出 SLK。
- JASS 混淆器特征/converter 字面量规范化/完整 KKAPI.DzAPI native 声明：均为运行时或单向不可逆，无静态可提取逻辑。已顺手把常见 `DzAPI_Map_SaveServerValue` / `DzAPI_Map_StoreInteger` / `DzAPI_Map_SavePublicArchive` 和 `KKAPI_SaveServerValue` 作为“PlatformSave”静态存档线索记入 `存档读写线索.tsv`；不做运行时调用、参数模拟或平台兼容层。
- imp 名转义为磁盘安全文件名($XX 方案)：仅当地图导入名含 `:`/控制字符时需要；CASC 浏览器对完整逻辑路径使用统一安全相对路径校验，未知条目落到 `UnknownCASC/`，不直接信任原始名称。可在真实地图触发额外 Windows 非法字符时再按需扩展，暂不优先。
- WTS 正文含 } 的告警：w3xray 是只读提取器，_CLOSE 已正确处理独占行 }，正文内 } 字符不影响读取（仅影响回写，而 w3xray 不回写）。纯数据质量提示，价值低。
- .lng 本地化文件格式：是 KKWE 自身 UI 文案存储机制，非从地图提取的数据；w3xray 字段标签走 fields.py/westrings.py 离线生成另一套，无格式借鉴价值。
