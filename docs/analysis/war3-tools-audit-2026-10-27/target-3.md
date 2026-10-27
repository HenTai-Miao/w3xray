> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# War3ReforgedTrainer 2.1.20 全功能静态审计

样本：`C:\Users\zhong\Downloads\War3ReforgedTrainer-v2.1.20-213F512FD188.exe`，30,268,092 字节，SHA-256 `213f512fd188c47ad62c4c16a40d956f75b86f20ab669d9338d93360fcd57f1c`。产品常量为 `2.1.20 / stable / 普通读取版 / PRODUCT_READ_MODE=normal`，默认 Game build 常量 `3.0.0.24268`。`normal` 区别于备用读取模式，并不构成全产品禁止写游戏的闸；本包包含大量明确写功能。

本次只做静态分析。没有运行目标 EXE、嵌入 bootstrapper、DLL、字节码或地图载荷，没有 LoadLibrary 目标，没有注入、写游戏或读取当前游戏。本目录未修改仓库。运行效果、当前进程兼容性及权限结果未验证；下列“支持”均指静态实现/资源链存在，另外列出禁用、失配和动态未知。

## 交付入口与覆盖口径

- features.json：全部功能、参数、效果分类、调用链、证据与GameXRay建议 (`audit://target-3/features.json`)，共 **1,009 条分层审计记录**。同一功能可能分别有 UI、service、protocol、DLL 视图，不能把这个数当作互不重叠的按钮数。
- coverage.json：全部第一方嵌套代码覆盖账本 (`audit://target-3/coverage.json`)：**176 个第一方模块记录、3,673 个代码对象、324,043 条指令**，独立 code ID 集合对账零缺失。包括 173 个 war3 PYZ 模块、2 个 diagnostics 兼容模块和 1 条 CArchive 入口。
- report-validation.json：独立集合/计数/源身份校验 (`audit://target-3/report-validation.json`)；container-integrity.json：原始TOC与分析前后摘要 (`audit://target-3/container-integrity.json`)。原始 CArchive 有 1,197 条 TOC 记录，其中 1,196 载荷与 1 运行选项；PYZ 998 项，无重复名或出界载荷；样本 SHA 前后相同。
- asset-ledger.json：1,196成员逐项去向 (`audit://target-3/asset-ledger.json`) 与 inventory.json：长度、SHA、压缩范围与原始偏移 (`audit://target-3/inventory.json`)，零未分类成员。第三方/stdlib 模块、Tk/Tcl 资源和依赖另列，不把它们的全部内部能力冒充为第一方可达功能。
- 审计方法、可信工具版本及证据限制 (`audit://target-3/audit-method.md`)。当前没有可用 REA MCP/provider，证据实际来自本地 PyInstaller、匹配 CPython 3.12 的 inert marshal/dis、pefile 和隔离 Capstone。完整 marshal、指令/常量 JSON、dis、AST、数据和原始输出保留，未用工具预览截断替代完整记录。

| 分卷 | 模块记录 | 嵌套代码 | 指令 | 功能记录 | 完整说明 |
|---|---:|---:|---:|---:|---|
| Web/Tk/CLI/应用入口 | 21 | 871 | 67,884 | 397 | UI卷 (`audit://target-3/scopes/ui/README.md`) |
| 版本、发现、档案、会话、适配器 | 35 | 699 | 66,492 | 85 | Discovery卷 (`audit://target-3/scopes/discovery/README.md`) |
| 协议、engine、传输与独立native控制 | 52 | 466 | 46,290 | 54 | Protocol卷 (`audit://target-3/scopes/native/README.md`) |
| 后端、Facade与业务服务 | 44 | 1,418 | 119,974 | 382 | Services卷 (`audit://target-3/scopes/services/README.md`) |
| 对象/字段/装备目录、MPQ、存档与纯解析 | 24 | 219 | 23,403 | 43 | Catalog/资源卷 (`audit://target-3/scopes/catalog_resources/README.md`) |
| 四个tools DLL | — | 原生机器码分列 | 可执行节/函数分级 | 48 | Native DLL卷 (`audit://target-3/scopes/native_dlls/README.md`) |

## 整体结构及所有功能领域

