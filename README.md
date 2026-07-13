# w3xray — 魔兽地图提取器

> **X-ray your Warcraft III maps.**

从零实现的魔兽争霸 III 地图/战役提取工具；地图 MPQ 解析为纯 Python，并包含基于 CascLib 3.0 的 Windows 原生 CASC 后端。
带图形界面，可对地图里的 **单位 / 物品 / 技能 / 科技 / 可破坏物 / 装饰物 / 增益**
做模糊搜索、查看详细字段，并提取脚本、隐藏聊天指令、合成配方，导出文件。
支持战役 `.w3n`（多关卡子地图 + 战役级共享对象）。
GUI 现在按偏 Warcraft III World Editor 的工作台组织：总览、对象编辑器、地图信息、
GUI触发器、场景放置、触发指令、合成配方、孤立对象、分析报告分别承载浏览与体检功能。

> 用途：研究地图、学习地图制作。不含改存档 / 过反作弊 / 开图等作弊功能。

## 直接用（GitHub Releases）

Windows x64 同时提供：

- `w3xray-v0.1.2-windows-x64.zip`：完整解压后运行，启动更快，也更容易诊断依赖或启动问题，适合长期使用。
- `w3xray-v0.1.2-windows-x64.exe`：单文件直接运行，首次启动会解压到临时目录，因此启动较慢。此单文件直发版未做代码签名，因此可能出现 SmartScreen 提示。

两者功能相同；遇到杀软误报或启动问题时优先使用 ZIP 版。

macOS 提供两个未签名、未公证的 onedir ZIP，请按 Mac 处理器选择并完整解压：

- `w3xray-v0.1.2-macos-arm64.zip`：Apple Silicon（M1/M2/M3/M4/M5）。
- `w3xray-v0.1.2-macos-x64.zip`：Intel Mac。

Linux 提供：

- `w3xray-v0.1.2-linux-x64.tar.gz`：Linux x86-64，解压后运行 `./魔兽地图提取器/魔兽地图提取器`。

macOS/Linux 包支持地图与战役的静态提取；Windows 专用的 CascLib 游戏客户端原生后端不包含在这两类包中。macOS 首次运行可能出现 Gatekeeper 未验证开发者提示。

## 开发运行（uv）
```bash
uv run main.py                 # 启动图形界面
uv run main.py cli <地图路径>   # 命令行快速查看分类统计
uv run main.py current         # 获取游戏进程正在使用的地图并解析只读快照
uv run main.py cli <配置.wgc>   # 命令行查看 World Editor AI 测试配置
uv run main.py casc --help      # CASC Root 全量清单 / 单文件导出
uv run main.py save --help      # 真实存档文件只读证据分析
uv run main.py acceptance --help # 源码或打包 EXE 验收并生成 JSON
uv run w3xray-test             # 运行测试（Windows 下避开 pytest.exe trampoline）
```
CLI 输出会附带只读「审计 / 组件诊断 / 地形 / 地图结构 / SLK / 游戏常数 / 游戏配置 / 触发器树 / 小地图标记 / 导入资源 / 脚本诊断 / 崩溃风险 / 秘籍口令 / 命令 / 资源 / 兼容」摘要，提示缺失地图信息、war3map.w3e 地形纹理、网格、世界坐标范围、地形点高度/水位/坡道/荒芜/边界/边缘统计、预放置单位/装饰物越界、实际地表/悬崖纹理使用分布、地形中文名/贴图路径、区域/镜头/声音/路径图摘要与可读条目、路径图禁止行走/飞行/建造等 pathing flag 统计、war3map.shd 阴影图覆盖统计、内嵌 SLK 表行列摘要、war3mapMisc.txt 覆盖项、`.wgc` AI 测试/对局配置、`war3map.wtg` 触发器树结构、`war3map.mmp` 小地图标记、`war3map.imp` 标准/自定义导入路径与疑似缺失资源、脚本缺失、异步/本地状态风险调用、已知崩溃配置、官方秘籍/调试口令残留、引用覆盖偏低、孤立对象比例偏高、重复命令串、脚本数值 Order ID 解码、自定义游戏平衡常数、未引用素材、1.20E return bug 迁移风险、1.24E 兼容风险等；这些提示只用于人工排查，不会修改地图。

## 获取当前地图（只读）

Warcraft III 对局运行时，可在 GUI 顶栏点击「获取当前地图」。探测在后台线程中完成：唯一的直接证据会自动建立快照并加载；只有提示证据时会先显示来源和路径，必须由用户确认；候选不唯一、未找到或平台探针不可用时不会猜测或打开地图。

CLI 概要为 `uv run main.py current [--root PATH] [--accept-suggestion]`。`--root PATH` 可重复，用于补充有界搜索目录；还可把现有地图 CLI 的 `--listfile PATH`、`--game-data PATH`、`--author-bundle PATH`、`--pack PATH` 原样转发给后续只读解析。例如：

```bash
uv run main.py current
uv run main.py current --root "/path/to/Warcraft III/Maps" --accept-suggestion
uv run main.py current --listfile names.txt --game-data /path/to/game-data --author-bundle /path/to/bundle --pack /path/to/report
```

定位结果按证据强度处理：

