# KKWE 提取增强清单（多代理分析汇总）

## #1 [high价值/low成本] 全量 FIELD_LABELS：用 8 个 MetaData.slk 离线生成对象字段 4cc→中文映射（从 ~80 扩到 1100+）
**why**: w3xray fields.py 现仅手挑 ~80 个字段码，自定义对象/技能/科技/buff 的绝大多数字段在界面显示为原始 4cc。这是 w3obj.py 已解析二进制后最直接的可读性提升，且 w3xray 已具备全部所需基础设施（slk.py.parse_slk、westrings.py 8065 条），近乎零新增依赖。
**how**: 写一次性离线脚本（产物嵌进 fields.py，运行时零开销）：1) 用 latin-1 读取 KKWE 的 8 个文件 meta/units/{unitmetadata.slk, abilitymetadata.slk, upgrademetadata.slk, miscmetadata.slk, destructablemetadata.slk, abilitybuffmetadata.slk, upgradeeffectmetadata.slk} + meta/doodads/DoodadMetaData.slk；2) 对每个跑 slk.parse_slk()，得 {ID行键: {列名:值}}；3) 对每行取 code=ID(行键)、raw=row['displayName']，用下方 finding(rank2) 的 resolve() 把 WESTRING_* 解成中文；4) 合并 8 文件为 FIELD_LABELS[code]=中文，同 code 冲突保留首个；5) 同时产出 FIELD_TYPES[code]=row['type']。slk.py 按第1行列名动态定位 displayName 列，列顺序差异自动吸收，无需为各文件特判。NAME_FIELD 7 类已与这些表对应，不动。
**ref**: w3xray: w3xtool/fields.py:20-50(现 ~80 条), w3xtool/slk.py:12(parse_slk), w3xtool/westrings.py:4(WESTRINGS 8065 条); KKWE: plugin/.../script/meta/units/*.slk + meta/doodads/DoodadMetaData.slk

## #2 [medium价值/low成本] westring 多级解引用 + 控制符清理（FIELD_LABELS 生成的前置工具函数）
**why**: displayName 列的 WESTRING_* 可能链式别名（WESTRING_A→WESTRING_B→真实文本），现有 westrings.py 是合并产物但单次查表会漏链式键并残留控制符。是 rank1 落地的必需配套，成本极低。
**how**: 在生成脚本里实现 resolve(key)：若 key.upper() 不以 'WESTRING_' 开头直接原样返回；否则循环 k=WESTRINGS.get(k) or WESTRINGS.get(k.upper())，用 seen 集合防环，直到不再是 WESTRING_ 或查不到（查不到则回退原 4cc）；最后 re.sub(r'[\x00-\x1f]+','',k) 去控制符。仅用于离线生成，不进运行时。
**ref**: w3xray: w3xtool/westrings.py; KKWE: script/core/init.lua:81-119 (mt:get_editstring)

## #3 [high价值/low成本] war3map.wct 自定义脚本文本解析（导出每个触发器的 JASS/Lua 自定义代码）
**why**: 格式极简、成本极低，却能直接拿到地图作者手写的自定义 JASS/Lua 片段——对'看触发器'价值高。w3xray 现仅把 wct 原样导出。不依赖 TriggerData，独立可用。
**how**: 新建 wct.py，游标式读取：读 uint32 版本；若 >1 则该值==0x80000004，再读 uint32 真版本(断言==1)。然后全局块：cstr 注释 + int32 size（==0 空，否则 cstr 代码）。再循环触发器块（经典格式先 int32 count 循环 count 次；重制 0x80000004 格式无 count 循环到 EOF）：每块读 uint32 size，size==0 表示该触发器无代码（空串），否则读 size-1 字节为代码 + 跳 1 字节 NUL。复用 w3obj.py 的 _decode_str 做 UTF-8→GBK 回退。容错：size 越界/剩余不足即停，保留已解析部分。接入 api.py 的脚本展示。
**ref**: w3xray: w3xtool/api.py:26(SCRIPT_FILES 含 wct 但仅原样), w3obj.py:14(_decode_str); KKWE: script/core/slk/frontend_wct.lua:12-74

## #4 [high价值/medium成本] war3map.w3i 地图信息完整逐字段解析（版本 18/25/28/31）
**why**: 用户最想看的'地图信息'——地图名/作者/描述/玩家数与种族/队伍/迷雾/载入屏/脚本语言(JASS/Lua) 等，w3xray 完全未做。KKWE 给的是实战验证、版本分支齐全的权威布局，纯翻译无新算法。
**how**: 新建 w3i.py，复用 doo.py 的 _Reader 模式（i32/u32/f32/u8/tag + cstr 找 \0）。按 KKWE frontend_w3i.lua 顺序逐字段：起始 i32 version；header(version>=28 多读 4×i32 war3 版本)；cstr 地图名/作者/描述/推荐玩家(均经 wts.resolve 还原 TRIGSTR)；8×f32 镜头边界+4×i32；i32 宽/高；u32 flag 位域；c1 主地表。version>=25 续读载入屏(i32 id+4×cstr)/game_data_set/序章/雾(i32 type+3×f32+4×u8)/环境(c4 weather+cstr sound+c1 light+4×u8)；version>=28 i32 脚本类型(0=JASS 1=Lua)；version>=31 额外 2×i32。version==18 走旧分支(载入屏/序章仅 i32 id+3×cstr)。玩家段 i32 count×{i32 id,type,race,fixStart,cstr name,2×f32 start,2×u32 ally,[v>=31:2×i32]}；队伍/升级/科技/随机组/随机物品段。升级/科技/随机段前 peek 单字节==0xFF 判空早停。结尾不 assert，对不上保留已解析部分（w3xray 容错风格）。flag 位域解成 bit 列表。把字段挂到 MapData 新增的 w3i 结构上供界面展示。
**ref**: w3xray: w3xtool/doo.py(_Reader 模式可照搬), w3xtool/wts.py:56(resolve), api.py:30(已列 w3i 为导出但未解析); KKWE: script/core/slk/frontend_w3i.lua:42-350

## #5 [high价值/low成本] 三层并集文件枚举：(listfile) + 内置静态名单 + imp 清单（补全无 listfile 的保护图）
**why**: w3xray mpq.list_files() 现仅读 (listfile)；保护图常删/伪造它，导致固定名地图文件与导入资源漏抓。三层并集成本低、对保护图覆盖率提升明显。imp.py 已能解析但产出未回流到枚举。
**how**: 在 mpq.py 加 enumerate_files()：mark=set(); files=[]; 依次遍历三来源，对每个 name 做 lname=name.lower() 去重，再 has_file(name) 验证存在才收。来源(a) 现有 (listfile)；(b) 硬编码 STATIC_MAP_FILES 常量(小写)：war3map.j/.doo/.imp/.mmp/.shd/.w3c/.w3e/.w3i/.w3r/.w3s/.w3a/.w3b/.w3d/.w3h/.w3q/.w3t/.w3u/.wct/.wpm/.wtg/.wts、war3mapextra.txt、war3mapmap.blp/.tga、war3mapmisc.txt、war3mapskin.txt、war3mapunits.doo、war3map.txt.ini、war3mappath.tga、(attributes)、(signature)、war3campaign.w3f/.imp/.wts；(c) imp.parse_imp 的每个 name 先试原名，has_file 失败再试 'war3mapimported\\'+name。把 list_files() 改为返回此并集（或新增方法并让 api.py 改用）。
**ref**: w3xray: w3xtool/mpq.py:495-509(list_files 仅 listfile), w3xtool/imp.py:16(parse_imp), api.py:378/410/569(用 list_files); KKWE: script/core/map-builder/load.lua:4-82, core/info.lua:128-149(impignore)

## #6 [high价值/medium成本] 轻量 JASS tokenizer 抽取全部 4cc 对象码（替代逐行正则 + 按 native 名硬分类）
**why**: script_scan.scan_object_refs 现按 native 名逐行正则，会漏跨行参数、漏裸 ID 常量、按 native 名猜类型易错分。词法级扫描更可靠且能统一产出 ids 集合再用已解析对象表反查归类。
**how**: 在 script_scan.py 加状态机 tokenizer 扫一遍 war3map.j：识别并跳过 //注释到行尾、整体跳过双引号字符串(避免误抓引号内文本)；对每个整数/rawcode 字面量产出候选 ID：(a) 'xxxx' rawcode 取引号内最多 4 字节原样；(b) 0x.. 或 $.. 十六进制 int(s,16)，若 >=0x41303030('A000') 则 struct.pack('>I',v) 得 4 字节码；(c) 十进制整数同阈值过滤后 pack('>I')。阈值 0x41303030 是关键去噪点。产出统一 ids 集合（不强分物品/单位），再用已解析的 w3u/w3t/w3a 等对象表反查归类。保留现有正则做聊天指令/配方（那部分仍有效），仅替换 scan_object_refs 的取码方式。
**ref**: w3xray: w3xtool/script_scan.py:82-93(_codes_in), 137-152(scan_object_refs); KKWE: script/core/slk/backend_searchjass.lua:92-142

## #7 [medium价值/medium成本] TRIGSTR 在 war3map.j / wtg / wct 文本中的内嵌还原（让触发器文本可读）
**why**: 现 resolve() 只处理对象数据里的 TRIGSTR 字符串字段；脚本与触发器文本里的 "TRIGSTR_NNN" 引用未还原，导出的触发器文本仍是占位号。配合 rank3(wct)/rank4(w3i) 提升整体可读性。
**how**: 在导出脚本/wct 文本时做两类替换（用现有 wts 表）：(1) war3map.j/.lua 文本：re 匹配 rb'"TRIGSTR_(\d{3,})"'，把带引号 token 整体替换为 wts 文本并做 jass 转义(\→\\、"→\")；(2) 二进制 wtg/wct：re 匹配 rb'TRIGSTR_(\d{3,})\x00'，用 wts[sid]+\0 替换。数字至少 3 位、wtg 以 \0 终止；缺失引用单点降级保留原 token（w3xray resolve 已是此安全行为）。可加可选开关，默认对导出文本生效。
**ref**: w3xray: w3xtool/wts.py:56-64(resolve 仅对象字段); KKWE: backend_convertwtg.lua:21-23, backend_convertjass.lua:25-28

## #8 [medium价值/low成本] 对象字段值列表化显示（concat_types + FIELD_TYPES）
**why**: abilityList/unitList/buffList 等多值字段应按逗号/竖线拆分展示而非单值。锦上添花，依附 rank1 已产出的 FIELD_TYPES，几乎零额外成本。
**how**: 把 KKWE metadata.lua:9-76 的 concat_types 照抄为 Python CONCAT_TYPES dict（abilityList/unitList/buffList/targetList/effectList/intList/techList/itemList/stringList/unitClass/modelList/lightningList/unrealList/upgradeList/pathingListPrevent/pathingListRequire/tilesetList/attackTable/defenseTable=True，其余 False）。显示字段值时若 CONCAT_TYPES.get(FIELD_TYPES.get(code)) 为真，按逗号/竖线拆分展示，列表内 4cc 项可二次查 FIELD_LABELS/对象名。
**ref**: w3xray: rank1 产出的 FIELD_TYPES, w3obj.py:39(var_type); KKWE: script/prebuilt/metadata.lua:9-76

## #9 [medium价值/low成本] 地图名/作者优先取 w3i 的 MAP_NAME/AUTHOR（HM3W 头兜底）
**why**: HM3W 头名常是占位/旧名甚至 TRIGSTR；编辑器里设的真实名在 w3i 的 MAP_NAME（可能 TRIGSTR 需 wts 还原）。修正一批显示占位名/TRIGSTR 的地图。改动小，依附 rank4。
**how**: rank4 的 w3i 解析落地后，_map_name() 改为：先尝试 w3i 的 MAP_NAME（经 wts.resolve 还原 TRIGSTR），非空且非 TRIGSTR 残留则用之；否则回退现有 HM3W 头名；再否则文件名。quick_map_name 仍用 HM3W（不解析整 MPQ）保持目录列表快速。
**ref**: w3xray: w3xtool/api.py:272-296(_map_name/quick_map_name 仅 HM3W); KKWE: frontend_w3i.lua:59

## #10 [medium价值/medium成本] 提取完整性自检：枚举到的文件数 vs block 表有效条目数
**why**: 让保护图提取覆盖率对用户透明——抓不全时提示'存在 N 个无法按名定位的隐藏文件，可提供外部 listfile'。成本低，依附 rank5。
**how**: 在 mpq.py 暴露 number_of_files()=block 表中 flags 含 MPQ_FILE_EXISTS(0x80000000) 且非删除/非空洞的条目数。rank5 枚举完成后比较 len(recovered) 与该数，差值>0 输出告警。可选增强：对未命名 block 用 peek_block(已有) 读前 4 字节 magic 盲猜类型（HM3W=w3i、BLP1/BLP2=blp、MDLX=mdx、W3do=doo）。
**ref**: w3xray: w3xtool/mpq.py:461(peek_block 已有), block_table; KKWE: backend/cli/unpack.lua:136-145

## #11 [medium价值/low成本] war3map.w3f 战役信息头部解析（6 字段）
**why**: w3xray 已处理战役(.w3n)但未解析 w3f，无法显示战役名/作者/难度/描述。头部 6 字段成本极低；战役占比少故价值中。
**how**: 在 w3i.py 或新 w3f.py 加最小头解析：i32 version；i32 campaign_version；i32 editor_version；cstr 战役名/难度/作者/描述（后三 cstr 经 wts.resolve 还原）。KKWE 自身也只解到头，后续战役地图列表段暂缺（需另找 HiveWE 规范，价值不足暂不做）。接入战役展示。
**ref**: w3xray: w3xtool/api.py(战役 .w3n 处理 381-401); KKWE: script/core/slk/frontend_w3f.lua:16-39

## #12 [medium价值/low成本] extra_func / need_mark 两张 BJ→隐式对象引用静态映射表
**why**: 图作者用暴雪内置开局/随机刷怪 BJ(MeleeStartingUnitsHuman、ChooseRandomItem 等)时，引用的对象码写死在 BJ 内部，任何脚本扫描都抓不到。纯数据搬运，零算法成本，让'这张图实际用了哪些对象'更完整。
**how**: 把 KKWE backend_searchjass.lua:11-47 的 extra_func（~14 个 BJ 函数名→内置对象码列表，如 MeleeStartingUnitsHuman→hpea/Hamg/htow…）和 need_mark（ChooseRandomCreep/Item、InitNeutralBuildings 等→creeps/building/item/marketplace 标记）转成 Python dict 常量。在 rank6 tokenizer 扫到标识符 token 命中 extra_func 时把对应码加入 ids 集合；命中 need_mark 记 flag。
**ref**: w3xray: w3xtool/script_scan.py; KKWE: script/core/slk/backend_searchjass.lua:11-47

## #13 [low价值/low成本] doo.py 装饰物 v8 的 4 字节格式变体兜底（暴雪改格式不改版本号）
**why**: 某些重制版图在 version>=8 时 7 个 float 后紧跟一个等于该条 type_id 的多余 4 字节，会导致 doo.py 错位。doo.py 已对等且更细，仅缺此一处健壮性补丁。
**how**: 在 doo.py 装饰物循环(约 107-125 行)读完 7 个 float 后、读 vis/life 之前，对 version>=8 加 peek：窥探下 4 字节是否等于刚读的 tid，若相等则跳过这 4 字节再继续。无 4 字节 peek 接口则用 r.d[r.p:r.p+4] 比较后手动推进 r.p。
**ref**: w3xray: w3xtool/doo.py:96-125; KKWE: script/core/slk/backend_searchdoo.lua:31-34

## #14 [medium价值/low成本] WTS 解析加固：注释行处理 + 行首独占 { 定位 + ACP 编码回退
**why**: 三个低成本健壮性点合并：(a) 现用 data.find(b'{') 找正文起点，注释行 '// foo {bar}' 含 { 会错位；(b) 简中以外系统应优先系统 ACP 而非硬编码 gbk，繁中/日文老图否则全损。当前对纯简中环境无害，故价值中。
**how**: (1) parse_wts 中把 brace=data.find(b'{') 改为用行锚定位真正独占一行的 {：在 STRING 头之后逐行跳过可选空白+// 开头的注释行，遇到 strip 后==b'{' 的行作为正文起点（与 _CLOSE 的 (?m)^\}[ \t]*$ 对称）。(2) _decode_str 回退顺序改为 UTF-8 → mbcs(系统 ACP，仅 Windows 可用，非 Windows 跳过) → gbk(跨系统兜底) → utf-8 replace。同样可应用到 w3obj._decode_str/imp 解码。
**ref**: w3xray: w3xtool/wts.py:44(data.find b'{'), 19-27(_decode_str); KKWE: frontend_wts.lua:21-39, script/ffi/unicode.lua:7-22(CP_ACP)

## 不建议做
- war3map.wtg GUI 触发器完整 ECA 树解析（effort high）：ECA 体逐参数推进强依赖 TriggerData.txt（每函数参数个数），无它会错位；经典 v7 与重制 0x80000004 分支差异大。可做的低成本子集已被 rank3(wct 自定义代码)覆盖；若只想要目录树+触发器名+变量清单可作为 rank4 之后的可选小增量，但完整 ECA 不划算。
- TriggerData.txt 解析（wtg 完整 ECA 的前置）：仅在做完整 ECA 树时才需要，且要内置/区分经典 old-reader 与重制 new-reader 两套格式，成本高、收益仅服务于上一条不划算项。
- CASC（重制版客户端基础数据）读取：纯 Python 需实现 .build.info/CDN config/encoding/root/.idx 索引/BLTE 解块/Salsa20，effort 极高；且只影响'从客户端取游戏基准数据'，不影响读单张 .w3x（地图本身仍是 MPQ）。建议仅在文档标注'重制版客户端数据不支持'并记录判据(安装目录有 Warcraft III.exe 且版本 minor>=29)与虚拟路径方案 war3.w3mod: / _locales\<lg>.w3mod: 即可。
- war3map.w3e 地形解析：KKWE 根本无 w3e 解析器（把地形当二进制原样保留），无法借鉴；需另找 HiveWE/wc3lib 规范，解析量大而对'看地图信息'价值低。
- 完整 JASS PEG/AST parser（grammar.lua/parser.lua/checker.lua）：几千行文法+语义+检查，远超'静态抽对象码'目标；KKWE 自己抽码也不用它而用轻量 searchjass。rank6 的词法级 tokenizer 已足够。仅 Integer256/Char16 的四种整数边界定义可作 tokenizer 校准参考。
- metadata.lua 的 parse_id/characters 后缀推导与 repeat 分级：仅用于 SLK/INI 文本格式的派生列名（DataA、_2 等）；w3xray 读二进制 .w3a/.w3u 时 field_id 就是 MetaData 的 ID 行键本身，可直接查 FIELD_LABELS，无需此推导。w3xray 也不导出 SLK。
- JASS 混淆器特征/converter 字面量规范化/KKAPI.DzAPI native 声明：均为运行时或单向不可逆，无静态可提取逻辑。弱信号(识别混淆图、$XXXX 十六进制整数写法、Dz* 依赖标记)可顺手记入，但不值得专门开发。
- imp 名转义为磁盘安全文件名($XX 方案)：仅当落盘文件名含 ':'/控制字符(主要是 CASC 名)才需要；w3x 地图导入名极少触发，且 w3xray 不支持 CASC。可在遇到 Windows 非法字符报错时再按需补，暂不优先。
- WTS 正文含 } 的告警：w3xray 是只读提取器，_CLOSE 已正确处理独占行 }，正文内 } 字符不影响读取（仅影响回写，而 w3xray 不回写）。纯数据质量提示，价值低。
- .lng 本地化文件格式：是 KKWE 自身 UI 文案存储机制，非从地图提取的数据；w3xray 字段标签走 fields.py/westrings.py 离线生成另一套，无格式借鉴价值。