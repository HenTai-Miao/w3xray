# 进度日志

## 会话 1 — 2026-06-08

### 已完成（全部 9 个阶段）
- 调研原软件：魔兽 III 作弊工具盒子；本任务只做合法的"地图提取"。
- 环境：Python 3.14.4 + uv 0.11.18；StormLib.dll 为 32 位(弃用)，改纯 Python。
- **Phase 1** uv init 项目 w3x-extract，建规划文件。
- **Phase 2-3** mpq.py + explode.py：MPQ 头定位/表解密/扇区解压；PKWARE DCL 解压
  移植 blast.c。真实地图验证：war3map.j(2.5MB) 等全部正确解出。
- **Phase 4** w3obj.py：解析 w3u/w3t/w3a/w3q/w3b/w3d/w3h，缓冲完整消费。
  实测 单位751 物品51 技能719 科技6 可破坏物20 装饰物82 增益137。
- **Phase 5** 脚本提取 war3map.j/lua/wts/wtg/wct。
- **Phase 6** 战役 .w3n 递归解包（已写，缺真实 .w3n 验证）。
- **Phase 7** wts.py + fields.py：TRIGSTR→中文名(如 Hpal→H000=圣骑士格罗姆)。
- **Phase 8** gui.py：CustomTkinter 深色风，搜索/分类/详情/导出；冒烟测试通过。
- **Phase 9** PyInstaller 打包 `dist/魔兽地图提取器.exe`（13MB 单文件），实测启动运行正常。

### 决策
- GUI 框架：用户选 CustomTkinter（深色卡片风）。
- 包管理：用户要求用 uv，不直接调 python。

### 会话 2 追加（2026-06-08）
- 备份可用版到 `地图提取工具_备份_v1_可用版`。
- **Phase 10** w3e.py：地形解析+俯视渲染(289x353)，PNG 验证湖/草/路清晰。
- **Phase 11** doo.py 解析 212 放置单位(剩余0字节正确)；w3i.py 解析全局物品表。
  本测试图无编辑器掉落(脚本控制)，已在UI如实标注。
- **Phase 12** mapview.py：CTk 画布+地形底图+200可点击单位标记+平移缩放+信息/掉落面板。
- **Phase 13** script_scan.py：扫 war3map.j 聊天指令，104 条(含 -isee/-kill/-main…)。
- gui.py 重构为三标签页(对象浏览/地图视图/隐藏指令)，全功能冒烟+截图验证通过。
- **Phase 14** 重新打包 exe(18.9MB)，实测运行正常。

### 会话 2 后续追加
- 地图视图卡顿修复：平移用 canvas.move、缩放封顶≈11x。
- **Phase 15** build_base_names.py 从游戏 MPQ 提取 2028 个原版中文名→base_names.py；
  api/mapview 在无自定义名时回退，nckb→邪恶的科多兽。
- **Phase 16** 批量测 10 张图：自定义物品全提取(8F9CC 达1237)；几张"0物品"图实为无 w3t。
- **Phase 17** script_scan.scan_recipes：以"添加成品"为锚点收集前面"移除材料"；316821 准确提 2 配方。
  新增「合成配方」标签页(名称解析+重复材料折叠)。
- **Phase 18** 重新打包 exe(19.0MB)，4 标签页。

### 待办 / 已知限制
- 战役 .w3n 路径未用真实文件验证。
- 字段中文标签为精选子集，未收录的码显示原 4 字符（完整需游戏 MetaData.slk）。
- (listfile) 常不全 → 解包用"已知文件名 + listfile"合并兜底。
- **掉落**：仅对使用编辑器掉落表的地图显示；脚本控制掉落(如杂交版)无法逐怪自动提取。
- 指令"说明"为best-effort(同名触发动作里的提示文本)，不一定每条都有。