主入口 `war3_web_gui` → WebView2/pywebview + 本地前端 → `DesktopRpcFacade`/`DesktopBridgeApi` → `TrainerApplication` → `War3Trainer`/Facade/service → profile/adapter 或 `Engine24268` 固定 protocol → `war3_bridge_24268.dll` → 游戏线程 native handler。另有 Tk GUI、辅助对话框和 CLI。CArchive 与 PYZ 的入口六个 body/常量/异常表图语义相同，原 marshal SHA 不同，不能称为相同文件字节。

| 领域 | 静态实现的具体能力 | 主要入口/证据 |
|---|---|---|
| 连接与身份 | 显式 PID、多实例拒猜、进程完整性级别、游戏窗口/线程、exe 与 PE 指纹、创建时间、模块base、profile digest、地图 epoch；进程/地图切换失效缓存和typed引用 | `war3_backend`、`war3_game_session`、`war3_integrity`、`war3_object_registry`；Discovery与Services卷 |
| 版本与发现 | 七版schema5/bridge3档案；source digest、布局、ABI白名单与按依赖启用；PE分节快照/空洞、RTTI/函数定位、TLS/native表、调用ABI/字段/技能身份/selection/stats/语义见证；分阶段缓存与重验 | `war3_game_profile`、`war3_profile_resolver`、全部`war3_discovery_*`；下述资源失配会挡未知版默认发现 |
| Web/Tk界面 | 连接状态、单位/英雄/物品/技能/装备/扩展/场景/存档/批编辑/定义处理面板；中英文文案、搜索/筛选/输入校验、离线目录、后台任务、主线程交付、取消、通知、日志及原子数据保存 | 67 RPC与67前端wrapper、183 Application方法、166前端事件全部留档；68快捷键全绑定；Tk辅助/CLI另列 |
| 单位实时读取 | 普通/备用选中快照、候选/精确对象身份、所属玩家、四码/名称、英雄等级/经验/技能点/三围、生命/法力/最大值/回复、位置、护甲/防御、攻速和14类高级属性、技能/库存/扩展状态 | Facade按当前 indexed 路线读；部分为外部读取，部分调用native getter，不能整体称纯只读 |
| 单位修改 | 生命/法力/回复、属性、护甲/防御/攻速、等级、技能点、缩放、移动、无敌、寻路、暂停、控制权、冷却、击杀/爆炸击杀/移除 | `basic_fields`可直接外写；其他adapter或native；全计划预检/读回/回滚保护按具体方法不同 |
| 技能与施法 | 技能存在/等级/handle、增删/升降等级；boolean/integer/real与level字段读取/修改；目标/即时/点/无参效果、持有式施法观察/清理、全图敌方效果、冷却和能力可见性 | `abilities`、`ability_bundle`、`facade_abilities`、`ability*`/`effect`/`world_cast`/`direct_cast`协议；临时技能、Location和timer也属副作用 |
| 经典物品栏 | 六格精确快照、创建、删除、落地、次数、槽位替换、按目标身份事务、原始物品字段20项、附带技能查询/添加/效果字段；运行时目录试建/回收和安全性试建 | `items`/`facade_items`、`item*`协议；试建/清理功能不是读取 |
| 扩展背包/装备/天赋 | 30背包槽、9装备槽、6官方背包身份、6天赋控制器；读取、创建/移动/卸下/删除/恢复、普通物品装备化和分类修复、天赋点/选择/层级解锁、图标显示补丁 | `extensions`、`equipment_slots/effects`、`backpack_*`、`talent_*`；废弃/诊断action另列，不能因声明存在认作可用 |
| 套装与单位复制 | 单目标/多目标data-only方案、槽位/类型/charges校验、原子JSON存储；恢复生成新物品、部分完成/取消/防重放；单位复制普通栏/技能及扩展背包/装备/天赋状态、保留/归属/出生点选项 | `artifact_plan`、`loadout_*`、`batch_edit`、`clone*`协议；不会把序列化指针当恢复依据 |
| 玩家与资源 | 玩家数组/本地玩家、金币/木材等索引属性、精确所属；资源读写、金矿枚举/存量批改、科技允许量/研究等级、英雄经验倍率 | `facade_resources`、`player_resources`、`gold_mines`、world协议；统计和截断回执按操作保留 |
| 场景与输入 | 屏幕鼠标、游戏鼠标世界点、地形高度、相机目标/眼睛/参数、地图矩形；点选/输入协调、位置投影/地形落点；迷雾/黑幕、暂停/结束、全组治疗/冷却/建筑完成/联盟和敌方击杀 | `cursor`、`camera_projection`、`mouse_terrain`、`world`、`bulk`；截图/OCR/临时dummy部分入口实际禁用，见下 |
| 速度 | 原生0..4游戏速度档位及锁标志；另一路任意finite >=1的系统时钟倍率、健康状态、1倍恢复、驻留身份与watchdog | `game_speed` 与 `speed_clock_backend`/DLL是两种机制；后者hook计时API |
| 存码/存档/导出 | 文本/预载/Tooltip存码候选；私有堆ASCII/UTF-16明文命令候选扫描；`.w3v/.w3z`容器校验/解压/四布局缓存，保存时英雄属性/技能/库存字段；载入后的当前英雄快照；只新建导出文件 | `save_codes`、`gamecache_fields`、`save_extraction`、`archive_fields`；候选/保存时/当前live来源分开，不做平台加密算法解密 |
| 离线地图/战役定义 | MPQ本地读取/名称恢复/枚举、SLK与profile TXT结构解析、w3*四码、w3i资料/脚本语言、战役章节；复制输出后按manifest补齐背包/装备/技能定义，稳定源与完整成员/存储复核，批处理1..1000文件 | `extension_definitions`/definition jobs；这是写输出地图/战役的功能，输入源保持只读；不是GameXRay当前只读采集功能 |
| 日志与恢复 | 请求日志、native journal、操作trace、值/地址/身份出处、错误stack、84业务reason、交付/读回/效果/cleanup分离、保留不确定资源并禁后续危险重放、部分完成事实 | `error_messages`、`native_journal`、`operation_reports`、`game_session`、engine/transport；各层策略不可互相概括替代 |

