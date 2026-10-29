# Trainer 源码全量覆盖与本轮采用记录（v12）

审计日期：2026-10-29。来源为 `war3-reforged-trainer` 的
`main@39ddabe2dc16ca7c3be9911c41dc22c83d1b9c4d`；产品对照起点为 GameXRay 0.11.0，
`3b12a498c7e0ee507526dc5be2bcab867989a435`。本文件中的 v12 是审计标识，不是发行版本号。

**344 个当前源文件已全部建立字节身份、实际静态语义证据和能力对应。本轮适用的离线、只读能力已实施并通过各域针对性验证；正式集成、完整回归、真实 GUI 和发布验收的最终结果以同版本交付报告为准，本表为各域针对性证据。**
这里的全量覆盖不表示所有 Trainer 执行逻辑、第三方机器码、标准库函数或游戏行为都已实测。

配套 [逐文件全量清单](trainer-source-coverage-2026-10-29-v12.json) 包含每个文件的路径、大小、
SHA-256、Git blob、文件身份、覆盖类型、能力 ID 和实际审查证据；`current_adoptions` 单列本轮采用，
`capabilities` 保留历史细粒度记录及当前 2.1.22 覆盖层。历史实施/测试结论没有改写成此次结果。
`evidence` 使用证据容器内相对路径、大小和内容哈希；关键结论已经嵌入两份文档，不要求读者依赖原临时目录才能理解覆盖范围。

## 来源身份与全量分母

| 范围 | 实际结果 |
|---|---:|
| 受控源文件 | 344 / 9,902,801 字节 |
| Git 管理文件，单独分类 | 100 / 63,022,684 字节 |
| 所有普通文件 | 444 / 72,925,485 字节 |
| 目录 | 97 |
| 未跟踪 / 忽略 / reparse 或特殊条目 | 0 / 0 / 0 |
| 文件读取、身份错误 | 0 |
| 与冻结源码 ZIP 同字节的源文件 | 344 / 344 |
| 已验证身份并关联历史实际语义证据 | 327 |
| 本轮完整补读的文本、控制流和文档 | 15 |
| 本轮补齐容器、原生身份与有限证明 | 2 |
| 无能力对应或无覆盖说明 | 0 |

207 个 Python 文件中的 2,254 个函数定义（含嵌套）及 209 个类只是覆盖分母，不能替代语义审查。
其余文件包括 C/C 头、汇编、Svelte/TypeScript/JavaScript、JSON、构建配置、文档和二进制资源，
均出现在同一个 344 项索引中。

冻结源码为 `source-39ddabe2.zip`，5,553,689 字节，SHA-256
`ca4d94fe00b413bf60d6a30f2f77403e67d9ea5c60065d139f4fb74d06e339e0`；
366 个 ZIP 条目为 344 文件和 22 目录。成员完整读至 EOF，核对 CRC、大小和 SHA。
文件系统库存显式拒绝 reparse，使用不跟随的 Win32 文件/目录句柄、祖先目录身份和全字节前后校验。

327 项历史证据由三组相互重叠的实际关联组成：297 个文件与旧源码审查同字节，191 个当前 Python
源文件对应已审查代码对象及源码归一化证明，44 个当前前端文件对应完整快照与页面/RPC/事件审查。
**不能把 297、191、44 相加；也不能仅凭同名文件继承旧结论。**
旧覆盖文档绑定的是 `274881ad8bf6ab4340e883a9228604b4698a109f` 的 324 个文件，不能直接充当当前清单。
两次源码比较为 297 同字节、21 改动、26 新增、6 移除；当前改动文件由当前证据补足。

本轮 15 个补读文件是中英文 README、2.1.22 spec、CLASSIC_HKE 和 MPQ 恢复说明、VALIDATION.json、
pjass LICENSE、modern/2122 release builder、map reference/upgrade generator、2122 baseline/HKE/dependency
preparer 和版本资源文本。另两项为 `assets/map-script-validation-v1.zip` 与
`tools/map-script-pjass.exe`；其覆盖层级分别是完整容器/声明库存、原生结构及既有有限语义证明。
具体逐文件阅读范围和结论见 JSON，未用扫描出文件名或 AST 定义数冒充这些阅读。