| 状态 | 含义 | GUI / CLI 行为 |
|------|------|----------------|
| `FOUND` | 唯一直接证据：Warcraft 游戏进程打开的地图文件，或该进程启动参数中的明确地图路径 | 自动创建快照并加载 |
| `AMBIGUOUS` | 多个直接证据候选 | 展示说明/候选，不按修改时间猜测，也不创建快照 |
| `SUGGESTED` | 没有直接证据，只有游戏运行期间的近期地图缓存或近期 `.wgc` 引用 | GUI 仅对唯一候选弹窗确认；CLI 仅在唯一候选且显式传入 `--accept-suggestion` 时继续 |
| `NOT_FOUND` / `UNAVAILABLE` | 未发现可用候选，或当前平台无法可靠执行直接探针 | 报告原因，不创建快照 |

World Editor、Battle.net、启动器和下载客户端不算游戏进程；“最近修改”本身也绝不会成为自动打开依据。任何非唯一结果都不会因 `--accept-suggestion` 而被强行选择。

通过证据门槛后，工具只读打开现存的 regular `.w3x/.w3m/.w3n`，复制到系统临时目录下权限受控的唯一目录，并固定命名为 `current.<原扩展名>`。复制前后会核对源文件的设备号、inode、大小和纳秒 mtime，同时计算快照 SHA-256；源文件在复制期间发生变化会使快照失败并被删除。解析器只读取快照，源地图不会被修改。CLI 在解析返回后删除快照；GUI 在本次应用会话结束时统一删除，下一次启动只会有界清理本工具拥有的陈旧快照。

此功能只使用操作系统可见的进程列表、命令行、打开文件路径和磁盘元数据：**不读取游戏内存，不打开 `Game.dll`，不注入 DLL，不执行地图/平台代码，不提权，也不做数据级运行时解密**。如果自定义加密只在游戏内存中解密，本工具无法恢复明文；快照只保留磁盘上已有的字节，并交给现有静态兼容解析器。

Windows 上如果 `uv run pytest -q` 报 `uv trampoline failed to canonicalize script path`，
用 `uv run w3xray-test` 或 `uv run python -m pytest -q`；这两种方式直接走 Python 模块入口，
不经过 pytest 的 console-script 启动器。

## 重新打包 exe
Windows 包必须先从固定源码构建 x64 CascLib；脚本会验证源码 SHA256，并生成 DLL 及其哈希。默认命令构建 onedir（exe + 同目录 `_internal/` 依赖）；加 `--onefile` 构建可直接分发的单文件 exe：
```powershell
powershell -ExecutionPolicy Bypass -File tools/build_casclib.ps1
uv run w3xray-dist
uv run w3xray-dist --onefile
```
DLL 和生成的哈希是本地构建产物，不提交到 Git。Windows 打包会在 PyInstaller 启动前校验 DLL 存在、SHA256 匹配且为 x64 PE；直接运行 spec 也不能绕过这道校验。
只检查将要执行的 PyInstaller 命令，不真正打包：
```bash
uv run w3xray-dist --dry-run
```
说明：PyInstaller 不是跨平台编译器；在 macOS/Linux 上运行同一命令会生成当前平台的可执行文件，不会生成 Windows `.exe`。

真实 Windows 魔兽安装的一键验收（构建 CascLib、全套测试、打包、再由打包 EXE
执行地图/战役/GUI/CASC/导出/重复加载）运行：
```powershell
powershell -ExecutionPolicy Bypass -File tools/run_windows_acceptance.ps1 `
  -War3Dir "C:\Program Files (x86)\Warcraft III"