全部参数/默认值/handler/native名称与数字action→真实caller映射见每卷features及完整method/protocol目录。仅存在于`co_names`的旧流程、禁用函数和未打包helper均在覆盖账本保留，但没有提升为可用功能。

## 本包数据与版本资源

七个bundled profile均自报`validated`，并不代表本次已真机验证：`3.0.0.24268`、`3.0.1.24323`、`3.0.1.24332`、`3.0.1.24342`、`3.0.1.24360`、`3.0.1.24365`、`3.0.1.24371`。完整指纹、301标量叶×七版、布局/native ABI/module启停/check字节及两个discovery JSON见 profiles_summary.json (`audit://target-3/scopes/discovery/profiles_summary.json`)、profile-field-matrix.tsv (`audit://target-3/scopes/discovery/profile-field-matrix.tsv`)。

已观察到不同版本有显式空缺：24365 的 speed/effective_interval、ability_level_tail 和 fog recovery 字段为零，stat_details禁用；talent_icons仅24268启用，另外六版禁用。不能因“七版档案”泛称七版具备相同功能。

| 静态数据件 | 本样本实数与性质 |
|---|---|
| ID目录 | 283 item / 833 ability / 834 unit；来源固定快照，名称/描述/来源部分性保留 |
| 描述数据 | 651 item / 1,495 ability / 937 unit；与主目录的附着命中另有数量，不能把描述表总量当地图实时对象数 |
| 能力字段 | 753字段目录与中英labels；680 runtime资格、679 writable资格；并非全部字段在所有版本/当前技能可读可写 |
| 物品/高级属性 | 20物品字段；14 STAT_DETAIL_SPECS；8基础生命/法力/回复/坐标key |
| 官方装备 | **325条**，Ring66/Primary60/Chest39/Offhand39/Head38/Gloves32/Trinket28/Boots23；旧文档495不是此样本事实 |
| 官方英雄技能 | 6名官方战役英雄27技能；只作目录，不证明当前地图包含 |
| CASC catalog | 3.0.0.24268来源的648 item /473 ability /928 unit与源SHA；本模块只有静态数据，**没有CASC存储访问实现** |
| MPQ标准资源名 | 1,191条隐式路径；不能据此认为归档只含这些成员 |
| 定义包 | source3.0.1.24360，186成员=45SLK+140TXT+manifest；185数据hash/bytes全部匹配；37 required表/6,610 ID引用、1,906 dependency项/4,086边、102关键技能/6关键背包物品 |

完整literal数据见 data_catalogs.json (`audit://target-3/scopes/catalog_resources/data_catalogs.json`)、ID目录 (`audit://target-3/scopes/catalog_resources/id_catalog_data.json`)、描述目录 (`audit://target-3/scopes/catalog_resources/id_descriptions_data.json`)、definition-assets.json (`audit://target-3/definition-assets.json`) 和 完整定义manifest (`audit://target-3/definition-assets/manifest.json`)。原SLK/TXT全部保留；本审计的数据索引不是游戏运行或地图可用性验证。