库存终验时，全部 444 个文件的内容、大小、身份、mtime、创建时间及 HEAD/源 Git 清洁状态均保持一致。
97 个目录身份均未变，96 个目录的全部核对元数据未变；唯一观察到的是 `.git` 目录 mtime 从
`1793281295667286500` 变成 `1793282188890084500`，其他身份字段及其中 100 文件不变。
没有推断并行 Git 观察者的具体成因，也没有回写时间。访问时间不在不变声明之内。

## 本轮实施的适用能力

| 能力与实际缺口 | 产品变化 | 保留边界 |
|---|---|---|
| 完整脚本调用证据 | `script_behavior_index.py`、`script_behavior_catalog.py`、`script_behavior_syntax.py` 保留每个零参数、嵌套、重复位置和动态接收者调用的原文、所有参数、源码偏移、函数目标、绑定、词法分支/循环；313 个标准声明保留 native 与 Blizzard 函数区别 | 不把词法上下文当成运行顺序、分支可达或游戏效果；遮蔽、私有环境、未知语言和动态接收者保留未知 |
| `calls` 查询与完整交付快照 | `pack_query_script_calls.py`、`pack_query_script_snapshot.py`、`script_call_query_models.py` 支持空词全列、Boolean 搜索、整记录限制、完整 TSV 原始行/扩展/错误后缀和诊断；源码优先，最终复核全字节、身份、目录成员和缺失观察 | 索引不制造 native 绑定或物理调用次数；变动保留原快照并标为失败，最终 campaign 交付前复核由公共执行路径调用 |
| 脚本调用 GUI 及交互闭环 | `gui_pack_query.py`、`gui_pack_query_modes.py`、`gui_shell_object_panel.py` 新增「脚本调用」及对象右键交接；统一三行模式，修复空预填、收藏按钮和 Markdown CRLF 输出 | GUI 专项使用无真实 Tk 的替身；实际窗口、顶层路由、again 与发布属于正式集成验收 |
| 离线装备方案工作台 | 新增 `loadout_documents.py`、`loadout_report.py`、`loadout_cli.py`、`gui_loadout_workbench.py`。明确文件读取六槽 artifact-plan 与九槽 equipment-loadouts，保留额外槽位、所有记录、重复键、未知扩展、原始字节与整数 token；支持整记录查询和 JSON/Markdown/可逆 TSV | 只读方案证据；输出报告不是可导入或恢复的游戏方案，没有自动装备、native 调用或自动读取用户偏好 |
| save JSON 超长整数分类 | `real_save_files.py` 的分类复用显式栈 JSON 语法读取，公开 `analyze_real_save_path` 不再因 5000 位整数触发 Python int 转换配额，保留重复键原文及源字节 | before probe 证实的是超长整数失败；同次 1500 层数组原先成功，没有虚报深度缺陷；不改写、解密或恢复存档 |
| W3F v3 战役信息错位 | `w3f.py` 正确处理 race 后五个 float 和一个 signed int，再读取 background version/章节表；`map_components.py` 使用 evidence API，`map_metadata_exports.py` 导出原始字节、字段区间、尾部、重复记录和分层完整性 | v1/v2/v3 各按证实布局处理；未知版本和损坏头不猜。兼容入口仍保留历史 None 合同，证据入口不丢已读内容 |
| 显式 BOM UTF-16 WTS | `wts_parser.py` 的结构视图映射到原始 UTF-16LE/BE 字节位置，严格解码往返才确认记录；`script_sources.py` 只处理 WTS 显示分支 | 不猜无 BOM 编码；非法代理、奇数字节尾部与冲突原文完整保留；不改 JASS/Lua 脚本字节或偏移 |
| 独立地图自定义继承及覆盖证据 | `map_loader.py` 对普通 .w3x/.w3m 也调用现有类别限定迭代解析；`object_inheritance.py` 将被更高优先级子字段覆盖的父字段标为 overridden，并传播到后代 | 原始父字段、来源、字节、同级冲突全部保留；缺失/循环/歧义/跨类别同码不猜赢家；空覆盖仍有效 |
| 战役章节实际路径拼写 | `map_loader.py` 核对 W3F button/order、已知 archive 拼写及真实 `has_file` 结果，恢复 stripped-listfile 战役的实际成员 | `/` 与 `\` 两种成员都存在时保留两者，明确 order 优先；不改变 MPQ 名称哈希规则，不把规范化猜测当存在证明 |
| 默认 MPQ 资源候选名 | `build_mpq_resource_hints.py`、`mpq_resource_hints.py`、`archive_export_recovery.py` 引入完整 1191 个固定候选，保留源码 commit、两个文件哈希和四个上游声明哈希；导出附 provenance 侧车 | 1191 不是已恢复资源数。`candidate_only=true`、`game_version=null`；真实成员仍须 hash/probe chain/`read_file_entry` 证实，locale/platform/block/alias/UnknownRaw 保留 |
| 本地 profile 重复 JSON 键 | `live_profile_json.py` 统一 live override 与离线 reference 的 UTF-8/文件首 BOM 和所有深度重复键处理，再交既有 schema 验证 | live 失败记录诊断并退回内置 profile；离线返回输入错误。没有移植偏移、桥、注入或新增 Reforged 运行支持 |

公共入口的目标合同为 `pack-query <pack> calls [Boolean expression] [--limit N] [--json]`，
以及 `loadout <file> [--query EXPR] [--json] [--text-encoding ...] [--export PATH] [--format json|md|tsv]`。
领域实现及针对性用例已通过；菜单、帮助、公共 campaign/again、版本/缓存/质量清单整合与正式验收
的最终结果以同版本交付报告为准，本记录不替代这些公共入口和发布产物的验收。

## 缺口复现与独立证据

- **W3F**：179 字节独立 fixture，SHA
  `2f44e827c684b10fa22c9982ae256ed6c953f106ee3e298514913e35d15f9854`，
  修复前错误返回空章节、background 0 且无诊断；修复后真实章节、background 2、全字节消费并完整。
  布局同时对照固定 War3Net 提交 `5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8` 的 reader/writer；
  每个字节前缀截断、未知版本、损坏尾部和非有限数值均有明确诊断。
- **WTS**：独立 UTF-8、UTF-16LE BOM、UTF-16BE BOM 三份同内容输入，后两份由零确认记录修复为各两条。
  补充回归覆盖 U+010A、补充平面字符、内嵌 BOM、STRING 正文、CR/LF/CRLF、非法代理与后续有效记录；
  真实合成 MPQ 验证对象名称、WTS 可读导出、原始 base64 证据和 JASS 不变。
- **继承**：独立地图 I002 → I001 → ratf、子记录先序列化，修复前只有 ID 名且缺少父 gold 37，修复后取得父名和值。
  同一输入 SHA `f8bf0b7228a455c066640411077907cc853ad322c79f0fe4ebfbe33352f4d2aa`
  不变；真实 item/price JSON CLI 都返回 0，知识包写出 72 文件、0 失败。
  独立验收又发现子 gold 7 已正确但父 91 仍标 confirmed；此次修复保留父值并改为 overridden，原断言未放宽。
- **MPQ 候选收益**：独立加密、无 listfile/无引用的 `FullScreen.blp`，修复前自动仅保留 UnknownRaw，
  显式外部名称可还原；修复后自动还原相同 82 字节。
  MPQ SHA `96d95e9c8bf546e61fda872b89abaa145232615f6fdfe532783b96b3f2cf75c3`，
  明文 SHA `c8f9d7594424b2f28b9ecce48f25466567ebc46b8365926328ad3ea87cb9977c`。
  另有全部 1191 名称逐独立加密物理块验证、未知块、locale/platform、碰撞及引用闭包专项；不是只测一个示例后推算全部有效。
- **profile**：原先 live 接受顶层、fingerprint.machine、checks.rva、field offset 重复键，而离线已拒绝；
  共享解析后两者一致拒绝。重复相同值、转义键、不同对象同名、BOM、超过 2 MiB 和 1502 字段均覆盖。
- **save JSON**：公开入口在读取 `{"quantity":<5000 位整数>}` 时曾抛 ValueError，修复后保持全文件可分类，
  同时检查单文件、目录、重复键原文、完整 SHA/元数据和非 JSON 分类，原失败证据仍保留。

## 已有能力、未采用路径与已知缺口

0.11.0 基线已有正常/Skin/campaign/chapter 对象层、v3 修改证据、完整参考目录、多选导出、
存档文本编码边界、版本化字段类别、精确 MPQ 成员/引用恢复和语言敏感脚本诊断。
这些不能再次包装成本轮新增。完整 ID 目录的 283 物品、833 技能、834 单位、90 科技合计 2040 项，
以及当前 325 个装备身份、6 名英雄的 27 技能身份均已在产品基线存在；当前装备数不是历史材料中的 495。
固定构建说明不证明当前地图有这些对象，也不能覆盖地图自定义字段或证明可装备性、掉落与运行效果。

实际 HKE 发布路径是 MapScriptsPanel → DesktopBridgeApi → MapScriptJobs → DefinitionJobs →
prepare_map_script → `_patch_chapter` → `war3_huolong_runtime.generate`。
另一个 generic generator 虽有 50 个静态命令能力，未见发布调用者执行其 generate；配置保存的
prefix/features/resource_amount 也不全部被实际 HKE 生成路径消费。原 196 个 HKE 函数及菜单语义有静态证据，
没有因此执行 HKE 或生成、加载修改地图。本轮采用的是只读调用证据与纯数据能力。

原生边界按真实调用链判断：43 个 OperationSpec、41 个命名 handler、90 个 release bridge 导出不等于
43 个当前可用游戏功能。talent_probe、equipment_probe、cooldown_probe 的生产导出缺失；部分实现仅诊断条件可见。
源码 checkout 缺少默认路径中的 bridge/clock/icon/MPQ DLL，已有 release 的 DLL 是另外的已核对字节。
`read_query`、getter、action 0、dry-run 和回滚标签不能消除 transport 远程写入、注入、回调、组选取或临时物品/Location
生命周期。七份 profile 的 source_digest 与所提供参考内容的 raw/loader-normalized 摘要均不相符，
这是来源绑定缺口，不能单凭它判定实际运行失败。未新增偏移、native bridge、注入或当前构建支持声明。

源构建与有限二进制证明还有以下明确边界：

- VALIDATION.json 的 336 项输入声明中，335 个现有文件哈希一致；`assets/webview2-bootstrapper.exe`
  是缺少的外部准备输入。源作者的测试、GUI、战役声明不转记为此次实测。
- 三个当前生成器 `generate_map_catalog_reference.py`、`generate_upgrade_catalog.py`、
  `generate_war3_id_descriptions.py` 均导入缺少的 `tools/generate_forsaken_equipment_catalog.py`。
  源、未跟踪与忽略库存均无该模块；“两个生成器”的旧计数不再适用。没有执行源构建脚本。
- 标准库 ZIP 五个成员及四份 JASS 共 1,531,022 字节完整核对、所有声明哈希匹配；完整声明列表不证明每个库函数运行语义。
- pjass 为 138,872 字节，SHA
  `45911ae998b23155c8d408597c616cf080a3fa16b4cf2e1bacb239757c704d5c`，
  文件及 `.text` 与既有有限审查同字节。17,190 条线性指令候选不是所有可达路径证明；
  `//#` 抑制错误且 exit 0 的可信度问题仍保留，没有运行或加载该 EXE。
