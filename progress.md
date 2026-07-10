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
- export_all_files 当时追加 `protected_blocks/manifest.json`，记录保护块类型/大小和静态恢复失败说明；该保护图子系统已在后续精简中删除，当前完整性报告只建议由作者提供未保护文件、明文/listfile/key。
- main.py 追加 `analyze <地图路径>` 命令，输出保护状态、检测特征、对象/脚本统计和下一步提取策略。
- load_map/scan_commands/scan_recipes/analyze 支持外部解密脚本参数；GUI 增加「导入解密脚本」，可用合法 war3map.j/lua/dump 补提对象引用、隐藏指令、合成配方。
- 追加 KKWE 静态恢复：解析 KKWE 头和 zlib 分块；如果恢复出 JASS，自动作为 `.recovered.j` 扫描对象引用/指令/配方；如果恢复后仍是二进制，则导出 `.recovered.bin` 并在 manifest 记录摘要、JASS 标记和对象引用计数。
- 千风物语实测：KKWE 6 个 zlib 分块恢复出 393210 字节，但 `recovered_text_kind=binary`、`globals/function=0`、物品/单位引用=0；MPQ 声明 archive 后还有 412752110 字节高熵追加数据。因此静态工具已走完可安全路径；当前只建议由作者提供未保护地图、明文/listfile/key，不提供运行时解密路线。

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

### 会话 40：知识包脚本调用清单
- 新增 `w3xtool/script_call_catalog.py`，按函数/native 名汇总脚本真实调用，输出次数、来源、行号、机制、对象码、字符串参数和示例。
- 资料包新增 `脚本调用清单.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 扫描复用 `script_code_text()`、`extract_call_args()`、`save_api_catalog` 和 `_codes_in()`；注释或字符串里的伪调用不会升级成真实调用。

### 会话 41：知识包脚本函数索引
- 新增 `w3xtool/script_function_index.py`，按 JASS/Lua 函数范围汇总被调用次数、内部主调用数、机制、对象码和调用函数。
- 资料包新增 `脚本函数索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 函数索引复用调用清单的去噪与 API/对象码分类，只统计每行主调用，避免把 `StringHash()`、`Player()` 等参数辅助调用当成函数体主流程。

### 会话 42：知识包脚本字符串索引
- 新增 `w3xtool/script_string_index.py`，逐行导出真实脚本字符串字面量，包含来源、行号、函数、调用、用途、原文和 TRIGSTR 解析文本。
- 资料包新增 `脚本字符串索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 字符串用途覆盖 UI 文本、资源路径、聊天指令、同步前缀、存档/键、显示文本和普通字符串；跳过注释里的伪字符串和 JASS 单引号 4cc。
- **暂缓**（见记忆 `w3xray-audit-deferred`）：① huffman 0x101 疑似重复加权——需真实 Huffman 样本往返验证，盲改有风险；② single_instance 改完整路径比较 + kill 前 TOCTOU 复核（低概率本地攻击，不在本次范围）。
- 测试 **136→165 通过, 1 skipped**（+29 例）；onedir 重新打包。

### 会话 43：知识包脚本全局变量索引
- 新增 `w3xtool/script_global_index.py`，解析 JASS `globals/endglobals` 块，导出来源、行号、名称、类型、数组/常量标记、初值、字符串值、对象码和用途。
- 资料包新增 `脚本全局变量索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖对象码、资源路径、存档/键、布尔开关、数组状态和普通全局变量；注释与函数内 local 不进入索引。
- 验证：脚本/知识包聚焦测试 **13 passed**；全套 `uv run python -m pytest -q` 为 **489 passed, 15 skipped**。

### 会话 44：知识包脚本赋值索引
- 新增 `w3xtool/script_assignment_index.py`，解析 JASS `set` 和简单 Lua 赋值，导出来源、行号、函数、变量、数组索引、右值、字符串值、对象码和用途。
- 资料包新增 `脚本赋值索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖对象码、资源路径、存档/键、数组状态、布尔开关和普通变量赋值；注释、显示字符串里的伪赋值和 globals 初始值不进入赋值索引。
- 验证：脚本/知识包聚焦测试 **16 passed**；全套 `uv run python -m pytest -q` 为 **492 passed, 15 skipped**。

### 会话 45：知识包脚本变量使用索引
- 新增 `w3xtool/script_variable_usage_index.py`，解析 `udg_`、`gg_*`、`bj_` 全局变量引用，导出来源、行号、函数、变量、读/写、类别、当前行调用和对象码。
- 资料包新增 `脚本变量使用索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 变量类别覆盖用户全局、触发器、预放置单位/物品/装饰物、区域、镜头、声音和 BJ 变量；注释和显示字符串里的伪变量不进入索引。
- 验证：脚本/知识包聚焦测试 **19 passed**；全套 `uv run python -m pytest -q` 为 **495 passed, 15 skipped**。

### 会话 46：知识包脚本对象码出现索引
- 新增 `w3xtool/script_object_code_occurrence_index.py`，逐次导出脚本 rawcode 出现位置，包含来源、行号、函数、对象码、十进制值、分类、名称、对象来源、上下文、机制和摘要。
- 资料包新增 `脚本对象码出现索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 上下文覆盖对象创建/技能/物品 API、Hashtable/GameCache 存档调用、`set`/Lua 赋值、globals 声明和普通字面量；注释和普通显示字符串里的伪对象码不进入索引。
- 验证：脚本/知识包/目录聚焦测试 **5 passed**，相关回归 **13 passed**；全套 `uv run python -m pytest -q` 为 **498 passed, 15 skipped**。

### 会话 47：知识包脚本触发注册索引
- 新增 `w3xtool/script_trigger_registration_index.py`，导出脚本事件、动作、条件和计时器注册入口，包含来源、行号、函数、注册类型、句柄、API、目标和字符串参数。
- 资料包新增 `脚本触发注册索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 覆盖 `TriggerRegister*`、`TriggerAddAction/Condition`、`TimerStart`，可直接追聊天事件、玩家/单位事件、动作函数、条件函数和定时器回调；注释和显示字符串里的伪注册不进入索引。
- 验证：脚本/知识包/目录聚焦测试 **5 passed**，相关回归 **14 passed**；全套 `uv run python -m pytest -q` 为 **501 passed, 15 skipped**。

### 会话 48：知识包脚本条件分支索引
- 新增 `w3xtool/script_condition_branch_index.py`，导出 JASS `if/elseif` 条件，包含来源、行号、函数、条件表达式、调用、变量、字符串、对象码、用途和摘要。
- 资料包新增 `脚本条件分支索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖存档条件、对象 ID 条件、资源条件、状态变量条件、调用条件和普通条件；注释和显示字符串里的伪条件不进入索引。
- 验证：条件分支/知识包/目录聚焦测试 **5 passed**，相关回归 **13 passed**；全套 `uv run python -m pytest -q` 为 **504 passed, 15 skipped**。

### 会话 49：知识包脚本循环索引
- 新增 `w3xtool/script_loop_index.py`，导出 JASS `loop`/`exitwhen` 和 Lua `for`/`while`/`repeat`/`until`，包含来源、行号、函数、循环类型、表达式、调用、变量、字符串、对象码、用途和摘要。
- 资料包新增 `脚本循环索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖普通循环、存档循环条件、对象 ID 循环条件、资源循环条件、状态变量循环条件和调用循环条件；注释和显示字符串里的伪循环不进入索引。
- 验证：循环索引/知识包/目录聚焦测试 **5 passed**，相关脚本索引回归 **15 passed**；全套 `uv run python -m pytest -q` 为 **507 passed, 15 skipped**。

### 会话 50：知识包脚本返回值索引
- 新增 `w3xtool/script_return_index.py`，导出 JASS/Lua `return` 表达式，包含来源、行号、函数、返回表达式、调用、变量、字符串、对象码、用途和摘要。
- 资料包新增 `脚本返回值索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖空返回、存档返回值、对象 ID 返回值、资源返回值、状态变量返回值、调用返回值和普通返回值；注释和显示字符串里的伪 return 不进入索引。
- 验证：返回值索引/知识包/目录聚焦测试 **5 passed**，相关脚本索引回归 **17 passed**；全套 `uv run python -m pytest -q` 为 **510 passed, 15 skipped**。

### 会话 51：知识包脚本局部变量索引
- 新增 `w3xtool/script_local_index.py`，导出 JASS/Lua 函数内 `local` 声明，包含来源、行号、函数、名称、类型、初值、字符串、对象码、用途和摘要。
- 资料包新增 `脚本局部变量索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖对象码、资源路径、存档/键、开关和普通局部变量；注释和显示字符串里的伪 local 不进入索引。
- 验证：局部变量索引/知识包/目录聚焦测试 **5 passed**，相关脚本索引回归 **25 passed**；全套 `uv run python -m pytest -q` 为 **513 passed, 15 skipped**。