```
默认结果写入系统临时目录的时间戳证据目录 `w3xray-acceptance-YYYYMMDD-HHMMSS/`，两份报告的相对路径分别为：

- `windows-onedir/acceptance.json`
- `windows-onefile/acceptance.json`

仓库还包含
`.github/workflows/windows-package.yml`（hosted Windows 打包验收）和
`windows-real-war3.yml`（带 `w3xray-war3` 标签的 self-hosted 真安装验收）。

## 刷新原版数据（base_names / base_objects / westrings）
`w3xtool/base_names.py` 等三份内置数据由 `build_base_names.py` 从**游戏本体**一次性生成，运行时不读游戏。换语言/升级后想刷新：

- **经典版（≤1.29，MPQ）**：
  ```bash
  uv run build_base_names.py                 # 默认硬编码安装目录
  uv run build_base_names.py --game "D:/Warcraft III/war3"
  ```
- **重制版（1.30+，CASC）**：游戏数据改为 CASC。Windows 发行包已接入 CascLib 后端，可按已知路径读取，也可流式枚举 Root 的全部条目；无原路径的条目以 FileDataID/CKey/EKey 保留。无 CascLib 时可回退到带 `w3xray-casc-paths.tsv` 的 idx/data 非加密 BLTE 读取；所有平台也可读取 CascView/casc-extract 导出的散文件目录。本次 macOS 环境不能代替真实 Windows 魔兽安装验收，刷新内置数据仍可用散文件目录：
  1. 用 [CascView](http://www.zezula.net/en/casc/main.html)（GUI）或 `wc3tools/casc-extract`（CLI，如 `casc-extract war3.w3mod:units/*` ）把游戏 `units/` 下的 `*Strings.txt`/`*Func.txt`/`*Data.slk` 与 `ui/WorldEdit*Strings.txt` 导到一个文件夹。
  2. `uv run build_base_names.py --from-dir <该文件夹>`，按打印的「找到/未找到」清单确认覆盖。

## 静态提取边界
- **WTG 头和目录**：不需要游戏数据即可读取分类、变量、触发器头和启用状态。
- **WTG ECA 函数体**：需要与地图版本匹配的 `TriggerData.txt` 才能按函数签名安全展开；缺 schema 时保留头部并报告未展开入口，不猜参数字节。
- **ECA 本地化语义**：在 `TriggerData.txt` 基础上还需要 `TriggerStrings.txt`；缺少它时仍保留函数名和参数原值。
- **原生 CASC**：Windows 已实现固定版本 CascLib 的已知路径读取和完整 Root 枚举。Root 没保存原路径时，浏览器保留 CascLib 返回的 `FileDataID/CKey/EKey` 稳定标识，仍可读取/导出，不伪造路径。散文件目录和显式 path-map 是跨平台回退。仓库包含需 `W3XRAY_WAR3_DIR` 的 Windows 真机验收；本次 macOS 验证仍不冒充真实安装通过。
- **保护/加密地图**：只做有界开档诊断、可恢复静态块提取和 `UnknownRaw` 原始负载保留；不执行内嵌 loader，不做运行时内存 dump、调试器或平台保护绕过。作者可提供带源地图 SHA256 和逐文件 SHA256 的明文补充包，让完全不可开的容器继续分析作者给出的 `war3map.j/lua/w3*` 文件。
- **真实存档文件**：可对用户指定的文件/目录做只读清单、格式识别、SHA256、Preload/JASS/JSON/INI/MPQ 可读文本、存档键和对象 ID 交叉分析；不调用平台 API，不解密不透明平台数据，不修改源文件。
- **资源边界**：单个 MPQ 成员最多解压 256 MiB；单个战役最多加载 256 张子图且累计保留不超过 512 MiB；命名文件、匿名块和恢复文件分别受累计导出预算限制；listfile 最多采用 100000 个、每个不超过 1024 字符的名称；SLK 坐标、行列和单元格数均有上限。超限来源会跳过或进入诊断，不会继续无界分配。

## 能力状态
- **完整（有自动化证据）**：单张 `.w3x/.w3m` 和战役 `.w3n` 的静态 MPQ 提取；二进制对象、GBK Func/Strings、SLK 按 rawcode 合并；JASS/Lua/WCT、WTG/W3F、世界数据、资源和四类 ID 报告；逐组件诊断与逐文件写入结果。独立 StormLib fixture 同时覆盖四类对象、WTS、JASS+Lua、WTG/WCT 和 W3F 声明子图，战役 CLI 会自动发布每张已加载子图的独立资料包。
- **部分（输入决定上限）**：缺 `TriggerData.txt` 时 WTG 只保留头和未展开诊断；缺 `TriggerStrings.txt` 时 ECA 无编辑器本地化句子；损坏或匿名 MPQ 只发布可确认内容、诊断和 `UnknownRaw`；path-map/散文件客户端源只能枚举已知路径。
- **运行时范围外**：不执行地图 loader、平台 API 或游戏进程代码，不做内存 dump、反调试/反作弊绕过、数据级运行时解密，也不解密或修改不透明玩家存档。
- **外部验收 SKIP**：本次开发环境不是带真实 Warcraft III 安装的 Windows 主机。Windows 打包与真安装工作流已经存在，但只有 hosted/self-hosted 产生的验收 JSON 才能记为 PASS；本地 macOS 测试不替代该证据。

## 功能
- **获取当前地图**：GUI 顶栏按钮或 CLI `main.py current` 根据游戏进程与磁盘证据定位 `.w3x/.w3m/.w3n`，通过置信度门槛后只解析私有临时快照，不改源地图。
- **解包**：把地图(MPQ 压缩包)内部文件全部解出；文件名发现采用**三层并集**((listfile) + 内置固定名单 + war3map.imp 导入清单)，GUI 也可选择外部 listfile 补充被删掉的文件名；无文件名的匿名 block 会逐块尝试恢复加密 key、按内容猜扩展名导出到 `Unknown/`，若从 MDX/脚本等内容反推出真实资源路径则按原路径补导出并写 `RecoveredNames/manifest.tsv`，极端损坏或无法解码的原始 payload 会保留到 `UnknownRaw/manifest.tsv`；提取完整性报告会标出疑似数据级加密/运行时解密保护，不做运行时内存 dump 或绕过。
- **CASC 客户端浏览**：选择可读的 Windows 原生游戏数据后，「数据工具」可分页浏览整个 Root（每页 200 条）、按 mask 重扫并导出所选；CLI `casc inventory` 输出含路径类型、FileDataID、CKey、EKey、大小和本地可用状态的 TSV，`casc extract` 按任一稳定标识导出单文件。
- **作者明文补充包**：`cli <地图> --author-bundle <目录>` 或 GUI「数据工具」接入。补充包必须包含 `w3xray-author-bundle.tsv`，首行是 `W3XRAY-AUTHOR-BUNDLE<TAB>1`，第二行绑定源地图 SHA256，后续每行绑定内部路径和文件 SHA256；文件放在包内 `files/`，路径穿越、重复名、哈希不符和容量超限都会拒绝。
- **真实存档只读分析**：GUI「数据工具」可选存档文件或目录；CLI 用 `main.py save --map <地图> --save <文件或目录> --output <报告.tsv>`。输出把真实文件证据与地图脚本声明的存档键、对象 ID/名称关联，不执行任何平台代码。
- **对象信息**：解析对象编辑器数据，名称经 war3map.wts 还原为中文；字段标签全量化（1444 个字段码经 MetaData.slk + westrings 离线生成中文名，界面几乎不再出现裸 4 字符码）；多值字段（技能/单位/科技列表等）把逗号分隔的码逐项还原成「名字(码)」。对象数据三种载体都读：**二进制** `.w3u/.w3a/…`、**INI 文本档**（`*UnitFunc/Strings.txt`）、**内嵌 SLK**（`AbilityData.slk` 等，SLK 优化图的产物）；三者按对象码自动合并（如优化图里技能名来自 txt、字段与引用来自 SLK，合成一条完整记录）。SLK 字段做了可读化：等级后缀列（`Cast2`→「施法间隔(等级2)」、`BuffID1`→「buff效果(等级1)」），并按 `[AlwaysEmpty]` 隐藏 `comments/version/sort/code` 等编辑器噪声列
- **地图信息**：独立标签页展示 war3map.w3i —— 真实地图名/作者/描述/推荐人数/尺寸/脚本语言(JASS/Lua)/各玩家(类型·种族·名字)/队伍(同盟·共享)；地图名优先取 w3i（比 HM3W 头权威，自动还原 TRIGSTR）。战役 `.w3n` 另解析 war3campaign.w3f 显示战役名/作者/难度/描述；同时解析 `war3map.w3r/.w3c/.w3s`，列出世界编辑器里的区域、镜头、声音数量与名称摘要；若包内或单独打开 `.wgc`，会显示 AI 测试/对局配置里的地图路径、游戏速度、关闭战争迷雾/胜负条件、玩家/电脑/观察者槽位和自定义 AI 脚本路径；若存在 `war3map.wtg`，会显示触发器树版本、分类、变量、触发器头和开局运行/禁用/自定义脚本等状态；若存在 `war3map.mmp`，会显示小地图上的玩家出生点、金矿、中立建筑标记数量和坐标摘要；若存在 `war3map.imp`，会显示导入资源数量、标准/自定义路径、扩展名分布和疑似缺失导入文件
- **自定义脚本**：解析 war3map.wct，把作者手写的全局/各触发器自定义 JASS/Lua 代码解码成可读文本（原始 wct 是二进制），随「导出脚本」导出
- **搜索**：按名称 / ID / 字段内容搜索，采用 **SQL 风格语法**（`LIKE` / `=` / `AND` / `OR` / 括号）
  - **回车触发**：输入完按 `Enter` 才搜索（不逐键重建列表，大图也不卡）；清空后回车即恢复全部
  - `%词%` = **包含**、`词%` = **前缀**、`%词` = **后缀**、`甲%乙` = 中间通配；`%` 是通配符，**不分大小写**。裸词（不带 `%`）按 `%词%`（包含）处理。按 SQL `LIKE` 语义，**不做子序列**匹配
  - `="词"` = **精准**：必须原样连续出现，**区分大小写**；引号内空格 / `%` / `&` / `|` 都算普通字符，可搜整句
    - 精准词以 ASCII 字母/数字或 `+` 结尾时按**词边界**匹配，不会粘进更长的词：`="等级:E"` 不命中 `等级:EX`、`="等级:S"` 不命中 `等级:S+`（想要更高档就带上后缀，如 `="等级:S+"`）
  - `&&` = **且**、`||` = **或**、`( )` = **分组**；`&&` 优先级高于 `||`；相邻词缺运算符时默认 `&&`
  - 反斜杠转义：`\%` `\&` `\|` `\(` `\)` 表示对应字面量（如搜 `攻击+20\%`）
  - 例：`(%敏捷% || %全属性%) && ="等级:E"` —— （含「敏捷」或「全属性」）且 精准「等级:E」
- **脚本**：提取 war3map.j / war3map.lua / wts 等
- **战役**：打开 `.w3n` 后顶部出现「子地图▾」下拉，可切换浏览**战役共享对象**和**每张子图**的对象/指令/配方
- **导出**：全部文件 / 脚本 / 各分类 ID 列表 / 资料包 —— **统一导到系统临时目录**(`%TEMP%/w3xtool提取/`)并自动打开（提取物都是临时文件）；战役会递归导出每张子图内部文件，CLI `--pack` 会自动生成 `子地图/001_名称/`，父包与全部子包的合并结果共同决定退出状态；外部 listfile 会参与“导出全部”和“资料包”的内部文件清单/资源扫描。资料包写入会区分完整、部分和失败，`组件诊断.tsv` 保留来源/阶段/异常类型，`资料包写入结果.tsv` 包含自身并保留每个相对路径的最终状态；GUI/CLI 不再把部分成功显示成完整成功。
- **隐藏指令 / 合成配方**：扫描脚本里的聊天指令与物品合成配方
- **预放置**：独立标签页列出地图上预放置的**单位**（类型/ID/所属玩家/坐标/生命/魔法/英雄等级）与**装饰物/可破坏物**（类型/坐标/缩放/生命/掉落），可按类型名/ID 搜索；类型码经对象表/原版名还原为中文
- **对象引用分析**（只读）：解析"哪些字段指向别的对象"，给出三类信息——① **正向引用**：详情区列出该对象用到的技能/训练单位/建造建筑/出售物品/依赖科技…（码还原成「名字(码)」）；② **反向引用**：该对象被谁引用；③ **孤立对象**：独立标签页列出定义了却没被任何对象/脚本/预放置引用的**自定义**对象（疑似废弃物）。二进制对象走字段**类型**驱动(FIELD_TYPES)、文本格式对象档走 SLK **列名**驱动（列名表借鉴自 U9/SLK 优化器 `Config.ini [SearchObjectData]`）。**不做任何改图/优化/裁剪**，纯只读分析。
- **地图智能审计**（CLI）：基于已解析数据输出结构化提示，覆盖对象/脚本/内部文件清单，以及缺 war3map.w3i、脚本缺失、引用覆盖低、某类自定义对象孤立比例异常、`war3mapMisc.txt` 自定义游戏平衡常数等常见排查点；所有结论均为只读分析。
- **脚本诊断**（CLI/核心模块）：扫描 `GetLocalPlayer`、`GetCamera*`、`DzGetMouse*`、`DzTriggerRegisterMouse*`、`Dz*` 等本地状态/扩展 API 调用；额外识别 `GetLocalPlayer` 分支内的 `CreateUnit`、`SetUnit*`、`SetPlayerState` 等同步状态修改，提示可能的异步、掉线或跨版本风险，供人工确认。
- **崩溃风险检测**（CLI/核心模块）：按已知地图崩溃案例做静态排查，例如 1.24E~1.26 下闪电链“每个目标伤害减少”配置到 -100% 或更低、脚本使用旧版游戏缓存 `InitGameCache`/`Store*`/`SaveGameCache` 等高风险 API 时给出告警；只提示，不改对象或脚本数据。
- **秘籍/调试口令残留检测**（CLI/核心模块）：扫描脚本聊天触发和字符串字面量里的官方秘籍短语，如 `whosyourdaddy`、`greedisgood`、`iseedeadpeople` 等，提示可能遗留的测试入口。
- **控制命令 / Order 分析**（CLI/核心模块）：扫描对象字段里的「命令串 - 使用/打开」等 orderString 字段，以及脚本里的 `Issue*Order("...")` / `Issue*OrderById(851xxx)` 调用；内置 360+ 数值 Order ID 映射并在 CLI 摘要里展示解码后的命令名，重复命令串会提示为冲突，方便排查技能施放互相抢命令的问题。
- **资源依赖分析**（CLI/核心模块）：从对象字段、图标路径、脚本文本和内部文件清单提取模型/贴图/音频/字体引用，统计引用素材、内部素材和未引用素材；同时读取 `war3map.imp` 的导入类型标志，区分标准 `war3mapImported\` 路径和自定义路径，辅助排查冗余导入、缺失资源或错误导入路径。
- **版本兼容报告**（CLI/核心模块）：默认按 1.24E 经典环境做静态检查，提示 Lua 脚本、1.31+ w3i 格式、大地图标志、DDS 贴图、1.20E 常见 `H2I`/`I2U` return bug 句柄转换等兼容风险；不做自动转换。
- **地形摘要**（CLI/核心模块）：读取 `war3map.w3e` 头部与完整 tilepoint 载荷，展示地形网格尺寸、W3E 世界坐标范围、基础地形集、自定义地形集标志、地表/悬崖纹理 ID，并把可识别地表纹理补全为编辑器中文名与 `TerrainArt\...\*.blp` 贴图路径；若 tilepoint 数据完整，会统计地面高度范围、水位范围、水域、坡道、荒芜地、边界/边缘格数量、实际使用的地表/悬崖纹理索引和悬崖层级分布，方便和预放置单位/装饰物坐标对照，也方便排查异常地形、水域、不可用边界或声明但未使用的地形纹理。
- **场景边界检查**（CLI/核心模块）：复用 W3E 世界坐标范围与 `.doo` 预放置坐标，统计落在地形范围外的单位、装饰物/可破坏物，并列出前几条越界实例；只做提示，不自动移动对象。
- **地图结构摘要**（CLI/核心模块）：读取 `war3map.w3r/.w3c/.w3s/.wpm/.shd`，展示区域、镜头、声音数量、路径图尺寸，并统计路径图里的禁止行走/飞行/建造、荒芜地、禁水和未知 pathing flag；若存在 `war3map.shd`，会结合路径图尺寸校验阴影图单元数量，并统计阴影/透明/未知格；同时从结构文件中提取可读的区域名、镜头名、声音路径等零结尾字符串，补齐常用内部文件说明里的静态排查信息。
- **SLK 清单摘要**（CLI/核心模块）：枚举地图内嵌 `.slk` 表，解析行数与有效列数，快速判断 SLK 优化图携带了哪些对象数据表。
- **游戏常数明细**（CLI/核心模块）：解析 `war3mapMisc.txt` 的节名、键和值，直接列出被覆盖的游戏平衡性常数。
- **游戏配置解析**（CLI/核心模块）：解析 World Editor AI 测试生成/加载的 `.wgc`，读取基础游戏速度、禁用战争迷雾/胜负条件、相对地图路径、玩家槽位、电脑 AI 难度与自定义 AI 路径；地图包内可见 `.wgc` 会并入 MapData，外部 `.wgc` 可直接用 `uv run main.py cli <配置.wgc>` 查看。
- **触发器树与 ECA**（CLI/GUI/核心模块）：解析 Classic 与 Reforged 1.36 风格的 `war3map.wtg`。分类、变量和触发器头不依赖游戏数据；ECA 事件/条件/动作/调用、参数、嵌套调用和子动作只有在匹配 `TriggerData.txt` 时才安全展开。`TriggerStrings.txt` 可用时，资料包 `触发器ECA.tsv` 的 `语义文本` 会按编辑器模板本地化；缺 schema 时保留头部和结构化诊断，不猜测函数体。
- **小地图标记摘要**（CLI/GUI/核心模块）：解析 `war3map.mmp`，读取小地图预览标记数量、坐标、颜色，以及玩家出生点/金矿/中立建筑分类统计，用于确认开局点和资源点是否被正确标注。
- **脚本侧引用补全 / 脚本特征**：依据 `common.j` 里每个 native 的参数类型（`CreateUnit`→单位、`UnitAddAbility`→技能、`CreateDestructable`→可破坏物…，离线烤进 `jass_natives.py`），脚本提码从早期只认物品/单位扩到**全分类**——大幅减少"孤立对象"误报（实测多张图孤立数降 1/3~2/3）。同时从 `blizzard.j` 提取暴雪 **BJ 机制**特征（对战开局/随机物品/中立建筑/电梯…）在「地图信息」展示，并把 BJ 隐式引用的基础对象并入引用根集合。数据均从工具包随包 `common.j/blizzard.j` 离线生成，不复制 .j 本身。
- **列表交互**：各列表/表格列宽随最长内容自适应，并带横向滚动条——长地图名 / 长物品名 / 长指令说明都能拉着看全；搜索框回车才搜，逐键不重建，大图不卡
- **编辑器式 GUI 工作台**：顶部保留打开/导出工具栏，对战图/战役图保持独立导航；主标签为「总览 / 对象编辑器 / 地图信息 / GUI触发器 / 场景放置 / 触发指令 / 合成配方 / 孤立对象 / 分析报告」。总览集中显示对象、脚本、场景与风险快照；分析报告把 CLI 已有的审计、兼容、资源、命令、崩溃、秘籍等只读检测汇总到 GUI。
- **单实例**：只允许开一个。再次启动时会先关掉上一个实例再接管，不会多开（靠临时目录锁文件记录 pid+映像，并对 pid 复用做校验，绝不误杀同 pid 的他程序）

## 代码结构（w3xtool/）
| 文件 | 作用 |
|------|------|
| `mpq.py` | MPQ 压缩包读取：头部定位、表解密、扇区解压、匿名加密 block 恢复 |
| `explode.py` | PKWARE DCL 解压（移植 zlib blast.c，标准库没有） |
| `w3obj.py` | 对象编辑器数据(w3u/w3t/w3a/w3q…)解析 |
| `doo.py` | 预放置实例解析：war3map.doo(装饰物/可破坏物) + war3mapUnits.doo(单位) |
| `imp.py` | war3map.imp 导入文件清单解析：导入类型标志、标准/自定义路径、候选实际路径和疑似缺失资源 |
| `w3i.py` | war3map.w3i 地图信息解析(名/作者/描述/玩家/队伍/脚本语言/尺寸) |
| `w3world.py` | war3map.w3r/w3c/w3s 世界编辑器数据解析(区域/镜头/声音) |
| `gameconfig.py` | .wgc 游戏配置解析：AI 测试速度、规则开关、玩家槽位、自定义 AI 路径 |
| `mmp.py` | war3map.mmp 小地图预览标记解析：出生点、金矿、中立建筑 |
| `wtg.py` | war3map.wtg 触发器树摘要解析：分类、变量、触发器头、Classic/Reforged 结构 |
| `map_extras.py` | 地图附加元数据加载：世界数据、.wgc 配置、WTG 触发器树 |
| `wct.py` | war3map.wct 自定义脚本解析(把二进制 wct 解出可读 JASS/Lua 代码) |
| `field_meta.py` | 字段码→中文标签/类型全量表(1444 标签/1521 类型，由 build_field_labels.py 离线生成) |
| `wts.py` | war3map.wts 字符串表 / TRIGSTR 还原 |
| `fields.py` | 字段 4 字符码 → 中文标签 |
| `references.py` | 对象引用分析：正向/反向引用图 + 孤立自定义对象报告（类型驱动 + 列名驱动，只读） |
| `audit.py` | 地图智能审计：把已解析 MapData 汇总成 CLI/后续 GUI 可复用的只读提示 |
| `diagnostics.py` | 脚本诊断：异步/本地状态/JASS 风险调用提示 |
| `crash.py` | 崩溃风险检测：已知高风险对象配置静态排查 |
| `cheats.py` | 官方秘籍/调试口令残留检测 |
| `orders.py` | 控制命令 / Order 分析：对象命令串、脚本 IssueOrder/IssueOrderById 引用、重复命令串冲突 |
| `order_ids.py` | 数值 Order ID → 命令名映射表 |
| `resources.py` | 资源依赖分析：模型/贴图/音频/字体引用图 + 未引用内部素材提示 |
| `compat.py` | 版本兼容报告：面向 1.24E 的 Lua/w3i/大地图/DDS/return bug 风险提示 |
| `terrain.py` | 地形摘要：解析 war3map.w3e 的地形集、纹理 ID、网格尺寸、坐标范围与 tilepoint 高度/水域/边缘/纹理使用统计 |
| `cli_terrain.py` | CLI 地形摘要渲染：坐标范围、纹理、贴图路径、地形点高度/水位/标志/纹理分布 |
| `terrain_tiles.py` | 地形 tile ID → 编辑器中文名/贴图路径可读化 |
| `scene_bounds.py` | 场景边界检查：预放置单位/装饰物坐标 vs W3E 世界坐标范围 |
| `mapmeta.py` | 地图结构摘要：解析 war3map.w3r/w3c/w3s/wpm/shd 头部、路径与阴影统计 |
| `cli_structure.py` | CLI 地图结构摘要渲染：区域/镜头/声音/路径图/阴影图 |
| `slkmeta.py` | SLK 清单摘要：枚举地图内嵌 .slk 表并统计行列 |
| `gameplay.py` | 游戏常数明细：解析 war3mapMisc.txt 的平衡常数覆盖项 |
| `slk.py` / `slk_objects.py` | SLK 文本解析 / 内嵌 *Data.slk 对象数据解析合并（SLK 优化图的字段与引用恢复）；字段标签去等级后缀化 + [AlwaysEmpty] 噪声列隐藏 |
| `jass_natives.py` | 由 build_jass_natives.py 从 common.j/blizzard.j 离线生成：native 参数对象类别 + BJ 隐式码/特征（脚本提码全分类化、地图特征） |
| `api.py` | 高层：加载地图→结构化→导出→战役递归 |
| `search.py` | 搜索打分：SQL 风格语法（`%LIKE%` / `="精准"` / `&&` / `\|\|` / 括号），词法→递归下降→AST 求分；`compile_query()` 把查询编译一次供多条文本复用 |
| `huffman.py` | MPQ 自适应 Huffman 解压（移植自 StormLib，压缩掩码 0x01） |
| `single_instance.py` | 单实例：再次启动先终止上个实例（锁文件 pid+映像校验，防 pid 复用误杀） |
| `gui.py` | CustomTkinter 图形界面 |
| `gui_reports.py` / `gui_report_tabs.py` | GUI 总览/分析报告的数据格式化与编辑器式报告面板 |

## 技术说明
- 魔兽地图是 MPQ v1 压缩包（`.w3x` 前有 512 字节 HM3W 头）。
- MPQ 头定位会在文件前 16 MiB 扫描 512 对齐位置，跳过校验不过的诱饵头，取第一个合法头（兼容 `_w3p` 等头部混淆图，同时限制恶意稀疏文件的扫描成本）；偏移 0 的合法 UserData 包装仍是权威入口。
- 压缩支持 zlib / bzip2 / PKWARE explode / 稀疏 / 自适应 Huffman(0x01，移植自 StormLib)，文件加密(ENCRYPTED/FIX_KEY)亦支持。
- 导出时不只依赖文件名：对 hash 表有名、但 listfile 缺失的文件，继续用三层并集查找；对 hash 表无名的匿名 block，会用 MPQ 扇区偏移表反推加密 key 后解压，按文件魔数/文本特征导出到 `Unknown/`。如果匿名资源内容里暴露了 `war3mapImported\*.blp/mdx/...` 等路径，工具会用 MPQ hash 反查对应 block 并恢复到原始路径；无法解码的 block 不静默丢弃，而是把原始 payload 写入 `UnknownRaw/` 供后续人工确认。
- 字符串按条 UTF-8 优先、失败回退 GBK（兼容老中文图与 UTF-8/GBK 混合编码的 wts）。
- 已在 `魔兽争霸杂交版1.00d.w3x` 上验证：war3map.j(2.5MB) 全部正确解出，对象/指令均能提取。
- 战役 `.w3n` 已用真实战役 `206774.w3n` 验证：7 张子图 + 顶层 2050 个共享对象，子地图下拉切换正常。
- 本工具做静态文件提取：常见的头部/表保护（`_w3p` 诱饵头、block 表注水越界）已容忍；真正的数据级加密（KKWE/1337 等）与运行时内存 dump 不做。遇到大量无法恢复的匿名加密块时，`提取完整性.txt` 会明确提示需要作者提供的未保护文件、明文/listfile/key；作者明文补充包提供一条可审计的静态继续分析路径，而不是绕过保护。

### 游戏版本覆盖（1.20 ~ 1.32+ 重制版）
能不能提取**不取决于游戏 exe 版本，而取决于地图文件里的格式版本字段**。三条互相独立的版本轴，工具均已处理：
- **对象数据**(w3u/w3t/w3a/w3q/w3b/w3d/w3h) 首部 int32 格式版本：`1`=RoC、`2`=TFT(含 1.20/1.24/1.27)、`3`=重制版 1.32+。版本 3 在 oldId+newId 之后是 **sets 分组**(支持 HD/SD 皮肤多组修改)：先 `sets` 数量，再每组 `setsFlag` 位掩码 + 修改数 + 修改项；工具按 sets 循环读取，各组修改合并。版本 1/2 等价于单组无 setsFlag。
- **MPQ 容器**：所有 WC3 版本（含重制版）**恒为 MPQ v1**，不会出现 v2+ 大档头，故无需按游戏版本分支；压缩按扇区掩码字节派发，与版本无关。
- **脚本语言**：JASS(`war3map.j`) 与 Lua(`war3map.lua`) 均读取（1.31+ 可能为 Lua）。
- **头部混淆图**：部分打包工具(`_w3p` 等)会在真 MPQ 头前塞一个垃圾"诱饵"头来骗解析器。读取时不取第一个 `MPQ\x1a`，而是取第一个**校验通过**的头，故这类图(数据本身未加密)也能正常提取。真正加密(KKWE 等数据级加密)的图仍不做解密绕过，但会在提取完整性报告中标明保护边界。
- **block 表注水图**：部分保护图把 MPQ 头里的 `block_count` 注水、声明 block 表长度超出文件尾（如 `|cffff99cc幻想未来v1.366`，连 `header_size` 都填成 `0xFFFFFFFF` 哨兵值）。只要 block 表**起点**在文件内，就只读实际存在的条目加载（与 StormLib 一致），越界的尾部自然丢弃；hash 表仍要求整表在文件内（既是正确性也是反 DoS 护栏）。
- 已用 85 张实战图(含重制版 2.03、各类 RPG/生存图、`_w3p` 混淆图、Huffman 压缩脚本图)实测：84 张成功提取对象/脚本/指令/配方。当时唯一失败者是 block 表越界的保护图——**这一类（block 表尾部越界）现已支持**（见上条，如 `幻想未来v1.366`：4320 对象 + 脚本 + 指令 + 配方均正常）；只有真正的数据级加密（文件偏移被彻底打乱、war3map.w3u 哈希从档里剥离）仍不支持。

## 已知限制（典型 JASS 地图够用，以下场景未覆盖）
- **放置信息**：已解析 `.doo` 预放置实例——`war3mapUnits.doo`(单位：类型/坐标/朝向/所属玩家/血蓝/金币/背包/技能) 与 `war3map.doo`(装饰物/可破坏物：类型/坐标/缩放/生命/掉落)，进 `MapData.units` / `MapData.doodads`，并在 GUI「预放置」标签页列表展示、CLI 显示数量。单位 doo 支持 **RoC v7 老布局**、**TFT v8 经典布局**与**重制版 v8 皮肤码布局**；经典与重制版同为 version 8/sub 11、重制版每条多一个 4 字节皮肤码，两种布局都试取能完整读完的那个（已用真实重制版图逐字节验证）；损坏变长尾部对不上时优雅降级（保住前置字段后停止）。
- **无名内部对象**：地图作者自己造、但没起名的幕后技能/buff，只能按代号显示（源头就无名）。**标准暴雪 buff** 的名字已补全（base_names 从 2075 增到 2299，含 BOsh=震荡波/Bbsk=狂战士等 ~200 个 buff，取自 *AbilityStrings.txt 的 Bufftip/EditorName）；引用到的原版对象未作为对象加载时也回退取原版名，故引用列表里的 buff 多数有名。
- **引用分析覆盖度**：正向/反向引用对**二进制对象**、**文本 INI 对象档**、**内嵌 SLK 对象数据**都有效（SLK 优化图的技能字段与 BuffID/UnitID 召唤引用现已恢复，实测引用边从 35 升到 564）；脚本侧引用已按 `common.j` 的 native 参数类型**全分类提码**。但若某图**根本没带**某类入边来源（如 U9 图缺 `UnitData.slk`/`UnitAbilities.slk`，单位→技能的 abilList 整体缺失），那类技能仍"看似孤立"。工具据此做**两条覆盖度自检**：① 自定义对象多却几乎无对象暴露引用字段，② 某类(≥50)孤立率 >40%（正常图各类仅 6~15%）——任一成立即在孤立标签页/CLI 标注"⚠ 多为误报，仅供参考"，不误导。
- 单个对象、脚本或编辑器组件损坏时会继续提取其他独立来源，并在 CLI、GUI 和 `组件诊断.tsv` 中保留具体来源与异常；损坏来源本身无法凭空恢复。
- 战役优先按 `war3campaign.w3f` 声明顺序加载子图，其次使用 listfile/常见名恢复；若 W3F 与 listfile 都被删除且子图使用非标准名称，仍可能无法枚举该子图。