- 没有重建 Svelte bundle 以证明源码到产物完全等价；已有页面/RPC/产物静态审查按原层级保留。
  原 frontend 的 dict/list 形状、Elephant 初始路由、200 条界面上限、取消竞争、原始值复制遗漏和过期异步结果问题
  仍记录为来源问题，没有随界面模式一并复制。

按构建限定的双语描述比较、明确 W3I/data-mode 的基表差异查看，仍可作为独立离线工作评估。
当前证据不把它们宣布为未修复产品缺陷，也不自动选择一套基础数值作所有地图真值。
HKE/对象补齐/MPQ 新副本改写是真实作者工具能力，但需要另外的范围与验证设计；“原地图只读”本身既不是
它们的运行兼容性证明，也不是用文件覆盖数掩盖这些边界的理由。

## 已完成的针对性验证

以下为各域最终报告与日志范围，**不得相加为唯一用例总数或本轮正式全量通过数**。部分组覆盖同一公共模块，
objects 的后补 2 项也与 57 项组重叠。清单作者核对报告，没有再次执行产品测试。

| 范围 | 已记录结果 | 实际层级 |
|---|---|---|
| archives/W3F/WTS/加载导出 | 137 passed；额外边界 17 passed | 独立字节 fixture、真实合成 MPQ、脚本边界和超过一万章节；7 路径 lint/format/type 通过 |
| objects 继承与证据状态 | 初轮 44 passed；追加 override 57 passed；后补同级与独立断言 2 passed | 1200 对象链、原独立验收断言及全字段保留；最终 4 路径静态检查通过 |
| campaign 拼写 | 最终 12 passed | stripped listfile、单双路径、顺序、缺失诊断及不改输入 |
| scripts 核心 | 247 passed | 313 标准声明、深层绑定/括号、2501 调用；原 HKE 文本只作静态分析，5 路径静态检查通过 |
| calls 适配器 | 47 passed | 原始 TSV、全部诊断、同大小同 mtime 变更、最终跨章节复核；5 路径静态检查通过 |
| frontend | 96 passed | 查询模式、空词、收藏及原样导出；无真实 Tk；相关 lint/format/type 通过 |
| offline loadout | 26 passed | 全记录/额外槽/超长整数/深层扩展/重复键/导出/源稳定性/过期工作结果；7 路径静态检查通过 |
| offline save JSON 分类 | 16 passed | 独立新增回归加既有 real_save_files；lint/format/type 通过 |
| resources | 54 passed，0 skipped | 全 1191 独立物理块、Unknown/UnknownRaw、locale/platform/alias/闭包/冲突；4 路径静态检查通过 |
| native/profile 文件验证 | 351 passed，0 skipped | 共享重复键与现有 profile/reference 回归；相关静态检查通过；没有 live game 操作 |