### 会话 52：知识包脚本调用参数索引
- 新增 `w3xtool/script_call_argument_index.py`，逐次导出脚本调用的每个参数，包含来源、行号、函数、调用、参数序号、参数文本、字符串、对象码、机制、用途和摘要。
- 资料包新增 `脚本调用参数索引.tsv`，并加入 `资料包目录.tsv` 与 `需求覆盖.tsv`。
- 用途覆盖对象码、资源路径、存档/键、字符串和普通参数；注释和显示字符串里的伪调用不会被当成真实调用。
- 验证：调用参数索引/知识包/目录聚焦测试 **5 passed**，相关脚本索引回归 **30 passed**；全套 `uv run python -m pytest -q` 为 **516 passed, 15 skipped**。

### 会话 10：清掉会话 9 暂缓的两项（huffman 验证 + single_instance 加固）
- **Huffman 新符号加权——证伪审计怀疑，无 bug**：会话 9 审计怀疑 `huffman.py` 新符号(0x101)路径重复加权(sparse)。用 systematic-debugging 实测裁决：从 `War3x.mpq` 捕获 **2000 条真实 StormLib 编码的 Huffman 扇区**（其中 1845 条触发新符号路径、共 2958 次插入），用当前解码逻辑解到自然终止——**2000/2000 恰好在编码器写入的 0x100 结束符处停下且输入读尽**。自适应树一旦重复加权必在第一个新符号后失步、不可能在上千条真实流上对齐。结论：移植与 StormLib 完全一致（StormLib 的 InsertNewBranchAndRebalance 内部也对新符号 IncWeights 一次、调用方再 IncWeights 一次，本就是"两次"，并非 bug）。**不改代码**，改为新增锁定测试 `test_huffman.py::TestHuffmanRealStormLibStreams`（有游戏 MPQ 时实跑真实流的位级同步校验）。
- **single_instance 加固**（防误杀）：
  - `_decide` 由 **basename 比较改完整路径比较**（`_same_image`：normcase+normpath，Windows 大小写不敏感）——不同目录的同名 exe（便携版 vs 安装版、或攻击者放的同名进程）不再被当成"上一个实例"。
  - `_terminate` 由 `os.kill(pid)` 改 **句柄式**：`OpenProcess(TERMINATE|QUERY)` 拿句柄→用同一句柄复核映像==期望→`TerminateProcess`。句柄锁定进程对象，杜绝 `_decide` 与终止之间 pid 被复用导致误杀的 TOCTOU 窗口。
  - 测试：`test_single_instance.py` +4 例（同名不同目录不杀、路径大小写不敏感、真实子进程映像匹配则杀/不符则不杀）；并端到端实测两进程接管（A 起→B 起杀 A→B 存活）通过。
- 测试 **165→170 通过, 1 skipped**（+5 例）；single_instance 改了，onedir 重新打包。

### 会话 11：搜索改回车触发（用户反馈逐键搜索卡顿）
- **现象**：用户反馈"搜索一卡一卡的很烦"。原四个搜索框逐键触发（去抖 `_schedule`，220ms 合并），大图下每次仍要重建多列 Treeview，输入中途仍会卡。
- **改动**（`gui.py`）：四个框（物体主搜 `search_var`→`_refresh_list`、地图列表 `map_search`→`_populate_left`、隐藏指令 `cmd_search`→`_refresh_cmds`、合成配方 `rec_search`→`_refresh_recipes`）一律去掉 `trace_add("write")` 逐键触发，改为 `entry.bind("<Return>")` **回车才搜**；逐键输入不再重建列表，清空后回车即恢复全部。
- 删掉不再使用的去抖 `_schedule` 方法与 `self._debounce`（CTkEntry.bind 已确认转发到内部 Entry）。占位符加"回车搜索"提示。
- README 同步：搜索小节加"回车触发"说明、列表交互项"去抖"改"回车才搜"。`gui.py` 导入自检通过；onedir 重新打包。

### 会话 12：全项目复审（superpowers 多代理并行审查）
四个审查子代理分别深审：①二进制解析(mpq/huffman/explode/blp) ②对象/文本解析(w3obj/slk/wts/fields/textobj/script_scan) ③应用层/GUI(api/gui/icons/single_instance) ④搜索+数据表(search/build_base_names/数据表)。结论：经会话 9-11 加固后无 Critical/内存安全缺陷；查得若干 Minor/Important，已修真问题：

- **【已修·重要】search.py `_eval` 仍是递归——重新引入了迭代化本要消灭的 RecursionError。** 本模块注释明言"任意深嵌套都不爆栈"，`_parse` 已是调度场迭代，但 `_eval` 还在递归；交替 `&&/||` 的括号无法被扁平化合并，AST 深度==括号层数，约 1000 层即 `RecursionError`。而 GUI 在打分前已 `tree.delete`、`cq.score()` 无 try → 一抛异常列表清空不再回填，搜索面板变空白。改 `_eval` 为纯迭代（后序遍历 + id→分值缓存），语义不变。实测 3000 层交替嵌套正常求值。新增 `test_search.py::TestDeepNestingNoStackBlow`（+2）。
- **【已修·次要】导出临时目录复用残留 + 计数虚高（api.py/gui.py）。** 不同地图经文件名清洗后可能撞同一 `safe_name`（如都叫"(unknown)"或重名），`tmp_extract_dir` 只 `makedirs(exist_ok=True)` 从不清理 → B 图导出目录里混着 A 图残留文件，且"已导出 N 个"用 `os.walk` 把残留也算进去。给 `tmp_extract_dir` 加 `clean=True`：导出前 `shutil.rmtree` 重建；导出全部文件/脚本/ID 三处均传 `clean=True`。对真实输入无副作用。
- **【已修·次要】SLK `;;` 转义未处理（slk.py）。** `line.split(";")` 不认 SLK 字段内 `;;` 字面分号转义，`K"a;;b"` 会被拆断成 `"a`、丢掉 `b"`。改为先 `;;`→哨兵 `\x00`、拆完还原。魔兽 Data.slk 多为数值/4cc 几乎不含分号，对真实输入是无操作；属规范正确性补全。新增 `test_slk.py::test_escaped_semicolon_in_value`。
- **【已修·次要】MPQ 扇区解压异常类型不统一（mpq.py）。** 损坏压缩流让 zlib/bz2 抛 `zlib.error`/`OSError` 漏出 `read_file`（其契约是只抛 `KeyError`）。虽所有调用方都 `except Exception` 兜住未成 live bug，但契约不诚实。把编解码分支包进 try，统一收敛成 `ValueError`（与 explode、不支持掩码两分支一致）；实测损坏 zlib/bz2 现抛 ValueError。
- **暂记录不改（需判断/规格/属行为变更）**：① blp.py BLP1 paletted alpha 用 `flags==8` 等值判断而非位测试——需对 BLP1 规格确认，且真实魔兽 BLP1 几乎都是 JPEG 压缩，少走该分支；② textobj.py 同段重复键取**首**而非取尾（WC3 INI 常为后者覆盖），但实际罕见、语义无权威依据，不贸然改；③ search `=""` 命中全部（空精准词语义，极端边角）；④ 切换/加载新图不清空搜索框，旧筛选静默套用到新图（此为既有行为，非会话 11 引入，属可用性建议）；⑤ 连点加载无 in-flight 令牌，竞态下后到结果可能覆盖，但有 close() 安全网不致泄漏。
- 测试 **170→173 通过, 1 skipped**（+3 例）；onedir 重新打包。