## 新样本的失配、禁用与重要限制

| 发现 | 证据与影响 | 结论级别 |
|---|---|---|
| 七个discovery source_digest陈旧 | references中的七digest都不匹配当前profile canonical SHA；去掉新添四个item ability布局字段后七个全部精确匹配。`ProfileResolver.resolve`先作recipe/source digest闸，未知build默认发现路径止步；exact build提前返回 | 资源一致性已独立复算；未知版行为是静态控制流推断，未运行 |
| Web初始化按钮未接通 | JS `167612,167649)`通用action发送`prewarm_elephant`；`execute_elephant_action`的30接受项不含该名，末路Unknown action。独立同名RPC存在但wrapper零使用 | 静态路径预期失败，未运行 |
| Web实时英雄读取被存档目录门控 | `readLiveHeroes`事件byte200037位于`files.length>0`渲染块；没有存档时该live入口也不显示 | 静态前端条件事实 |
| 三诊断协议无DLL实现 | talent_probe/equipment_probe/cooldown_probe的marker和Query导出缺失；legacy_equipment_probe虽共享extension ABI仍为production禁止 | 精确目录/PE导出与marker核验 |
| 旧helper不可当当前功能 | `tools/war3_engine_24268.dll`未打包；当前managed GameSession下旧helper先被拒绝，主链是`war3_bridge_24268.dll` | 实际分支及打包清单事实 |
| dummy cast / screenshot / OCR旧入口禁用 | 服务入口直接抛错；旧名字残留不证明可执行 | 实际指令事实 |
| UI与枚举上限 | Web目录只回前200但matchCount完整；Web存档只前100且无total/omitted；clone warning仅前12项（完整日志另存）；DefinitionJobs 1..1000 | 按入口分列，不能误说所有输出全量 |
| 协议与遍历边界 | selected/source24、经典栏6、包30/装备9、field batches32或20、clone每单位128技能、金矿4096、item/target100000、native表8192/string256、module4096、forwarder16、work1MiB等 | 固定wire/请求/遍历guard分别标注，不把它们当游戏总量证明 |
| 发现/存码/缓存限制 | 默认发现30秒/256MiB；存码heap默认2GiB/20秒且gap/complete明确；缓存输入64MiB/raw128MiB/块数等结构guard详列；selection candidate limit=0返回空 | 本样本边界，不照搬为GameXRay隐藏截断 |