### 会话 3 追加（2026-06-09）
- 复现千风物语(`9CA7355453A11A7828F5CF54135B7368.w3x`)：普通解析对象/脚本/listfile全空。
- 根因：MPQ header size 被写成 `CAME`，hash/block 表位置以 signed int32 负偏移保存。
- mpq.py 增加 CAME/负偏移表恢复：该图恢复出 8 个 block，可读 w3i/mmp/blp/空 war3map.j。
- api.py 增加匿名 block 识别：导出 `KKWE PLUG-IN ENCRYPT JASS!` 载荷、PE loader、匿名 JASS loader。
- export_all_files 现在会写 `protected_blocks/anonymous_*.kkwe/.pe/.j`。
- GUI 保护提示改为显示真实检测特征(CAME/KKWE/匿名loader)，不再误写 HET 表。
- 单测：新增 `tests/test_protected_maps.py`，覆盖 CAME 表恢复、匿名载荷保留、导出、匿名 JASS 指令扫描。
- 验证：千风物语可静态导出 7 个文件；普通图"魔兽争霸杂交版1.00d"不再被误标 protected。
- 边界：千风物语真实业务脚本仍在 KKWE 加密载荷中；当前工具不执行内嵌 loader、不注入游戏、不做运行时 dump，因此对象/配方/指令仍可能为 0。
- 追加取证：内嵌 PE 是 32 位 DLL，只有 `init` 导出，含 `.tvm0/.tvm1/.tvm2` 虚拟化节和 OpenSSL/AES 字符串；匿名 JASS loader 通过 DzAPI/Frame API 做内存参数传递。
- export_all_files 追加 `protected_blocks/manifest.json`，记录保护块类型/大小和"完整业务脚本需要 KKWE 解密或运行时 dump"说明。
- main.py 追加 `analyze <地图路径>` 命令，输出保护状态、检测特征、对象/脚本统计和下一步提取策略。
- load_map/scan_commands/scan_recipes/analyze 支持外部解密脚本参数；GUI 增加「导入解密脚本」，可用合法 war3map.j/lua/dump 补提对象引用、隐藏指令、合成配方。
- 追加 KKWE 静态恢复：解析 KKWE 头和 zlib 分块；如果恢复出 JASS，自动作为 `.recovered.j` 扫描对象引用/指令/配方；如果恢复后仍是二进制，则导出 `.recovered.bin` 并在 manifest 记录摘要、JASS 标记和对象引用计数。
- 千风物语实测：KKWE 6 个 zlib 分块恢复出 393210 字节，但 `recovered_text_kind=binary`、`globals/function=0`、物品/单位引用=0；MPQ 声明 archive 后还有 412752110 字节高熵追加数据。因此静态工具已走完可安全路径，完整物品/科技/技能/单位仍需合法 KKWE 解密器、源码或运行时 dump。

### 会话 4 追加（2026-06-09）——精简，回归"正常地图提取器"
- **搜索升级**：四个搜索框支持 AND+OR（空格=且，竖线|=或，如 `智力 剑|法杖`）；`fuzzy_score` 改多关键词。
- **字体**：全局字体改 JetBrains Mono（gui.py/mapview.py 的 FONT + 详情框；中文走系统回退）。
- **删除「地图视图」**：移除 mapview.py / w3e.py / doo.py / w3i.py 四个模块、api 的 `load_map_view`/`MapViewData`、GUI 标签页与放置单位统计。标签页由 4 个减为 3 个（对象浏览/隐藏指令/合成配方）。
- **删除「运行时提取器」+ 整套千风/保护图子系统**（用户决定放弃提取千风，全删）：
  - 删 `w3xtool/runtime_dump.py`、`runtime_dump_cli.py`、`魔兽地图运行时提取器.spec` 及其 exe。
  - mpq.py 删 CAME/负偏移保护头恢复（`_repair_protected_table_offsets`/`_range_ok`/`protected_header`/`protection_features`）。
  - api.py 删 KKWE 静态恢复(`_analyze_kkwe_payload` 及 zlib/熵/采样辅助)、匿名 block 识别、外部解密脚本(`_add_external_scripts`/`extra_scripts`)、`describe_extraction`、protected_blocks/manifest 导出。`MapData` 去掉 `protected`/`protection_features`。
  - gui.py 删「导入解密脚本」按钮与保护图提示；main.py 删 `runtime-dump`/`analyze` 命令。
  - 删 `tests/test_protected_maps.py`（全是保护图测试）→ **目前无测试**，待补正常地图主路径单测。
- 验证：`魔兽争霸杂交版1.00d.w3x` 解析正常（单位1040/物品181/技能941/科技63/可破坏物20/装饰物82/增益137，指令104）；包导入无残留引用。
- 重新打包 `dist/魔兽地图提取器.exe`（约 20.1MB）；运行时提取器 exe 已删除。