### 会话 13：借鉴 KKWE 编辑器，新增预放置 .doo 解析 + war3map.imp 导入清单
用户提供桌面 `KKWE插件`（KK 版 YDWE 编辑器本体）问"是否对提取有帮助"。审查结论：其 native MPQ 栈（StormLib/virtual_mpq/MopaqPack）即本项目已纯 Python 复刻的那套，无新东西；KK 数据级加密是 `debugger.dll`/`MapHelper.dll` 运行时内存层做的，静态无解（与 findings.md 既有结论一致）。**真正能借鉴的是它自带的 w3x2lni 开源源码**暴露的两个本项目缺口，已实装：
- **P0 war3map.imp 导入清单**（新 `imp.py` + `api._imported_names` 接入 `_export_all_impl`）：listfile 被删时补全可导出的自定义文件名（imp 相对名直查不到时补 `war3mapImported\` 前缀）。注水 count/截断优雅返回。测试 `test_imp.py`（+8）。**本批 62 张 demo 图实测额外导出 0 个**（仅 3 张有 imp，且名字档内无数据或 listfile 本就全）——功能正确，增益面向真·剥 listfile 的保护图。
- **P1 预放置 .doo 解析**（新 `doo.py`：`parse_doodads` + `parse_units`，`api._add_preplaced` 接入 `_load_map_impl`，填 `MapData.units`/`MapData.doodads`，CLI 显示数量）：填补 README 头号已知限制"不解析 .doo"。装饰物布局移植 w3x2lni `frontend_doo.lua`；单位布局（TFT v8）靠 62 张真图「解析完恰好到 EOF」反推证伪——**61/62 张逐字节对齐**（Fireball 图 189 单位 20995/20995 字节；唯一例外是 1 张 RoC v7 老 .w3m，变长尾部老格式，优雅降级保前置字段）。单条记录损坏不拖垮整图（逐条容错，同 w3obj）。测试 `test_doo.py`（+13，含真实夹具 `matrix.units.doo`）。
- 端到端真实验证：Fireball 图 `load_map` 得 189 单位 + 300 装饰物，坐标/玩家合理；全部对象/脚本/指令解析不受影响。
- 文档同步：README 结构表加 `doo.py`/`imp.py`、"放置信息"限制改为已解析；findings.md 记录 doo/units/imp 三种格式与 RoC 差异。
- **未做（可后续）**：GUI 里展示预放置单位/装饰物列表（数据已在 `MapData`，仅 CLI 显示数量）；RoC v7 单位 doo 的精确老布局（样本不足，暂优雅降级）；imp 在真·保护图上的实测（手上样本未踩到）。
- 测试 **166→187 通过, 8 skipped**（+21 例）。

### 会话 14：GUI 接入预放置 + superpowers 多代理重析 KKWE 并落地 5 项增强
**Part A — 预放置接进 GUI**：新增「预放置」标签页（单位表：类型/ID/玩家/坐标/生命/魔法/等级；装饰物表：类型/坐标/缩放/生命/掉落；共用回车搜索，类型码经对象表/原版名还原中文），接进 `_render_map`。`gui_base` 同步复位新表。测试 `test_gui_preplaced.py`（+4）。

**Part B — 多代理工作流完整重析 KKWE**：用 Workflow 起 6 个分析代理（二进制格式/MPQ-CASC/字段元数据/脚本分析/字符串编码/保护图）并行深读 KKWE 工具链，对照 w3xray 现有能力，汇总成 14 项增强清单（存 `docs/KKWE借鉴清单.md`）。本会话落地高价值低成本的 5 项（全部 TDD + 62 张真图验证）：
- **#1 字段全量标签**（`field_meta.py` 1444 标签 + 1521 类型，generator `build_field_labels.py`）：fields.py 从 ~80 手挑扩到全量；`label_for` 两层（精选优先→全量兜底→原码），新增 `field_type()`。界面几乎不再出现裸 4cc。测试 `test_fields.py`（+4）。
- **#3 war3map.wct 自定义脚本解析**（`wct.py`）：把二进制 wct 解出全局/各触发器手写 JASS/Lua 代码，`_add_wct` 并入 `md.scripts["war3map.wct(自定义代码).txt"]` 供导出。62/62 真图解析。测试 `test_wct.py`（+8）。
- **#4 war3map.w3i 地图信息解析**（`w3i.py`，版本 18/25/28/31）：名/作者/描述/推荐人数/尺寸/flag/脚本语言/玩家(类型·种族·开局·名)/队伍(同盟·共享)。`_add_w3i` 存 `MapData.w3i`，新增 GUI「地图信息」标签页 + CLI 摘要。62/62 真图解析。测试 `test_w3i.py`（+8）、`test_gui_info.py`（+2）。
- **#5 三层并集文件枚举**（`mpq.py` `STATIC_MAP_FILES` + `list_files` 重写）：(listfile)+内置固定名单+imp 导入名，删了 listfile 的保护图也能枚举固定名文件。测试 `test_mpq_enumerate.py`（+5）。
- **#9 地图名优先取 w3i**：`_add_w3i` 里若 w3i.map_name 非空非 TRIGSTR 残留则覆盖 HM3W 头名（更权威、自动还原 TRIGSTR）。
- **当时未做**（见清单）：该轮暂缓 WTG ECA、CASC 和 W3E；这些缺口后来分别由会话 53 的 TriggerData/TriggerStrings、Windows CascLib 与地形解析任务补齐。完整 JASS AST 仍保持不做，现有静态索引使用轻量词法扫描。
- 文档：README 结构表 +w3i/wct/field_meta，功能列表 +地图信息/自定义脚本/全量字段标签/三层枚举；gui docstring 改 5 标签页；findings.md 记录 w3i/wct/字段标签/三层枚举四项格式 + 指向清单。
- 测试 **191→218 通过, 8 skipped**（+27 例）。

### 会话 14（续）：落地清单里的可选增强 #11/#8/#6-lite/#14
- **#11 war3campaign.w3f 战役头**（`w3i.py` parse_w3f + W3fInfo，`api._add_w3f` 存 `MapData.w3f`，GUI 信息页置顶显示战役名/作者/难度/描述）：3×i32 + 4×z（移植 frontend_w3f.lua）。当时无 `.w3n` 样本；现已由仓库内 StormLib 战役 fixture 覆盖。测试 `test_w3i.py`（+3）。
- **#8 多值字段列表化**（`fields.CONCAT_TYPES`/`is_concat_type` + `api._expand_codes`）：abilityList/unitList/buffList 等把逗号分隔的码还原「原版名(码)」；实测「技能列表: 蝗虫(Aloc), 无敌的(Avul)」。测试 `test_fields.py`（+3）。
- **#6-lite 整数对象码识别**（`script_scan._codes_in` + `_int_to_code`）：补认十进制(10 位)/0x 十六进制整数形式的码（'hpea'=1752196449/0x68706561），阈值 0x41303030+4 字节可打印过滤普通数字；原仅认 'xxxx'/$XX/FourCC。scan_object_refs 现能抓整数写法的单位/物品码。测试 `test_codes.py`（+6），既有 script_scan 测试不回归。
- **#14 WTS 注释行 { 加固**（`wts._OPEN` 独占行锚定 + 兜底退回）：STRING 头与正文间注释行里的 { 不再被误当正文起点。**62 张真图新旧解析逐字节一致（零回归）**。测试 `test_wts.py`（+1）。**编码 mbcs 回退评估后不做**（简中无收益、非简中反致 GBK 老图乱码）。
- **未做**（清单剩余，价值低/有风险）：#6 完整 JASS tokenizer 替换（按 native 分类的兜底场景不适合）、#10 提取完整性自检、#12 BJ 隐式引用映射表、#13 装饰物 v8 4 字节变体（无实据，盲改风险）。
- 测试 **218→231 通过, 8 skipped**（+13 例）。

### 会话 15：重制版（Reforged）地图提取支持 —— .doo 皮肤字段自适应
用户装了重制版（`C:\Program Files (x86)\Warcraft III`，CASC 存储 2.0.4.23745）问能否提取。
- **当时结论**：该轮只实现 MPQ 地图提取，未接原生 CASC；当前已增加会话 53 的 Windows CascLib 后端和 path-map/散文件回退，但 Windows 真机读取尚未在本轮验证。用户下载的地图（Documents\Warcraft III\Maps）仍是 MPQ，w3xray 能提（实测 Darkborne RPG v23 70MB 保护图，对象/脚本/地图信息全出）。
- **修的真问题**：重制版 war3map.doo / war3mapUnits.doo 每条在 scale 后多 4 字节皮肤码，但 version/sub 仍 8/11 无法靠版本区分 → 经典图按经典布局解析、重制图错位（单位 0、装饰物中途断）。
  - `doo.py` 重构 parse_doodads/parse_units：抽 `_read_doodad/_read_unit(r, skin)` + `_attempt_*(data,count,skin)`，**两种布局都试取完整读完 count 的那个**；各 count 加 `_CAP=256` 上限令错位快速触发换试。经典图先命中 skin=False 无回归。
  - 实测：27 张 Season1 重制版对战图 → 27 有装饰物、25 有单位（修前全 0）；Darkborne 33944 装饰物按 skin 布局 1833000/1833000 到 EOF。这是之前因"无实据"暂缓的清单 #13，现有实据并落地。
  - 测试 `test_doo.py` +2（重制版 skin 自适应 + 带掉落）。
- 该轮未实现 CASC 本体读取；后续会话 53 已增加 Windows CascLib 后端（本轮未做 Windows 真机验证），单张 `.w3x` 的 MPQ 路径保持独立。
- 测试 **231→233 通过, 8 skipped**（+2 例）。

### 会话 16：superpowers 全项目复查 + 匿名资源完整导出增强
用户要求对整套软件再做一次 superpowers 流程检查，并确认两张保护/优化地图尽量完整导出。本轮聚焦实际漏提路径：删 `(listfile)` 后只靠固定名/imp 仍拿不到大量匿名导入资源。

- **MPQ 匿名加密 block 恢复**（`mpq.py`）：新增按扇区偏移表反推加密 key 的读取路径。无文件名的加密资源不再直接跳过；反推结果经过偏移表单调/越界校验和实际解压校验，避免误 key 产出垃圾。回归测试覆盖 AV2 真实失败样本里的“错误 key 会把第二偏移解到 comp_size 外”的情况。
- **导出完整性增强**（`api.py`）：`export_all_files` 现在按“具名文件 → 内容反推原始路径 → Unknown 匿名文件 → UnknownRaw 原始 payload”四层落盘。MDX/脚本中出现的 `*.blp/*.mdx/*.wav/...` 路径会反查 MPQ hash 并恢复到原目录，同时写 `RecoveredNames/manifest.tsv`；完全无法解码的 block 写 `UnknownRaw/FileXXXXXX.mpqraw` 和 `UnknownRaw/manifest.tsv`，不再静默丢弃。
- **.doo 正确性补洞**（`doo.py`）：装饰物掉落表改为嵌套 drop-set 解析；`war3mapUnits.doo` 增加 RoC v7 老布局支持。真实 `TheRiseOfEyes_v3_15e_ENG` v7 fixture 加入测试，避免再按 TFT v8 错位。
- **文档同步**：README 写清匿名导出、原路径恢复、raw 保底目录，以及 RoC v7/TFT v8/Reforged v8 三种单位 doo 布局。
- **真实地图验证**：
  - `TheRiseOfEyes_v3_15e_ENG.w3x`：MPQ blocks 2627，list files 22，导出文件 2628，RecoveredNames OK 1061 / fail 0，UnknownRaw 0。
  - `AV2_TCoM MMORG v17.8m_CN.w3x`：MPQ blocks 5839，list files 26，导出文件 5842，RecoveredNames OK 3675 / fail 2，UnknownRaw 2。两项 fail 对应原图内无法解码的 BLP payload，已保留 raw；此前已用公开近版本 `v17.8n` 手工补回同名 BLP 到用户临时提取目录。
- 测试/打包：`uv run pytest` 为 **238 passed, 8 skipped**；`uv run python -m PyInstaller --noconfirm "魔兽地图提取器.spec"` 成功生成 onedir 产物 `dist/魔兽地图提取器/`。（`uv run pyinstaller` 在当前中文/空格路径下触发 uv trampoline 路径规范化错误，已改用等价的 `python -m PyInstaller` 入口。）

### 会话 17：提取完整性诊断 + 知识包补齐
用户要求把 UI 文本、图标、资源、配置格式、存档/ID 分析和提取差距排查都补上；本轮补齐“为什么有些图看起来提不全”的可解释诊断。

- **提取完整性诊断**（`w3xtool/extraction_completeness.py`）：统计命名文件、有效 MPQ block、命名覆盖率、无名块、`Unknown/` 可解包估算和 `UnknownRaw/` 原始负载兜底；原始地图不可读时退回已加载 `md.all_files` 并明确提示无法计算块覆盖。
- **GUI 分析块**（`w3xtool/gui_extraction_reports.py` + `gui_reports.py`）：新增“提取完整性”块，直接显示命名文件数、源状态、覆盖率、无名块、Unknown/UnknownRaw 数量和前 3 条警告。
- **知识包导出**（`knowledge_pack.py`）：新增 `提取完整性.txt`，和 GUI 使用同一份 formatter，便于把提取覆盖问题发给别人排查。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #10 标为 done，记录实际落地点。
- **验证**：新增/更新 `tests/test_extraction_completeness.py`、`tests/test_gui_reports.py`、`tests/test_knowledge_pack.py`；集中测试 17 passed；全套 `uv run python -m pytest -q` 为 **444 passed, 15 skipped**。测试后已清理 `.pytest_cache` 和 `__pycache__`。

### 会话 18：BJ 隐式对象引用进入脚本对象扫描
继续补齐脚本侧 ID 覆盖。之前 `scan_script_features()` 已能识别 Melee/BJ 机制并产出隐式码，但 `api._add_script_refs()` 只读取 `scan_object_refs()`，导致这些隐式码不会出现在对象补全列表里。

- **脚本引用补全**（`w3xtool/script_scan.py`）：`scan_object_refs()` 末尾合并 BJ 隐式对象码；按 `base_objects` 的原版分类归入单位/物品/技能等。`MeleeStartingUnitsHuman` 现在能补出 `hpea`/`htow`/`Amic` 等，`MeleeGrantItemsToHero` 能补出 `stwp`。
- **BJ 常量分类**：`bj_ELEVATOR_CODE*` 常量按可破坏物归类，避免只出现在“全部引用根集合”里而不进入分类对象引用。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #12 标为 partial，记录已落地的 extra_func/object-ref 部分和剩余 need_mark 扩展项。
- **验证**：新增 `tests/test_jass_natives.py` 2 例；脚本扫描相关测试 **56 passed**；全套 `uv run python -m pytest -q` 为 **446 passed, 15 skipped**。

### 会话 19：脚本 need_mark 机制线索 + 脚本扫描拆分
继续补 `docs/KKWE借鉴清单.md` #12 剩余 need_mark。目标是让没有具体 4cc 的运行时默认池也能被看见，而不是错误补出不存在的固定 ID。

- **脚本机制模块**（`w3xtool/script_mechanics.py`）：从 `script_scan.py` 拆出 BJ 特征、隐式对象码和 need_mark 扫描；`script_scan.py` 纯代码行从 206 降到 175。
- **need_mark 覆盖**：识别 `ChooseRandomItem*`、`ChooseRandomCreep*`、`ChooseRandomNPBuilding`、`InitNeutralBuildings`，输出“随机物品池/随机野怪池/随机中立建筑池/中立建筑初始化”，并明确“不直接给出固定 4cc”。
- **GUI/资料包**：GUI 分析新增“脚本机制”块；资料包新增 `脚本机制线索.txt`，包含脚本特征、隐式对象码和运行时默认池。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #12 标为 done。
- **验证**：新增 `tests/test_script_mechanics.py`，更新 GUI/知识包测试；集中测试 **68 passed**；全套 `uv run python -m pytest -q` 为 **448 passed, 15 skipped**。

### 会话 20：资料包复制资源/配置本体
继续补“UI 文本、图标、资源、配置格式整理”的资料包落地。之前资料包只有资源引用、内部素材清单和资产索引，不能直接拿到已读取的素材/配置文件。

- **资源本体导出**（`w3xtool/knowledge_assets.py`）：新增安全复制层，把 `build_resource_inventory()` 中状态为 `存在/已引用`、`存在/未引用` 的图标/模型/音频/UI 文本/SLK/对象数据/地图配置复制到 `资源/素材文件/`。
- **manifest**：新增 `资源/素材文件_manifest.tsv`，记录内部路径、导出相对路径、字节数和状态；源不可读、源内缺失、读取失败、不安全路径都写入 manifest，不中断资料包。
- **安全路径**：落盘前拒绝空名、盘符和 `..` 穿越；目录源测试确认 `..\\escape.blp` 不会写出 `资源/`。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #15 done，记录资料包本体复制能力。
- **验证**：新增 `test_pack_exports_resource_file_bodies_when_source_is_readable`；资料包/资源/导出安全集中测试 **13 passed**；全套 `uv run python -m pytest -q` 为 **449 passed, 15 skipped**。

### 会话 21：脚本文本 TRIGSTR 可读化导出
继续补 `docs/KKWE借鉴清单.md` #7。之前工具能在 `UI文本引用.tsv` 中列出 `TRIGSTR_N` 对照，但导出的脚本正文仍是占位符，阅读触发器代码时要手动来回查表。

- **可读脚本导出**（`w3xtool/script_text_export.py`）：新增 `build_readable_script_exports()`，对非 WTS 脚本里的 `"TRIGSTR_N"` 字符串字面量做 WTS 表还原；缺失引用保持原样；文本内反斜杠、双引号、换行会转义，避免破坏脚本行结构。
- **资料包接入**：`knowledge_pack.py` 新增 `脚本可读文本/`，每个非 WTS 脚本输出一份已还原文本，配合 `UI文本_TRIGSTR.tsv` 和 `UI文本引用.tsv` 使用。
- **GUI 接入**：`导出脚本` 改用同一份可读化文本，因此 `war3map.wct(自定义代码).txt` 这类解出的触发器脚本也能直接看到 WTS 文案。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #7 标为 done。
- **验证**：新增 `tests/test_script_text_export.py`，更新知识包测试；脚本文本/资料包/UI 报告集中测试 **15 passed**；全套 `uv run python -m pytest -q` 为 **450 passed, 15 skipped**。

### 会话 22：脚本对象码轻量词法扫描
继续补 `docs/KKWE借鉴清单.md` #6。之前 `scan_object_refs()` 已有 native 分类表和整数 4cc 支持，但仍按行扫描；跨行 native 调用会漏，注释/显示字符串里的 `'A001'` 会进入孤立判定根集合。

- **代码视图模块**（`w3xtool/script_tokens.py`）：新增轻量词法辅助，保留偏移地抹掉 `//` 注释和普通双引号字符串内容，保留 `FourCC("xxxx")`；不引入完整 JASS AST。
- **跨行 native 调用**：`scan_object_refs()` 改为扫描平衡括号的 native 调用块，因此 `call CreateUnit(\n Player(0),\n 'hfoo', ...)` 能归入单位引用。
- **孤立判定去噪**：`scan_all_referenced_codes()` 改用代码视图，注释和用户显示字符串里的 rawcode 样文本不再让对象“假装被引用”。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #6 标为 done。
- **验证**：新增 `test_multiline_native_call_is_categorized` 与 `test_ignores_comment_and_display_string_rawcodes`；脚本相关集中测试 **37 passed**；全套 `uv run python -m pytest -q` 为 **452 passed, 15 skipped**。

### 会话 23：Warcraft 字符串 ACP 回退统一
继续补 `docs/KKWE借鉴清单.md` #14 剩余编码回退。之前 WTS 注释行 `{` 已加固，但多个解析器仍各自硬编码 `UTF-8 → GBK`，繁中/日文 Windows ACP 老图会出现 UI 文本、对象字段或导入路径乱码。

- **公共解码模块**（`w3xtool/war3_encoding.py`）：新增 `decode_warcraft_string()`，统一 `UTF-8 → 系统首选编码/mbcs → GBK/GB18030 → replace`，保留 WTG/WGC 原有 `latin-1` 可选兜底。
- **接入范围**：`wts.py`、`w3obj.py`、`imp.py`、`w3i.py`、`wct.py`、`wtg.py`、`gameconfig.py`、`gameplay.py`、`w3world.py` 都改用公共解码策略，覆盖 UI 文本、对象字符串、导入资源路径、地图信息、触发器头、测试配置和区域/镜头/声音名。
- **回归用例**：新增 CP950（繁中 ACP）测试，确认 ACP 顺序优先于 GBK，避免 `測試` 等文本被 GBK 抢先误解。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #14 标为 done。
- **验证**：编码/地图信息/触发器/配置相关集中测试 **73 passed**；全套 `uv run python -m pytest -q` 为 **455 passed, 15 skipped**。

### 会话 24：MPQ listfile 旧编码路径枚举补洞
继续补“能提取就尽量提取”的基础枚举链路。会话 23 已统一多数 Warcraft 文本解码，但 `MPQArchive.list_files()` 仍直接把 `(listfile)` 按 `utf-8, replace` 解码，繁中/日文 ACP 老图会把资源路径解成 `����`，导致后续图标、模型、UI 文本和配置本体复制都拿不到真实内部路径。

- **枚举职责拆分**（`w3xtool/mpq_files.py`）：把 `(listfile)`、固定地图文件名、`war3map.imp` 三层并集枚举从 oversized `mpq.py` 抽成独立模块；`mpq.py` 纯代码行从 589 降到 542，保留 `STATIC_MAP_FILES` 兼容重导出。
- **旧编码 listfile**：`(listfile)` 改用 `decode_warcraft_string()`，顺序继承 `UTF-8 → 系统 ACP/mbcs → GBK/GB18030 → replace`；新增 CP950 用例确认 `素材\測試.blp` 能被枚举出来。
- **行为不变项**：`(listfile)` 中的名字仍不强制 `has_file`，固定名单仍只收真实存在项，`war3map.imp` 仍选第一个真实存在的候选路径，大小写去重逻辑保持不变。
- **文档同步**：`docs/KKWE借鉴清单.md` 的 #5 标为 done，并记录 listfile 编码补洞。
- **验证**：新增/更新 `tests/test_mpq_enumerate.py`；焦点测试 `tests/test_mpq_enumerate.py tests/test_imp.py tests/test_export_safety.py tests/test_extraction_completeness.py` 为 **30 passed**。

### 会话 25：战役导入表参与枚举、导出和摘要
继续补战役 `.w3n` 顶层资源提取。此前完整性诊断已经能检测 `war3campaign.imp`，固定名单也会把它列出来，但实际导入路径补全只解析 `war3map.imp`，导致战役顶层导入 UI/图标/音效资源可能漏提取，GUI/资料包的导入摘要也看不到。

- **共享导入表入口**（`w3xtool/mpq_files.py`）：新增 `IMPORT_TABLE_FILES = ("war3map.imp", "war3campaign.imp")`，提供 `import_tables_from_archive()`、`import_path_candidate_groups()`、`import_candidate_names()`；地图和战役导入表走同一套候选路径逻辑。
- **枚举/导出补全**：`MPQArchive.list_files()` 现在会从 `war3campaign.imp` 补出真实存在的导入路径；`api._imported_names()` 改为委托共享入口，顶层导出也会尝试这些战役导入资源。
- **导入摘要**：`map_extras.add_import_summary()` 合并地图/战役导入表条目，`MapData.import_summary` 可显示战役顶层导入资源的 resolved/missing 状态。
- **文档同步**：`docs/KKWE借鉴清单.md` 更新 #1/#2/#3/#4/#5/#8/#9/#11/#13 的当前完成状态；源码注释、完整性说明和配置格式索引改为地图/战役导入表。
- **验证**：新增/更新 `tests/test_mpq_enumerate.py`、`tests/test_imp.py`，覆盖战役导入枚举、导出候选名和导入摘要。

### 会话 26：资源类型覆盖 + 跨行存档/ID 调用扫描
继续补“都加上”里实际会影响提取完整度的静态差距：地图脚本常把长调用换行写，UI/载入图/字体/SLK 资源也不止 BLP/MDX/MP3。

- **跨行存档/ID 线索**（`w3xtool/save_analysis.py`）：扫描粒度从逐行改成整段脚本调用；`StoreInteger(...)`、`SaveInteger(...)`、`PreloadGenEnd(...)`、`UnitAddAbility(...)`、`CreateUnit(...)` 等跨行写法仍能保留行号、存档区段/键和对象 4cc。
- **资源引用扩展**（`w3xtool/resources.py`）：资源引用识别新增 PNG/JPG/BMP、OTF、FDF/TOC/TXT/INI、SLK；对象字段和脚本字符串里的 UI 布局、载入图、字体、表格、文本配置都进入资源图。
- **资源清单同步**（`w3xtool/resource_inventory.py`）：`.toc` 按 UI/文本归类；当内部文件清单和脚本引用同时出现时状态为 `存在/已引用`，资料包复制资源本体时也能按存在资源处理。
- **验证**：新增 `tests/test_save_analysis.py`、`tests/test_resources.py`、`tests/test_resource_inventory.py` 用例；聚焦测试 `tests/test_resource_inventory.py tests/test_resources.py tests/test_save_analysis.py` 为 **9 passed**。

### 会话 27：存档/ID 扫描去掉注释和字符串误报
会话 26 为了补跨行调用把 `save_analysis` 改成整段脚本扫描，但整段扫描会把注释或玩家提示文本里的 `StoreInteger(`、`UnitAddAbility(` 也当成真实逻辑。

- **真实代码视图**（`w3xtool/save_analysis.py`）：调用定位改为在 `script_code_text()` 生成的代码视图上扫描；该视图保留偏移，参数仍从原始脚本文本中读取，所以跨行行号、存档文件、区段/键和对象 4cc 不丢。
- **Lua 注释支持**（`w3xtool/script_tokens.py`）：代码视图新增 `--` 行注释抹除，避免 Lua 地图脚本注释里的伪调用污染存档/ID 线索。
- **验证**：新增 `test_ignores_save_and_object_calls_inside_comments_and_strings`；脚本相关集中测试 `tests/test_save_analysis.py tests/test_script_scan.py tests/test_jass_natives.py tests/test_script_mechanics.py tests/test_gui_reports.py` 为 **40 passed**。

### 会话 28：DzAPI / KKAPI 平台存档静态线索
补“分析它怎么读写本地存档/地图 ID”范围内的常见 RPG 平台保存调用。这里只做静态报告，不执行平台 API、不模拟运行时、不提供绕过平台能力。

- **PlatformSave 机制**（`w3xtool/save_analysis.py`）：识别 `DzAPI_Map_SaveServerValue`、`DzAPI_Map_GetServerValue`、`DzAPI_Map_StoreInteger`、`DzAPI_Map_GetStoredInteger`、`DzAPI_Map_SavePublicArchive`、`DzAPI_Map_GetPublicArchive`、`KKAPI_SaveServerValue`、`KKAPI_GetServerValue`。
- **键名抽取**（`w3xtool/save_call_context.py`）：服务器值/公共档案类函数提取键名；Store/GetStored 类函数提取区段和键名。输出仍进入 `存档读写线索.tsv` 和 GUI“存档/ID线索”块。
- **文档同步**：`docs/KKWE借鉴清单.md` 把 DzAPI/KKAPI 明确为只保留弱静态线索，不实现完整 native 声明或运行时兼容层。
- **验证**：新增 `test_detects_platform_save_api_keys_without_executing_them`；存档/GUI/资料包集中测试 **16 passed**。

### 会话 29：资料包审计总览 + 扩展配置资源覆盖
继续收口“都加上”的静态资料整理面，目标是导出后能一眼确认 UI 文本、资源、配置格式、存档/ID、地图/对象 ID、提取完整性是否都有产物。

- **资料包审计**（`w3xtool/knowledge_audit.py`）：新增 `资料包审计.txt`，汇总 UI 文本字符串/引用/未解析数、资源资产数、配置格式数、存档/ID 线索数、对象/分类数和提取完整性状态。
- **地图/对象 ID 索引增强**（`w3xtool/investigation_exports.py`）：`地图与对象ID索引.tsv` 保留原有地图/对象行，并增加内部文件数、脚本文件数、对象总数、各分类数量摘要。
- **扩展文本配置资源**（`w3xtool/resources.py`、`w3xtool/resource_inventory.py`）：资源图和资产索引新增 `.json`、`.plist`、`.skin`、`.ai` 覆盖，分别归类为配置或 AI 脚本；配置格式索引同步识别这些文件。
- **验证**：新增/更新 `tests/test_resources.py`、`tests/test_resource_inventory.py`、`tests/test_knowledge_pack.py`；焦点测试 `uv run python -m pytest tests/test_resources.py tests/test_resource_inventory.py tests/test_knowledge_pack.py -q` 为 **11 passed**。

### 会话 30：地图文件身份指纹进入 ID 索引
继续补“分析地图 ID”的静态面。对象 4cc 和脚本存档键已经可导出，但原始地图文件本身还缺稳定指纹，无法和平台/存档侧常见的地图哈希线索对照。

- **地图身份模块**（`w3xtool/map_identity.py`）：对真实可读的地图文件流式计算文件字节数、CRC32、SHA1；目录源、缺失源或不可读源不猜测。
- **ID 索引接入**（`w3xtool/investigation_exports.py`）：`地图与对象ID索引.tsv` 增加 `文件字节`、`CRC32`、`SHA1` 地图行，和对象 4cc/十进制 ID 放在同一个表里。
- **资料包审计接入**（`w3xtool/knowledge_audit.py`）：`资料包审计.txt` 增加地图身份摘要；源不可读时明确显示“源文件不可读”。
- **验证**：新增 `test_pack_exports_readable_map_file_identity_hashes`；焦点测试 `uv run python -m pytest tests/test_knowledge_pack.py -q` 为 **3 passed**。

### 会话 31：Hashtable handle native 覆盖面补齐
继续补“分析它怎么读写本地存档”的静态覆盖。之前只识别少数 hashtable native，`SavePlayerHandle`、`SaveTimerHandle`、`LoadTriggerHandle`、`HaveSavedHandle`、`RemoveSavedHandle` 这类标准句柄存取会漏。

- **API 目录拆分**（`w3xtool/save_api_catalog.py`）：把存档 API 目录和对象 API 分类从 `save_analysis.py` 抽出，`save_analysis.py` 纯代码行从 212 降到 147。
- **通配 hashtable native**：按规则识别 `Save*Handle`、`Load*Handle`、`HaveSaved*`、`RemoveSaved*`，并保留原始 API 名到 TSV/摘要，方便回看脚本定位。
- **父键/子键提取复用**（`w3xtool/save_call_context.py`）：用同一 API 目录判断 hashtable key 参数，避免扫描与参数提取两边维护不同名单。
- **验证**：新增 `test_detects_wide_hashtable_handle_native_family`；存档/GUI/资料包集中测试 `uv run python -m pytest tests/test_save_analysis.py tests/test_gui_reports.py tests/test_knowledge_pack.py -q` 为 **18 passed**。

### 会话 32：对象 ID 索引增加使用来源和未知脚本码
继续补“地图 ID、物品/技能/单位 ID 怎么读写/引用”的资料包输出。此前 `地图与对象ID索引.tsv` 只有地图摘要和对象表行，无法区分对象是否实际被脚本、存档/ID 报告、对象字段或预放置数据使用，也不会列出脚本里出现但对象表没解析出的未知 4cc。

- **ID 使用来源**（`w3xtool/investigation_exports.py`）：对象行新增 `使用情况` 和 `详情`，合并脚本引用、`存档/ID线索`、对象字段反向引用和预放置来源；未命中的对象仍明确保留为 `对象表`。
- **未知脚本 ID**：脚本中出现但不在对象表的 4cc 会输出 `脚本引用/未知` 行，带十进制 ID、来源脚本和“未在对象表中解析”说明。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #19 done。
- **验证**：新增 `tests/test_investigation_exports.py`；聚焦测试 `uv run python -m pytest tests/test_investigation_exports.py tests/test_knowledge_pack.py tests/test_save_analysis.py tests/test_gui_reports.py -q` 为 **19 passed**。

### 会话 33：对象 ID 使用来源精确到脚本行号
继续增强 `地图与对象ID索引.tsv` 的可追溯性。会话 32 已能说明某个 ID 来自哪个脚本文件和分类，但还不能直接定位到具体行。

- **扫描逻辑拆分**（`w3xtool/object_id_usage.py`）：新增对象 ID 使用来源 collector，按去噪后的脚本代码视图逐行提取 4cc，并结合 `scan_object_refs()` 的分类结果生成 `来源:行号:分类` 详情。
- **导出层瘦身**（`w3xtool/investigation_exports.py`）：移除脚本使用来源扫描逻辑，只保留格式化；`地图与对象ID索引.tsv` 详情列现在能显示 `war3map.j:1:单位`、`save.j:1:技能` 这类定位信息。
- **未知 ID 定位**：脚本中出现但对象表没有解析出的未知 4cc 也带行号，方便回到脚本核对来源。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #20 done。
- **验证**：更新 `tests/test_investigation_exports.py` 行号期望；聚焦测试 `uv run python -m pytest tests/test_investigation_exports.py tests/test_knowledge_pack.py tests/test_save_analysis.py tests/test_gui_reports.py -q` 为 **19 passed**。

### 会话 34：WTG 触发器目录和变量清单进入知识包
继续补安全静态提取面。该轮先把不依赖游戏数据的 WTG 分类、触发器头和变量清单导出成独立资料包表格；后续会话 53 已接入 TriggerData/TriggerStrings 驱动的完整 ECA 展开。

- **触发器导出模块**（`w3xtool/trigger_exports.py`）：新增 `format_trigger_tree_tsv()` 和 `format_trigger_variables_tsv()`，输出分类 ID/父 ID、触发器名称、分类、启用状态、自定义脚本、初始关闭、初始化运行、变量类型/数组/初始值等。
- **知识包接入**（`w3xtool/knowledge_pack.py`）：新增 `触发器树.tsv` 与 `触发变量.tsv`，并在 ECA 未展开时明确写入“缺 TriggerData.txt 参数表，只显示触发器头”。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #21 done；该项的 ECA 缺口后来由 #40 完成。
- **验证**：新增知识包测试覆盖触发器树/变量 TSV；聚焦测试 `uv run python -m pytest tests/test_knowledge_pack.py tests/test_wtg.py tests/test_gui_reports.py tests/test_cli_audit.py -q` 为 **36 passed**。

### 会话 35：资料包目录清单
继续改善“都加上”后的资料包可用性。资料包里已经有多份 TSV/TXT，但没有入口表说明每个文件覆盖哪个调查面。

- **目录清单模块**（`w3xtool/knowledge_manifest.py`）：新增 `format_knowledge_manifest()`，输出 `主题 / 文件 / 用途` 三列，把 UI 文本、资源/图标、配置格式、存档/ID、地图/对象 ID、触发器、脚本和提取完整性映射到具体文件。
- **知识包接入**（`w3xtool/knowledge_pack.py`）：导出根目录新增 `资料包目录.tsv`，作为资料包入口。
- **测试拆分**：新增独立 `tests/test_knowledge_pack_manifest.py`，避免继续增大已进入警戒区的 `tests/test_knowledge_pack.py`。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #22 done。
- **验证**：聚焦测试 `uv run python -m pytest tests/test_knowledge_pack_manifest.py tests/test_knowledge_pack.py tests/test_resource_inventory.py tests/test_ui_text_report.py tests/test_save_analysis.py tests/test_investigation_exports.py -q` 为 **17 passed**。

### 会话 36：世界编辑器区域/镜头/声音表进入知识包
继续补可静态整理的地图配置面。`war3map.w3r/.w3c/.w3s` 已经解析到 `MapData` 并显示摘要，但资料包没有明细表。

- **世界编辑器导出模块**（`w3xtool/world_exports.py`）：新增 `format_regions_tsv()`、`format_cameras_tsv()`、`format_sounds_tsv()`，分别输出区域范围/天气/环境声音、镜头位置/角度/视野/裁剪距离、声音路径/变量名/循环/3D/音乐/导入标志。
- **知识包接入**（`w3xtool/knowledge_pack.py`）：新增 `世界区域.tsv`、`世界镜头.tsv`、`世界声音.tsv`。
- **目录清单同步**（`w3xtool/knowledge_manifest.py`）：`资料包目录.tsv` 增加世界编辑器三项说明。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #23 done。
- **验证**：新增 `tests/test_knowledge_pack_world.py`；聚焦测试 `uv run python -m pytest tests/test_knowledge_pack_world.py tests/test_w3world.py tests/test_knowledge_pack_manifest.py tests/test_knowledge_pack.py tests/test_gui_info.py tests/test_cli_audit.py -q` 为 **41 passed**。

### 会话 37：需求覆盖矩阵进入知识包
继续把“都加上”的范围变成可验收产物。本轮不做运行时平台兼容或保护机制修改，只整理静态资料包中已经覆盖的需求面。

- **需求覆盖模块**（`w3xtool/knowledge_requirements.py`）：新增 `format_requirement_coverage()`，输出 `需求覆盖.tsv`，把 UI 文本、图标/资源、配置格式、本地存档读写、地图 ID、物品/技能/单位 ID、触发器/变量、区域/镜头/声音和提取完整性映射到对应产物。
- **知识包接入**（`w3xtool/knowledge_pack.py`）：根目录新增 `需求覆盖.tsv`。
- **目录清单同步**（`w3xtool/knowledge_manifest.py`）：`资料包目录.tsv` 增加需求覆盖条目。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #24 done。
- **验证**：先确认 `tests/test_knowledge_pack_manifest.py` 对缺失 `需求覆盖.tsv` 红灯，再实现转绿；聚焦测试当前为 **2 passed**。

### 会话 38：预放置单位/装饰物表进入知识包
继续补“地图上实际有什么”的静态资料面。本轮仍不做运行时平台兼容或保护机制修改，只导出已经解析到 `MapData` 的放置信息。

- **知识包编排拆分**：`knowledge_pack.py` 先拆出 `knowledge_io.py`、`knowledge_object_exports.py`、`knowledge_resource_exports.py`、`knowledge_script_exports.py`，保留 `format_box_id_text` 重导出给 GUI 使用，避免新增产物继续推高主编排文件行数。
- **预放置导出模块**（`w3xtool/knowledge_preplaced_exports.py`）：新增 `format_preplaced_units_tsv()` 和 `format_preplaced_doodads_tsv()`，输出 `预放置单位.tsv`、`预放置装饰物.tsv`，包含坐标、角度、玩家、生命/魔法/金矿、英雄等级、物品栏、技能、缩放和掉落。
- **目录/需求同步**：`资料包目录.tsv` 增加预放置两项，`需求覆盖.tsv` 把预放置表列入物品/技能/单位 ID 的辅助产物，并新增“分析预放置单位/装饰物”需求行。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #25 done。
- **验证**：拆分前知识包基线测试 **7 passed**；拆分后知识包/脚本/GUI 聚焦测试 **22 passed**；新增预放置红灯后实现转绿，`tests/test_knowledge_pack_preplaced.py tests/test_knowledge_pack_manifest.py` 为 **3 passed**。

### 会话 39：对象 ID 使用摘要
继续补“地图 ID、物品/技能/单位 ID 怎么读写/引用”的聚合视图。本轮只做静态来源计数，不执行脚本或平台 API。

- **对象 ID 汇总模块**（`w3xtool/object_id_summary.py`）：新增 `format_object_id_usage_summary()`，输出 `对象ID使用摘要.tsv`，按 ID 汇总脚本引用、存档/ID 线索、对象字段引用、预放置引用次数和详情。
- **预放置嵌套 ID 计数**：同一模块提供 `preplaced_code_counts()`，把单位类型、单位物品栏、单位技能、装饰物类型、装饰物掉落都计入预放置来源。
- **ID 索引同步**（`w3xtool/investigation_exports.py`）：`地图与对象ID索引.tsv` 复用新的预放置计数，物品栏/技能/掉落里的 ID 也会标为“预放置”。
- **知识包接入**（`w3xtool/knowledge_pack.py`）：根目录新增 `对象ID使用摘要.tsv`；`资料包目录.tsv` 和 `需求覆盖.tsv` 同步加入口。
- **文档同步**：`docs/KKWE借鉴清单.md` 新增 #26 done。
- **验证**：先用缺失模块/缺失产物确认红灯，再实现转绿；`tests/test_object_id_summary.py tests/test_knowledge_pack_object_id_summary.py tests/test_knowledge_pack_manifest.py tests/test_investigation_exports.py -q` 当前为 **6 passed**。

### 会话 53：完整静态提取验收、能力文档与安全收尾
一次性验收 WTG ECA、原生 CASC、外部 listfile、资源/配置/ID 资料包和静态提取边界，不再把历史计划或未验证环境写成已完成能力。

- **WTG ECA**：Classic/Reforged 触发器头始终可读；匹配 `TriggerData.txt` 时展开事件/条件/动作/调用、参数和嵌套子动作，`TriggerStrings.txt` 可用时生成编辑器式本地化语义文本。
- **游戏基础数据源**：Windows 已实现固定 CascLib 3.0 的已知逻辑路径读取和完整 Root 枚举；未知条目保留 FileDataID/CKey/EKey 合成名并按该名重开。散文件与显式 path-map 继续作为跨平台回退。macOS fake-native、固定源码构建和打包路径已验证，真实 Windows 魔兽安装测试本轮仍跳过，不声明真机读取通过。
- **真实地图验收**：`war3net-map-script-builder.w3x` 通过 CLI + 外部 listfile + TriggerData/TriggerStrings 生成 72 个资料包文件；`触发器ECA.tsv` 出现 `Kill gg_unit_hpea_0006`，需求覆盖记录 listfile“确认 1，缺失 1”、CASC“使用散文件”、运行时解密“不支持”，命名覆盖为 `16/16 (100.0%)`。
- **输出安全**：安全审查复现父目录移出后 `O_TRUNC` 会截断并删除外部同名文件，进一步复现最终发布窗口仍可能覆盖原文件；改为祖先预检、唯一临时文件、既有目标硬链接备份、阶段复核和越界原子恢复，非预期异常也按 inode 清理未发布临时文件。外部 listfile 增加 8 MiB、4096 字符/行、100000 有效条目的硬上限并逐行迭代，越界整体拒绝。
- **静态边界**：真正数据级加密只做有界诊断和 `UnknownRaw` 原始负载保留；需要作者提供未保护文件、明文/listfile/key。本项目不执行内嵌 loader，不做运行时内存 dump、调试器或平台保护绕过。
- **验证**：全量测试 **684 passed, 16 skipped, 1 subtest passed**；Task 8/安全聚焦 **15 passed**，GUI/CLI 聚焦 **34 passed**；真实 fixture CLI 退出码 0 并生成 72 个普通文件、0 个符号链接。

### 会话 54：恢复未提交闭环工作
- 从 `edf6cea`（`local` 与 `origin/local` 同步）继续；保留工作区全部既有改动，不处理 `.DS_Store` 和 `tests/.DS_Store`。
- 恢复时已知最近全套结果为 `719 passed, 4 skipped, 1 failed`；唯一失败来自测试仍从 `casclib_source` 导入已移动的 `CascNameType`，工作区已修正，但必须重新执行完整套件确认。
- 后续顺序固定为：完整回归 → CASC 清单有界写盘红绿测试 → 核心类型/Windows 资产校验 → no-excuse 检查 → 五路审查 → 提交推送 → hosted Windows workflow 证据。
- **完整回归**：`uv run python -m pytest -q -rs` 为 **720 passed, 4 skipped, 1 subtest passed**（6.53s）。跳过项精确为 Windows Warcraft III CASC、真实 `war3.mpq` 图标缓存、Windows 单实例终止 API 两项。
- **CASC 流式红灯**：新增 `test_inventory_writes_bounded_chunks_while_root_is_still_enumerating`，源在最后一条前检查同目录 stage；旧实现按预期失败于 `assert staged`，证明枚举结束前没有任何写盘。
- **CASC 流式绿灯**：新增 `write_chunks_safely()`，POSIX 复用锚定 stage/备份/发布协议，Windows 路径回退使用同目录 0600 stage 并在完整写入后 `os.replace`；清单按约 64 KiB 批次编码。流式增长、延迟发布、异常保留旧目标三项测试 **3 passed**。
- **类型检查**：流式输出相关核心文件 basedpyright 为 **0 errors, 0 warnings**；非 GUI 新核心集合为 **0 errors, 55 warnings**，并清除仓库全部 `typing.Generator` 遗留导入。两次组合 `apply_patch` 因上下文文件写错未应用，读取实际文件头后拆分补丁成功，未产生部分写入。
- **Windows workflow 本地门禁**：两个 YAML 经 Ruby YAML parser 和 `actionlint v1.7.12`（仅忽略预期自托管标签 `w3xray-war3`）通过；验收资产测试 **4 passed**。dispatch 的 `war3_dir`/evidence 路径改经环境变量传入 PowerShell，新增测试先红后绿。
- **no-excuse 真实样本**：`tests/test_campaign.py`、Huffman fixture 类、`tests/test_slk_objects.py` 合计 **19 passed, 0 skipped**；仓库内 `.w3n`、游戏 MPQ Huffman、旧 SLK 三类缺样本跳过已闭环。
- **review-work 第一轮**：QA 在源码 acceptance 上得到 4 PASS/3 预期 SKIP，聚焦测试 12 passed；目标/上下文/安全审查判定整体 FAIL。有效阻断项为真实存档与作者明文路径换包、MPQ 解压总量、self-hosted runner 权限/固定 ref，以及旧 CASC 文档冲突。首批五代理无结果被关闭；第二批代码质量 lane 仍无结果，待修复后重跑窄复审。
- **安全阻断修复**：新增单次打开/`lstat+fstat` 身份核对/`O_NOFOLLOW`/有界读取 helper；真实存档改用稳定快照，MPQ 成员按 block 声明大小在解压前拒绝并共享 8 MiB 文本预算；作者明文拒绝 `files/` 与子路径 symlink，验证后按 inode/size/hash 重验。Windows path fallback 发布前两次核对 stage inode。self-hosted workflow 固定 `local` ref、最小 `contents: read`、environment 和 `persist-credentials: false`。安全/CASC 聚焦测试 **56 passed**。
- **聚合预算补漏**：新增二进制 MPQ 成员回归，复现“解压成功但无法解码为文本时不扣 8 MiB 总预算”的绕过（修复前 5 个成员全部解压，期望仅 2 个）；预算现对每个已解压成员扣减，不再取决于文本解码结果。
- **CASC 路径编码补漏**：复审指出 `CascOpenFile` 边界强制 ASCII 会让非 ASCII 逻辑路径在进入 CascLib 前抛错；新增红绿测试并改为 UTF-8。固定 CascLib 源码同时再次证实 `CASC_OPEN_BY_NAME(0)` 会依次解析真实路径、`FILE%08X.dat`、CKey、EKey，无需按名称类型切换 flags。
- **五路复审通过**：目标、QA、代码质量、安全、上下文五路最终均为 PASS。独立 QA 的 portable acceptance 为 4 PASS/3 个预期 SKIP，并另跑 49 项聚焦测试；安全复审确认前序 TOCTOU、symlink、解压预算、stage 发布与 self-hosted workflow 阻断项均已闭环。
- **修复后完整回归**：`uv run python -m pytest -q -rs` 为 **735 passed, 4 skipped, 1 subtest passed**（7.24s）；改动 Python 文件 Ruff、`compileall`、YAML、`actionlint` 与 `git diff --check` 均通过。4 个跳过仍只涉及真实 Windows Warcraft III CASC、真实 `war3.mpq` 和两项 Windows 句柄 API，不再包含 `.w3n`、Huffman 或旧 SLK 样本缺口。
- **托管 Windows 分栏测试闭环**：Actions `29070319469` 的最后 3 个失败来自测试等待 `paned >= 900`，但 430/300 minsize 与 8 px sash 下，原固定坐标实际需 988-1068 px。`31f5156` 改为从生产分栏读取约束、临时缩窄测试源列表栏并使用两个可行坐标；应用级释放事件、命名配置与精确坐标断言均保留。
- **PowerShell 5.1 代码页闭环**：Actions `29075235405` 已通过 Windows 全测和 onedir 构建，但内嵌中文 EXE 路径在 Windows PowerShell 5.1 中被按旧代码页解码并在执行前 `ParserError`。`4c1663b` 让 hosted run block 与真机脚本以纯 ASCII 查找并校验 `dist` 下唯一 `.exe`，不改变中文产品名；两条失败优先测试由 `2 failed, 6 passed` 转为 `8 passed`。
- **最终本地门禁**：`uv run python -m pytest -q -rs` 为 **741 passed, 4 skipped, 1 subtest passed**；改动文件 Ruff、basedpyright、no-excuse、`compileall`、Ruby YAML、`actionlint v1.7.7` 与 `git diff --check` 均通过。
- **托管 Windows 最终验收**：[Actions `29075856581`](https://github.com/HenTai-Miao/w3xray/actions/runs/29075856581) 在提交 `4c1663b` 上成功，Windows 全套为 **734 passed, 11 skipped, 1 subtest passed**；固定 CascLib、onedir 构建、打包 EXE 实跑和产物上传全部通过。
- **EXE acceptance 证据**：下载并读取 artifact `8220770701` 中的 `acceptance.json`，总体 `pass`；Windows runtime、地图加载（16 文件/1049 对象）、战役切换（1 子图）、知识包导出（72 文件）、5 次稳定重载和 9 个 GUI 标签均 PASS。artifact ZIP SHA-256 为 `f8a47eeb77527d22ea57fb480fc438a1c9879d0584d48dc696877bc70b2affc1`，EXE SHA-256 为 `94a7185a28ec652c39d5aaa2c48afd51a403adea567f0b4ed59c84950069ba55`。
- **真实客户端边界**：`real_windows_casc` 是验收报告唯一 SKIP，原因是 hosted runner 没有 `W3XRAY_WAR3_DIR`；GitHub API 当前返回 self-hosted runner **0 台**。真实 Warcraft CASC workflow/脚本已实现，但只有接入带真实安装目录的 `w3xray-war3` Windows 机器后才能产生真机证据，当前不宣称通过。