测试使用 `gamexray-test` 私有运行缓存；独立 CLI/解析探针使用 `dev_test.create_test_environment()`。
资源域首轮普通权限有两项 fixture 失误及五项 Windows symlink 权限失败，原失败日志保留；修复 fixture 后复用
已授权 High session 完整运行，最终无 skip。读取 High scope 的 ACL 失败和逐字节复制证据也保留，未改 ACL 或安全策略。
对象域一次并发 uv 更新启动器被 Windows 拒绝，随后使用已存在解释器完成专项；失败不记通过。

**最终结果以同版本交付报告为准；本表为各域针对性证据。** 本记录不单独声明最终发行版本、
全量通过数、真实 GUI 或打包成功。同版本交付报告应绑定实际冻结文件、完整回归与发布产物，不能用本表代替。

## 可搬迁的证据定位

旧证据均来自 GameXRay-0.11.0 交付，先核对完整 ZIP，再按成员与源码身份关联：

| 容器 | 字节数 | SHA-256 |
|---|---:|---|
| `analysis/inherited/source-audit-evidence.zip` | 15,610,831 | `3831e4c5a9410383e79cfb51d3e959956641205d6dfc376ccc3c3cce42926750` |
| `analysis/complete-static-evidence.zip` | 187,809,406 | `fd493634cca8787b58657b6d12d911c0d1449937ad71f7d69e856df991bcd3e4` |