### 会话 4 优化（superpowers 评审 + TDD）
四路评审梳理出优化点，按 TDD（先写失败测试再修）落地高优先项：
- **路径穿越修复**（安全）：`export_all_files` 用不可信的 MPQ 内部文件名拼接输出路径，绝对路径/`..\\` 可写到目录外。新增纯函数 `api._safe_export_path`，拒绝穿越/盘符 + commonpath 兜底。测试 `tests/test_export_safety.py`（6 例）。
- **解压炸弹防护**（安全/DoS）：`_decompress_sector(data, out_size)` 各分支（zlib/bz2/sparse/explode）按 out_size 硬封顶；`_sparse_decompress`/`explode` 加 `max_output`。合法图扇区正好解出 out_size，不受影响（杂交版 war3map.j 仍完整 2.57MB）。测试 `tests/test_decompress_limits.py`（5 例）。
- **消除重复打开 MPQ**（性能）：打开一张图原本 `load_map`+`scan_commands`+`scan_recipes`+`IconResolver` 各开一次归档；新增 `api.commands_from_map(md)`/`recipes_from_map(md)` 复用 `md.scripts`，GUI 改用之，少开 2 次。测试 `tests/test_map_reuse.py`（3 例）。
- **异常不再静默**：GUI 指令/配方扫描失败时 `traceback.print_exc()`，区分"真无"与"扫描出错"。
- **打包**：spec 关闭 UPX（加快启动+免杀）、加 `excludes` 裁标准库；启动实测正常。onefile→onedir 待用户确认。
- 测试从 0 → 14 例全过。仍待补：对象二进制解析、textobj.classify、fuzzy_score 的直接单测。

### 会话 4 优化（续）：BLP 向量化 + 补测试
- **BLP 调色板解码向量化**：把逐像素 Python 循环改成 PIL `"P"` 模式 + 调色板，C 层批量展开；
  抽出 `blp._palette_rgba` 共用于 BLP1/BLP2，截断等异常仍回退逐像素保持原语义。
  实测 256×256 解码 **43x 提速**，输出逐字节一致。测试 `tests/test_blp.py`（2 例特征测试）。
- **搜索算法外置**：`fuzzy_score`/`_single_score` 从 gui.py 抽到 `w3xtool/search.py`（架构更清晰、可独立测试），
  gui.py 改为 import。测试 `tests/test_search.py`（12 例，覆盖 AND/OR/子串优先/全角竖线）。
- **补核心解析器测试**：`tests/test_w3obj.py`（3 例：原始/自定义表、带等级 w3a、未知类型报错）、
  `tests/test_textobj.py`（5 例：分类按字段特征/代码前缀/默认物品）。
- 测试合计 **36 例全过**；重新打包 exe（20.1MB），实测启动正常。

### 会话 4 优化（续2）：MPQ 头 DoS 硬化 + 游戏 MPQ 缓存
- **MPQ 头校验**（安全/DoS）：`mpq._validate_header` 拒绝非法表大小——hash 表必须是 2 的幂、hash/block 表必须放得进文件。
  修复前恶意头写超大 `hash_count` 会让 `range(hash_count)` 跑数十亿次卡死；现在瞬间拒绝。测试 `tests/test_mpq_header.py`（3 例，含 4 billion）。删保护图支持后可严格校验，不再误伤正常图（杂交版 hash 2048 正常）。
- **游戏 MPQ 进程级缓存**（性能）：`icons._open_game_mpq` 按路径缓存 war3.mpq 等大档，跨地图复用。
  实测 war3.mpq 首开 57ms → 缓存命中 0.002ms；之后每次打开地图都省下游戏档重复扫头+解密表。测试 `tests/test_icons_cache.py`。
- 测试合计 **40 例全过**；重新打包 exe，实测启动正常。

### 会话 4 优化（续3）：onefile → onedir
- spec 改 onedir（EXE `exclude_binaries=True` + `COLLECT`）：产物为 `dist/魔兽地图提取器/魔兽地图提取器.exe` + `_internal/` 依赖，启动不再每次解压 ~20MB 到临时目录。实测窗口 1.77 秒出现，启动正常。
- 分发改为把整个 `dist/魔兽地图提取器/` 文件夹打 zip。README 已更新。