预热、实时英雄按钮和网络/授权的精确前端字节切片见 [UI卷 (`audit://target-3/scopes/ui/README.md`)，档案问题见 Discovery卷 (`audit://target-3/scopes/discovery/README.md`)。所有限制的完整数值/条件及精确字节码偏移保存在功能JSON，未仅以表中例子代替全集。

## 原生DLL、读写和网络边界

pe-inventory.json (`audit://target-3/pe-inventory.json`)覆盖原EXE与91嵌入PE。原EXE manifest资源ID`24/1/0`为`asInvoker`，证书表范围和资源全部保留，签名未验证。四个tools DLL共有151个导出（代码、数据、forwarder分别标注）。

| DLL | 字节 | 导出 | 静态行为与GameXRay边界 |
|---|---:|---:|---|
| war3_bridge_24268.dll | 149,504 | 90=43代码+47数据 | 固定命令/ABI/profile/fault/lifecycle和native调用dispatcher；39 production操作均有本包marker/query接合，仍不代表游戏效果已验证 |
| war3_mpq.dll | 494,592 | 53 | StormLib完整文件/HTTP provider与读写导出；Python明确有受writable闸的read/write/flush/compact/reserve，写用于输出定义图；文件系统路径调用链未见URL路由，未额外拒绝UNC共享 |
| war3_speed_clock.dll | 19,968 | 2 | SpeedControl+ABI，QPC/GetTickCount/GetTickCount64/timeGetTime hooks、连续锚点和watchdog；非只读 |
| war3_talent_icon_display.dll | 5,632 | 6=2代码+4数据 | 校验→VirtualProtect→在gamebase+0x10058c7写/恢复36字节→FlushInstructionCache→保护恢复及逐字节复核；非只读 |

Native DLL卷 (`audit://target-3/scopes/native_dlls/README.md`)区分`.pdata`函数范围、无unwind叶函数候选和全可执行节线性扫描；没有把线性扫描候选全称作已证明可达代码。所有导出RVA/文件偏移/ABI字节、调用候选、未绑定间接target和原生未知完整保留。

“读”必须分层：纯离线解析/计算；外部内存读；业务native查询；外部内存直接写；经bridge修改；输入效果；本地宿主/输出地图文件写。engine的业务读也会分配/写remote buffers、LoadLibrary/SEC_IMAGE、remote thread、Windows hook、临时组/Location等，不能因按钮或方法以read/query命名就认作纯ReadProcessMemory。

固定operations目录确有只读白名单，不信调用者标签；`session_entry`上层还含read_/get_/locate_等方法名前缀豁免，不能把前者推广为所有包装器的统一闸。交付、callback进入/退出、业务完成、读回、效果、解除hook/消息排空、资源释放分别留证。写事务并非普遍回滚：字段有专门恢复闸，套装/克隆有部分提交，资源与基础字段有不同语义，失败后的已完成写入不可隐去。

授权/网络审计只作有界结论：第一方UI与前端未识别产品注册码/许可证/激活/远程产品更新控制流；依赖中存在cryptography/bcrypt不等于产品授权。缺WebView2时存在询问→固定SHA256核验内置bootstrapper→`/install`（900秒超时）→复检的正控制流；这是组件安装。前端唯一fetch是modulepreload shim，本地资源之外的URL常量是组件说明/开发服务器/框架文档。不能外推第三方WebView2、bootstrapper或StormLib永不联网。见 UI网络/授权证据 (`audit://target-3/scopes/ui/network-and-authorization.json`) 与 前端全部AST网络/授权候选 (`audit://target-3/scopes/ui/frontend/network-and-authorization.json`)。

## GameXRay可用性

| 采用层级 | 可以做什么 | 前提/不应迁移部分 |
|---|---|---|
| 可独立借鉴的纯数据/解析 | 版本化字段目录、四码/名称/描述/来源、SLK/TXT与w3*结构校验、真实存档框架/四布局歧义、存码明文候选、data-only导出/原子持久化、纯坐标投影和错误证据 | 重新实现并保持完整原始字段、源身份、类别/地图作用域；官方目录不等于当前地图；避免复制样本容量/时间截断；源图继续只读 |
| 可用于现有只读架构增强 | PID+creation-time与模块/地图epoch、typed引用、来源地址/字段值快照、缓存重验证、部分读/扫描洞与不确定性、按功能依赖启用、后台取消/主线程交付、请求日志与清理状态 | 这些是设计候选，需按当前GameXRay代码/需求判断差额；不能宣称此审计已实现或已真机通过 |
| 条件研究的重制版读取 | 七版布局/指纹、对象registry、玩家属性、组件/能力/物品身份、选中链、native表纯外读及ABI见证 | 当前GameXRay x64/Reforged链仍有pending边界；必须用目标版本真机独立外读验证。不能直接执行提取DLL或照搬调用native getter的读链 |
| 当前只读产品不采用 | 内存写、修改属性/资源、创建/删除/复制/移动、技能/物品/装备/天赋变更、施法、输入控制、remote加载/hook/patch、计时倍率及修改输出地图 | 仅作功能对照与边界记录。此任务没有实现这些功能，也没有获得由静态阅读推导出的运行授权 |

当前代码对照的具体锚点和每项建议在各卷features保留。例如GameXRay的x64/reforged仍可返回pending；其当前DERIVE_STAGES实际5项、ScanBudget默认无截止，不沿用旧AGENTS文档中16阶段或旧样本495装备的说法。当前进程身份比较exe路径，与Trainer creation-time绑定有差额；这些是进一步只读增强候选，不是本次代码变更。

## 残余未知与闭环

第一方模块和嵌套body的完整解码/内容事实、UI事件/RPC、协议/ABI、所有打包与嵌套资产都有去向，覆盖账本无未指派代码。原生间接游戏handler的全部可能目标、调用后效果、不同OS/游戏会话的动态路径、第三方库内部全部语义及真实兼容性仍未观察；这些不是由字符串/导出/marker一致就能证明的事实。原生线性扫描与算法识别均保留候选等级，不声称原始源码或形式证明。

本目录的完整功能JSON、body/AST/数据、分卷说明和未知条目足以继续定点深挖；本次闭环是**完整静态清单与可追溯功能解释**，没有把静态结论写成目标运行通过。