本轮证据逻辑根为 `gamexray-source-completion-20261029-2mrwwf0_`。来源库存的 61 个载荷文件共
23,374,467 字节；其 `inventory/artifact-manifest.json` SHA 为
`696201562c7b978f50ec34ad839ca096ec70549fe0b450f6d32939c509b2f02a`，清单自身及其 SHA 文件明确不计入载荷。
配套 JSON 的 `containers`、`evidence` 记录相对成员路径与真实哈希；搬迁或归档后可按内容身份重新定位。
此次引用的 20 份分域报告/证明另存为 `inventory-publication-evidence/` 下的内容哈希命名快照，
JSON 同时保留 `reviewed_origin`。后续根验收追加原报告时，不会悄悄改变本记录实际引用的字节。

核心入口为 `inventory/source-capability-inventory.json`、`capability-adoption-matrix.json`、
`source-manifest.before.json`/`after.json`、`source-preservation.after.json`、`current-source-supplement.json`；
分域最终报告为 archives/report.md、objects/report.md、native/final-audit.md、scripts/CURRENT-REPORT.md、
scripts-query/implementation-report.md、frontend/summary.md 与 gui-implementation.md、offline/report.md、
resources/README.md。对应机器验证文件也在配套 JSON 内以哈希定位。
这两份仓库文档不复制 Trainer 源码或运行载荷，不修改其他已有文档、AGENTS 或版本文件，不包含提交或推送动作。