### 会话 5：战役(.w3n)完整提取
背景：战役有三层内容（顶层 war3campaign.* 共享对象 / 各子图 war3map.* / 资源），原本打开 .w3n 三页全空（顶层 0 对象，子图 sub_maps 在 UI 看不到）。实测 `206774.w3n` = 7 子图 + 2050 顶层共享对象。
- **A 战役级共享对象**：`_build_objects` 加 `prefix` 参数；load_map 对 .w3n 额外用 `war3campaign.*` + `war3campaign.wts` 解析顶层共享对象（824单位/313物品/703技能…共 2050）。`tests/test_campaign.py`。
- **B 子地图浏览 UI**：顶部加「子地图▾」下拉（`CTkOptionMenu`），打开战役时显示，条目 = ★战役共享 + 7 子图共 8 项；选哪项三页就渲染那张（`_prepare`/`_render_map` 复用，`_set_campaign_views`/`_view_md`/`_on_submap_change`）。普通图隐藏。`tests/test_gui_campaign.py`。
  - IconResolver 加 `extra_paths`：子图图标可回退到战役顶层档查找（子图档→战役档→游戏MPQ）。
- **C 递归导出 + 全进 TMP**：`export_all_files` 默认导到 `%TEMP%/w3xtool提取/<名>/`，战役递归把每张子图内部导到子文件夹；新增 `tmp_extract_dir`。GUI 三个导出按钮（全部文件/脚本/ID）改为直接写 TMP、不弹选目录框、导完自动打开文件夹（用户要求"提取的都是临时文件"）。
- 端到端实测 `206774.w3n`：下拉 8 项、默认显示共享 2050 对象、切到 XSHZ-2 显示 1167 对象/3 指令、四列正确填充。
- 测试 0→**46 例全过**；onedir 重新打包，实测启动正常。

### 会话 5 续：UI 重构为两级导航 + 美化
用户反馈原 UI 太挤太丑（下拉框塞顶栏）。重新设计：
- **一级「对战图｜战役图」分段控件**（`CTkSegmentedButton`，居中），二级仍是对象浏览/隐藏指令/合成配方。
- **左侧列表按模式切换内容**：对战图=文件夹地图列表(+选择目录按钮)；战役图=★战役共享对象+各子图。撤掉顶栏子地图下拉。`_on_mode_change`/`_populate_left`/`_left_items_for_mode`/`_refresh_left_list`；`_on_map_pick` 按 kind(path/md) 分流。打开 .w3x→对战图、.w3n→战役图自动切。
- **美化**：树行高 24→32、字号 10→11、滚动条融入深色、Heading flat；默认窗口 1180→1380 让详情面板默认完整可见。
- **布局版本号** `_LAYOUT_VERSION`：布局变更后忽略旧的分隔条配置，避免老用户升级后详情被挤掉。
- 端到端实测：战役下拉 8 项、切子图、回退对战图均正常；测试 47 例全过；onedir 重新打包启动正常。

### 会话 5 续2：战役图也加「选择地图目录」+ 树形列表
用户要求战役图模式也有选择目录/刷新。改成树形：
- 战役图左侧 = 树：`选择地图目录` 扫出文件夹里的 .w3n 战役做**父节点**，展开(`<<TreeviewOpen>>`)才懒加载该战役并列出子地图(★共享+各关卡)；点子地图看内容。
- `_scan_dir` 拆分 .w3x/.w3m(对战图扁平列表) 与 .w3n(战役图树)；`_node_map` 映射树节点 iid→(kind,payload)；`_refresh_campaign_tree`/`_on_tree_open`/`_load_campaign_node`。
- 单独「打开战役」会把该战役并入树（已加载、展开）。两种模式都显示选择目录按钮。
- 测试 49 例全过（test_gui_campaign 改树形模型）；onedir 重新打包启动正常。
- 注意：截图改用让用户直接看运行的窗口，不再用 ImageGrab 盲抓屏（会抓到屏幕上其它窗口，不安全）。

### 会话 5 续3：目录/交互细节修复（用户反馈）
- **每模式各记各的目录、各扫各的列表**：原来一次扫描同时填对战图+战役两个列表、共用一个目录，给两模式选不同目录会互相覆盖。改为 `_scan_dir(d, mode)` 只扫该模式（对战=.w3x/.w3m，战役=.w3n）、`_fill_battle`/`_fill_campaign` 只填各自列表；`_cur_dir={battle,campaign}`。
- **两模式目录持久化**：config 存 `last_dir_battle`/`last_dir_campaign`，启动分别恢复（兼容旧 `last_dir`）。
- **战役选目录零解析**：战役列表只用文件名(basename)，不读不解析；点某战役(展开/点击)才 `load_map`。
- **左侧地图列表改双击加载**：`<Double-1>`（单击只选中，双击才加载/切换）；对象列仍单击出详情。
- **右键复制/粘贴**：`_attach_ctx_menu`——四个搜索框(复制/剪切/粘贴)、详情框(复制全部)。
- 测试 51 例全过；onedir 重新打包启动正常。

### 会话 5 续4：子地图脚本引用取共享对象真名 + 全地图审计
- **修复光秃秃脚本条目**：子地图独立解析、不认识 war3campaign.* 共享对象，脚本引用它们时只显示光秃秃码。`load_map` 把战役共享对象索引传给子地图，`_add_script_refs(shared_index)` 命中即用共享对象真名/分类/字段（标〔战役共享〕）。XSHZ-1：光秃秃 33→0，29 个解析为共享对象(H600=法师等)。测试 `test_submap_resolves_campaign_shared_names`。
- **全地图逐文件审计**（206774 + 182537 两战役含全部子图 + 杂交版对战图）：每个对象文件零解析失败、名字解析率 96~99%、war3map.j 真 JASS、指令正常；无"含目标数据却漏掉"的文件类型。小瑕疵：约 6 个系统技能/buff 码(edol/htws/ugsp/Ansp/Stpm)无名、配方识别仅覆盖标准 YDWE 写法。
- 测试 52 例全过；onedir 重新打包。

### 会话 5 续5：去掉无名原版对象噪声
- 审计发现的"每图都冒的 6 个光秃秃码"(edol/htws/ugsp 单位 + Ansp/Stpm/Stpr 技能)根因：它们在 BASE_OBJECTS(游戏 *Data.slk)里有、但 *Strings/*Func 没给显示名（系统内部对象）。`_add_base_objects` 现在跳过无名原版对象。
- 效果：战役子图光秃秃条目清零(XSHZ-1: 6→0)，杂交版去掉这 6 个 base 噪声。剩余少量光秃秃码是地图自己定义但作者没起名的内部技能/buff（字段都在，无名可查，非漏提）。
- 测试 54 例全过；onedir 重新打包。

### 会话 5 续6：补评审缺口（脚本扫描覆盖面 + 不再全静默）
- 评审结论：对用户实际地图(JASS)已完善实测正确；以下为其它地图类型的缺口，本次补可补的：
  - ① Lua `FourCC("xxxx")`：`_codes_in` 增 `_FOURCC_FN` 识别双引号/FourCc 函数写法。
  - ② 聊天指令 `...ChatEventBJ`：`scan_chat_commands` 增 `_CHAT_BJ`（参数顺序不同）。
  - ③ `_build_objects` 解析失败打 stderr 告警(cli/控制台可见)，不再完全静默；畸形文件仍优雅返回空。
- 核实为误报/不改：`.doo`(放置实例,非定义)、战役 `text_cats`(顶层 text 与 war3campaign 同归档,逻辑一致)。
- explode 原生提速：实测 explode 占加载时间 0%（这些图用 zlib 非 PKWARE），划掉不做。
- 测试 62 例全过；onedir 重新打包。
- 剩余(可选)：Lua 配方按函数切分仍是 JASS 风、.doo 放置解析、UI 内可见的解析失败提示。

### 会话 5 续7：隐藏指令/合成配方/对象列 右键复制
- 之前只有搜索框/详情框能右键复制；表格(Treeview)不能。新增 `_attach_tree_copy`/`_copy_tree_row`：右键复制选中行（指令="指令\t说明"、配方="成品\t材料"、对象列=名字），挂到 cmd_tree/rec_tree/四个 col_trees。
- 测试 `tests/test_gui_copy.py`（3 例，验证剪贴板内容）；共 65 例全过；onedir 重新打包。

### 会话 5 续8：右键去剪切 + 搜索独立 + 搜索框居中（用户反馈）
- 右键菜单去掉「剪切」，只留复制/粘贴（`_attach_ctx_menu`）。
- 切换对战图/战役图时清空左侧搜索框（`_on_mode_change` 加 `map_search.set("")`）——战役与对战是两套独立列表。三个标签页搜索框本就各搜各的（已确认）。
- 4 个搜索框文字改居中（CTkEntry `justify="center"`）。
- 65 例全过；onedir 重新打包。

### 会话 6：删 AI 功能 + 修保护图提取（block 表注水越界）
- 用 superpowers 流程删除全部 AI 调用层(`w3xtool/aicli/`)与本地诊断层(`audit.py`/`tools_audit.py`)及对应 UI/标签页/测试/提示词；工具回归纯提取/浏览，顶栏只剩打开+导出，标签页三个。
- 修复保护图提取：`|cffff99cc幻想未来v1.366`(war3/Maps/dz/rpg/46419190…w3x) 原报 `MPQ block 表越界` 打不开。根因=该图把 MPQ 头 `block_count` 注水(2049)、block 表声明长度超出文件尾约 16KB(实际仅 ~1006 条在档内)，`header_size` 也填成 0xFFFFFFFF 哨兵。`_validate_header` 原要求整张 block 表落在文件内→直接拒。
- 修法(最小面)：block 表只校验"起点在文件内"，越界尾部交给 `_read_tables` 既有截断(avail=实际字节//16)，下游 `read_file` 本就挡 `block_index ≥ len(block_table)`；与 StormLib 行为一致。hash 表保持严格(既正确性也反 DoS，挡 range(hash_count) 卡死)。
- TDD：新增 `test_block_table_past_eof_tolerated`(先看它以 block 表越界失败→改后通过)；反 DoS/诱饵头测试不受影响。全套 97 例通过。
- 实测该图现可提取：4320 对象(物品1080/技能1954/单位870/科技165/增益246/装饰物5/可破坏物3)、war3map.j、2 隐藏指令、14 合成配方、导出 13 个文件。
- onedir 重新打包。

### 会话 7：修精准搜索词边界（等级:E 误命中 等级:EX）
- 用户反馈：`"敏捷" | "全属性" "等级:E"` 在 `幽罗世界RPG1.41`(war3/Maps/dz/rpg/0F11C72E…w3x) 仍捞出一堆 EX 装备。根因=精准词是纯子串，`等级:E` 把 `等级:EX` 也吃了；该图物品等级档为 E/F/D/C/B/A/S/S+/EX，各档独立。
- 修法：`_exact_score` 加 ASCII 词边界——精准词以 ASCII 字母/数字结尾时，其后一字符不能也是 ASCII 字母/数字（开头同理）；中文端点不设边界（保留 全属→全属性 这类紧邻命中）。多处出现时跳过粘连处继续找下一处。
- 实测：`"等级:E"` 由 31 命中(含 19 个 EX)收敛为 12 个纯 E；组合查询由 17(混 EX) 收敛为 6 个纯 E。
- TDD：`test_search.py` 加 3 例(尾/头边界 + 真实组合查询)，先红后绿。
- 续：把 `+` 也并入"词内字符"，使 S 与 S+ 分档——`"等级:S"`(36 全 S，修前 70 混 S+)、`"等级:S+"`(34 全 S+)。加 1 例(加号边界)，全套 112 逻辑测试通过(GUI tk 测试在无头环境偶发 TclError，单跑即过)。

### 会话 8：搜索改 SQL 语法 + 暴力测试 + GUI 测试隔离 + 全项目优化 + 单实例
- **搜索语法重写为 SQL 风格**（用户要求按 SQL 来）：`%x%`包含/`x%`前缀/`%x`后缀/`a%b`中间通配（`%`通配符、不分大小写、裸词按`%x%`、不做子序列），`="x"`精准（区分大小写、连续、ASCII 词边界），`&&`且/`||`或/`()`分组（`&&`优先于`||`、相邻词默认`&&`），`\% \& \| \( \)`转义。`search.py` 重写为 词法`_lex`→递归下降`_Parser`→AST`_eval`。完全替换旧的「空格=且/竖线=或/引号=精准」。
- **暴力测试**（230 万次随机 fuzz + 定向边界）挖出并修复 3 处递归撑栈 + 1 处越界：深层嵌套括号、超长游离运算符链、超长操作数链（AST 改扁平 n 元节点、`_eval` 只迭代）、尾随`&&`越界。括号嵌套设上限 100。新增 `TestRobustnessNoCrash`+`TestLikeOracle`（差分测试）。
- **GUI 测试隔离**：一进程内反复 `App()` 新建/销毁 Tcl 解释器间歇 `Can't find a usable init.tcl`（~50% flaky）。改为整会话共享单一 App（`tests/gui_base.py::GuiTestCase`，setUp 复位状态、atexit 销毁），创建从 ~12 次降到 1 次，循环 25 次 0 失败，且提速约一倍。
- **全项目优化**（派 3 个 Explore 子代理扫描后择高价值低风险落地）：
  - search 每次按键对每个对象都重新 `_lex`+解析同一查询 → 新增 `compile_query()` 编译一次、`CompiledQuery.score()` 复用 AST；GUI 三处调用点改为编译一次。5000 对象/键实测 **58ms→12ms（4.8x）**。CJK 全角标点归一化由 5 次 replace 改 1 次 `str.translate`。
  - `explode.py` LZ77 回溯拷贝：无重叠时整段切片批量拷贝、重叠(RLE)保留逐字节（抽出 `_copy_match` 并对拍朴素实现测试）。
  - 跳过：GUI 去抖（改 UX 且 compile 已解决根因）、配方字体测量缓存（增益小）。
- **单实例**：`single_instance.py`，再次启动先终止上个实例再接管（临时目录锁文件记 pid+OS 映像，对 pid 复用校验防误杀；`os.kill`+`ctypes` 查询/终止，全程 best-effort 不阻塞启动）。`main.py` GUI 分支调用。`_decide` 纯逻辑单测 + 真实子进程接管冒烟验证通过。
- 全套 **136 通过, 1 skipped**；onedir 重新打包。

### 会话 9：superpowers 全项目审计 + 修复 P0~P4（~30 项）+ GUI 横向滚动
用 superpowers 派 5 个并行 agent 按模块域审计全项目，交叉核对去重后分级，**逐项 TDD（先写复现测试→看它失败→再修→跑全套）**修复。全程未改动可正常提取的真实战役回归基线（`206774.w3n` 821/313/700/61/16/79/54 始终不变）。

- **P0 安全**
  - **BLP 解压炸弹**（`blp.py`）：`width*height` 加 `_MAX_DIM=4096` 硬上限。修前一个 100 多字节的恶意 BLP 能让 `bytearray(n*4)` 真分配 ~17GB（本机实测 17s 才返回 65535² 图）；并对短数据加 `struct.unpack_from` 前的长度校验，越界返回 None。测试 `test_blp.py::TestBlpMaliciousInput`。
  - **MPQ 越界**（`mpq.py`/`explode.py`）：新增 `_parse_sector_offsets` 校验扇区偏移单调+在数据内（修前逆序/越界偏移切片成空段→静默产出错误数据）；`_read_block` 校验 block 起点在文件内；`_validate_header` 加 `sector_size_shift<=20`；explode 输入耗尽的 `IndexError` 统一转清晰 `ValueError`；IMPLODE 路径补 `max_output` 封顶。测试 `test_mpq_robust.py`、`test_explode.py::TestExplodeTruncated`。
- **P1 正确性**
  - **搜索深嵌套丢查询**（`search.py`）：深嵌套括号超旧 `_MAX_DEPTH=100` 时静默吞 `(` 不配对 `)`，导致组后的 `&& 条件` 被整段丢弃（过滤失效）。把递归下降 `_Parser` 整体重写为**迭代调度场算法 `_parse`**（显式操作数/运算符栈 + 同类节点扁平化），任意深嵌套不爆栈、不丢内容，`_eval` 长链不深递归；删 `_like_score` 已证不可达的死分支。测试加深嵌套首/尾条件保留 2 例，全 43 例过。
  - **wts 行首 `}` 截断**（`wts.py`）：正文里 `} else {` 这类 JASS 片段会被当闭合括号提前截断 → `_CLOSE` 改为要求**独占一行的 `}`**（`^\}[ \t]*$`）。
  - **w3obj 逐对象容错**（`w3obj.py`）：抽 `_parse_one_object`，单对象失败（截断/错位/未知类型）只停该文件并保留已成功对象（修前整文件丢弃，尾部一坏整类对象消失）；`cstr` 缺终止符回退 EOF；count 超剩余字节即判损坏（防注水大循环）。
  - **slk F 记录**（`slk.py`）：F 定位记录原来被读了又丢，依赖 F 定位的合法 SLK 会错位 → F 也更新光标、K 只对 C 生效。新增 `test_slk.py`。
  - **GUI `_refresh_cmds`** 补 else，无指令时更新提示（不再残留上张图统计）。
- **P2 资源/内存泄漏**
  - `MPQArchive` 加 `close()`/上下文管理器（关句柄/mmap、删大图独占临时副本）；`api.py` 的 `load_map`/`export_all_files`/`scan_commands`/`scan_recipes` 全部 try-finally/with 收口。
  - **战役临时子图文件**：修前用固定名写 `%TEMP%` 且**从不删除**（清掉了 38 个历史残留）→ 改 `tempfile.mkstemp` 唯一名、读入内存后 finally 删除；防同名碰撞。
  - **战役 `.w3n` 不再进进程级游戏 MPQ 缓存**（`icons.py`）：`extra_paths` 改独立 `MPQArchive` 随 `IconResolver` 生命周期，新增 `IconResolver.close()`（修前每开一个战役就永久缓存一个档→内存泄漏）。
- **P3 性能（GUI）**
  - 三个搜索框逐键触发改**去抖 `_schedule`**（大图不再每键重建卡死）。
  - 导出脚本/ID 移**后台线程 + 异常处理**（修前主线程写盘且无 try）。
  - 切图/退出时 `close()` 旧 `IconResolver`；战役加载失败给弹窗+状态复位。
- **P4 清理**
  - `textobj` 导入 `except Exception`→`except ImportError`（语法错不再被静默吞）；`icons._load` 不再吞 `MemoryError`；删死代码 `_view_md`/`_col_select_all`/`on_export_selected`/`find_all_command_like_strings`；清掉删 AI 层后残留的 `w3xtool/aicli/` 空壳与 `tests/__pycache__/*aicli*`。
- **新需求：每个框加横向滚动**（用户反馈地图列表名字看不全）：地图列表、物品/单位/技能/科技四列、隐藏指令表都加横向滚动条 + 列宽随最长内容自适应（`_autosize_tree`，stretch=False 才有可滚区间）。合成配方表本就有。实测物品列 80→289px。测试 `test_gui_scroll.py`。
- **暂缓**（见记忆 `w3xray-audit-deferred`）：① huffman 0x101 疑似重复加权——需真实 Huffman 样本往返验证，盲改有风险；② single_instance 改完整路径比较 + kill 前 TOCTOU 复核（低概率本地攻击，不在本次范围）。
- 测试 **136→165 通过, 1 skipped**（+29 例）；onedir 重新打包。

### 会话 10：清掉会话 9 暂缓的两项（huffman 验证 + single_instance 加固）
- **Huffman 新符号加权——证伪审计怀疑，无 bug**：会话 9 审计怀疑 `huffman.py` 新符号(0x101)路径重复加权(sparse)。用 systematic-debugging 实测裁决：从 `War3x.mpq` 捕获 **2000 条真实 StormLib 编码的 Huffman 扇区**（其中 1845 条触发新符号路径、共 2958 次插入），用当前解码逻辑解到自然终止——**2000/2000 恰好在编码器写入的 0x100 结束符处停下且输入读尽**。自适应树一旦重复加权必在第一个新符号后失步、不可能在上千条真实流上对齐。结论：移植与 StormLib 完全一致（StormLib 的 InsertNewBranchAndRebalance 内部也对新符号 IncWeights 一次、调用方再 IncWeights 一次，本就是"两次"，并非 bug）。**不改代码**，改为新增锁定测试 `test_huffman.py::TestHuffmanRealStormLibStreams`（有游戏 MPQ 时实跑真实流的位级同步校验）。
- **single_instance 加固**（防误杀）：
  - `_decide` 由 **basename 比较改完整路径比较**（`_same_image`：normcase+normpath，Windows 大小写不敏感）——不同目录的同名 exe（便携版 vs 安装版、或攻击者放的同名进程）不再被当成"上一个实例"。
  - `_terminate` 由 `os.kill(pid)` 改 **句柄式**：`OpenProcess(TERMINATE|QUERY)` 拿句柄→用同一句柄复核映像==期望→`TerminateProcess`。句柄锁定进程对象，杜绝 `_decide` 与终止之间 pid 被复用导致误杀的 TOCTOU 窗口。
  - 测试：`test_single_instance.py` +4 例（同名不同目录不杀、路径大小写不敏感、真实子进程映像匹配则杀/不符则不杀）；并端到端实测两进程接管（A 起→B 起杀 A→B 存活）通过。
- 测试 **165→170 通过, 1 skipped**（+5 例）；single_instance 改了，onedir 重新打包。
