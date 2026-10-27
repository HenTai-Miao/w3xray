> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# 六个本地 Warcraft III 工具的横向版本比较

六标本的结构和静态行为已逐项对齐。三个 Python 标本存在可证明的代码迁移，但没有执行证据能把任何一个下载程序认证为当前可用的 GameXRay 只读组件。原生大象与 new.exe 的相似动作按概念比较，固定地址、函数标签和支持版本不能互换。

本分卷只在 `version-comparison/` 写分析文件；没有运行 EXE、DLL、目标 Python/JS、游戏 hook 或游戏进程，没有提权或修改仓库。每个来源文件和每项未确认边界保存在 `comparison.json`。六原件完整 SHA-256/字节数末轮复核均保持与最初输入一致。

## 标本与覆盖

| ID | 标本 | 类型 | 原报告记录单位 |
|---|---|---|---|
| 1 | War3ReforgedHotkeys-v2.0.0.exe | x64 Python3.12/PyInstaller | 38功能族 |
| 2 | War3ReforgedTrainer-v1.0.19-JianYX-v2.6.4-R8.exe | x64 Python3.12/PyInstaller | 37功能族 |
| 3 | War3ReforgedTrainer-v2.1.20-213F512FD188.exe | x64 Python3.12/PyInstaller | 1009跨层审计记录 |
| 4 | 大象1.27修改器.exe | x86原生 | 82控件/输入/辅助记录 |
| 5 | 魔兽争霸3修改器_new.exe | x86原生 | 18功能组+69字段 |
| 6 | war3 1.24E修改器V1.4by大象.exe | x86原生 | 28配置动作 |

不同计量单位不能合计成产品功能数。target-3 的同一功能会出现在UI、服务、协议及DLL多层；target-4也明确保留未完成效果链的控件。

独立从原始marshal只解数据、计算局部实现指纹，覆盖 **5063个第一方代码occurrence、448684条原始指令**。与三agent原始清单的path、SHA、长度、qualname、names和local ABI全部一致，`coverage-crosscheck.json accepted=true`。功能报告的代码身份引用另逐条复核于`feature-evidence-qa.json`。这证明身份和解码覆盖，不替代完整业务或运行验证。

## 三个Python标本

| 维度 | Hotkeys2.0.0 | Trainer1.0.19 R8 | Trainer2.1.20 |
|---|---|---|---|
| 应用版本、游戏构建与档案 | 应用2.0.0；两个x64精确指纹档案3.0.0.24268/3.0.1.24323。schema_version=1、bridge_protocol=4。作者game_effect分别not_run、physical_key_testing_pending。legacy fallback存在不证明经典版兼容。 | 应用1.0.19，文件名另带JianYX-v2.6.4-R8；无profiles/*.json游戏构建矩阵。NATIVE_PROFILE_ID=3736663128是1689个native排序表的身份，不能当游戏版本。 | 应用2.1.20；七个x64 exact构建24268/24323/24332/24342/24360/24365/24371，均3.0.*。schema5、bridge_profile_version3；status=validated是包内生产者声明。仅24268启用talent_icons，24365还禁用stat_details且speed/effective_interval与fog_recovery为0。unknown-build发现的七条先验source_digest均过期，默认借用发现路径受闸阻断；exact提前返回不受此问题影响。 |
| 封装与真实界面 | x64 PyInstaller/CPython3.12；7第一方模块278代码对象。Tk/ttk三页、42个格位编辑；不是42项游戏能力。 | x64 PyInstaller/CPython3.12；单trainer主脚本加6模块，共1112代码对象。Tk界面，50项快捷键声明/绑定及53个CLI参数声明。 | x64 PyInstaller/CPython3.12；175 PYZ第一方模块加1 CArchive入口记录，3673代码对象。默认Svelte5/WebView2；Tk及辅助弹窗仍保留。13主面板、67显式RPC、68快捷键；1009是跨UI/服务/协议/DLL的分层审计记录，不是1009个独立按钮。 |
| 选中、对象与全量范围 | 选择查询服务热键上下文；CreateGroup→GroupEnumUnitsSelected→FirstOfGroup→DestroyGroup，并非地图全部单位枚举。 | 当前/多选单位快照，完整handle/owner/unit身份、HP/MP/XY/字段、六格背包与技能；活跃入口前置persistent native helper。不能据保留扫描器声称全场单位读取。 | indexed注册表、typed UnitRef/ItemRef与selection快照；绑定session/map epoch拒绝陈旧对象，扩展背包/九槽装备/天赋和字段详情可读。selection协议容量24，不是全场完整性证明；完整证据须保留来源/限制。 |
| 玩家资源 | 未识别资源读取/修改产品入口；工具职责为热键/输入与上下文。 | 资源组扫描/缓存、金币木材人口读取及修改/增量/锁定；现成活动读可能前置hook。 | 资源组/本地玩家与source/address；金币木材人口读写、锁定；金矿按选中/世界读改及逐矿状态。native goldmine固定容量4096，truncated非零时decoder拒绝成功。 |
| 实际读写/执行边界 | ready/context/selection/readback均走远端装载/SEC_IMAGE、写远端命令、remote thread/WindowsHook；读命名不表示RPM-only。只可独立重做identity/TLS/registry等被动准备段。 | 旧persistent native init/hook是当前选择等读取前置；`普通读取版`仅产品模式，不是全局禁写保证。外部RPM类与业务native getter须分开。 | 语义read-query有白名单，transport仍分配/写入远端、装载/映射DLL并回调游戏线程。39 production固定操作的marker/query均与DLL相符；3diagnostic缺marker/query。默认managed session拒绝旧helper路径。 |
| 进程选择、身份与多实例 | 窗口/前台guard+可选目标PID；GUI没有多实例选择器，多个可用实例会选择。缓存identity含PID、创建时间、base和PE三元指纹。 | 可显式PID；无PID默认matches[0]，多个客户端不拒猜。窗口失效检查不等于opened exe/创建时间session复核。 | 默认发现多个不同PID时拒猜；显式PID检查exe/window。GameSession identity含PID/创建时间/base/fingerprint/profile_digest，epoch按窗口/地图/context失效。verify_opened_process仅在_ACTIVE_SESSION存在时比PID/创建时间，不是所有legacy内存路径的全局保证。 |
| 离线目录、数据模型与文件能力 | 热键方案、配置校验/迁移/本地化；没有对象ID数据库或地图档案解析产品入口。 | 1950条固定ID目录=物品283/技能833/单位834；753技能字段与20物品字段元数据。没有本次modern新增的存码/存档字段/定义补齐服务。 | ID底表逐对象与旧版完全相同；增加description_zh/en/source/partial及外接描述表，不扩大1950对象搜索目录。753技能字段/20物品字段完整模块局部实现相同。另有325新装备、英雄技能、文本存码候选、.w3v/.w3z缓存字段、data-only套装导入导出、独立新副本的地图/战役定义补齐。CASC模块仅静态catalog，没有CASC存储访问实现。 |
| 诊断、任务与恢复 | 状态JSON、异常日志、Tk队列、清理不确定状态quarantine；固定invalid备份名可能覆盖前次，unknown扩展字段不往返保留。 | 旧日志PID+时间、latest/归档；pending/fatal不重派、字段写失败尝试精确回滚并禁写到重连。日志命名旧开'w'，不等于多个工具会话无碰撞。 | 日志新增requested/actual PID、HWND、trainer PID/parent/thread/UUID与'x'排他创建；session/profile/source/hash/阶段独立。可取消定义任务、逐文件/字段状态、已完成但刷新失败与未知结果分离，拒绝不确定自动重放。 |
| 组件安装、网络、产品授权与权限 | 已解码第一方未见账号/激活/HTTP更新路径；本地命名mutex不等于Windows自启动。未建立第一方再分发许可。 | 第一方未识别账号/激活/HTTP升级；SeDebugPrivilege是Windows进程权限，与产品付费授权不同。 | 前端仅modulepreload fetch，默认本地页面，dev-url可外部指定；缺WebView2时有核哈希并运行bootstrapper安装路径，该组件可联网。所审UI+前端未识别产品激活/付费/自动升级控制流，不覆盖第三方/native任意行为。 |
| 可见上限与完整性边界 | hotkey事务16块是wire容量；native表8192节点、字符串256字节、legacy局部4MiB与稳定时间窗是其它边界。不能移植为GameXRay地图/对象静默上限。 | selection-manager遍历最多64、批量selected最多12；快照能力数超过4096转诊断；协议每批16操作，另有region/合理值过滤。容量、完整性拒绝和任意扫描guard分开；不能移为GameXRay静默上限。 | Web三目录[:200]有matchCount但只交付200行；档案files[:100]无total/omitted。协议24 selected、4096金矿、100000目录/世界targets、8192native nodes等，未证明均为游戏真实bound。文本/存档扫描文件数与字节数也有限制。 |

## 三个经典原生标本

| 维度 | 大象1.27 | 修改器_new | 大象1.24E |
|---|---|---|---|
| 应用版本、游戏构建与档案 | 产品窗口标题声明1.27a；PE FileVersion1.0.0.0是易语言程序元数据。硬编码Game.dll/War3Plugin.dll和偏移，未证明构建指纹闸；不可称1.27自动适配。 | 11个精确版本字符串分支：1.20.4.6074、1.21.0.6263、1.22.0.6328、1.23.0.6352、1.24.0.6372、1.24.1.6374、1.24.2.6378、1.24.3.6384、1.24.4.6387、1.25.1.6397、1.26.0.6401。没有1.27分支；未知INI非空路径仍跳过正常setup，不能当通用版本支持。 | About声明1.24E(1.24.4.6387)，修改器标签V1.4；CE/VCL框架版本1.8.0.0/Product1.2不是游戏版本。主AA固定Game.dll绑定且注释要求其它版本重新绑定；28动作的expected-byte patch记录全空，通用guard本标本不校验游戏字节。 |
| 封装与真实界面 | x86易语言；2表单137序列化控件记录、22真实声明事件，60checkbox。82项功能记录含输入及辅助控件，不等于82项已证游戏效果。 | x86易语言UPX静态解包；1真实表单35控件对象、15事件。18功能组和69字段表；通用打印/数据库模板是运行库资源。 | x86 Delphi/VCL Cheat Engine Trainer；28配置动作、37子记录、2 AA脚本、3自定义组件。原生加载器与overlay配置均有边界证据。 |
| 选中、对象与全量范围 | 恢复了修改分支与进程/内存类路径，未恢复可直接接入的只读选择/全场数据合同。 | 从selection manager编码count遍历整个当前选中集合，工具列表再选一条；69字段包括57常规/技能字段与6槽各名称/数量。所谓名称实际是反序FourCC。不是所有地图单位枚举。 | AA借GroupEnumUnitsSelected+FirstOfGroup取一个单位，主要用于动作；没有只读展示selected或全场单位的数据接口。 |
| 玩家资源 | 金钱/木材等UI修改项有WPM路径；不能把写入实现推成完整资源只读表。 | 12玩家四资源当前值（金币/木材/当前人口/最大人口），WPM修改和300ms timer持续锁定；双击取消锁。 | 资源动作对12玩家金币木材都写1,000,000；是全玩家赋值，不是资源读取。 |
| 单位/英雄/技能/物品修改及地图动作 | 60checkbox中53项证明控件getter到WPM，2项无ID使用/零声明事件，4项完整效果未定；另无CD无蓝耗声明event实际读取‘不会失败’checkbox，是接线失配。全屏腐臭蜂群getter只返回checked状态，没有证明动作调用；不能称60项全部实现。 | 4资源写锁定与69字段目标编辑/写入；没有由通用memory helper库方法推导隐藏产品功能。 | 28配置动作含初始化、26有效selector及NoDefeat等；英雄/传送/复制/库存/技能/8光环/4被动/六固定装备/全屏效果。另selector17仅ret、注释未完成，不计可用显示文本。 |
| 实际读写/执行边界 | 已证明OpenProcess/VirtualAllocEx/WriteProcessMemory可达分支与77处间接receiver绑定；22真实声明callback中15处有静态WPM可达路径。序列事件地址计算未知已关闭，生成载荷完整语义仍部分未知。 | 当前读值经RPM，修改经WPM，Timer实际循环写锁定项；读与写UI都在同一原生修改器中。未把linked codewrite/protect等通用方法说成可达产品功能。 | AA安装游戏hook/远程alloc/代码写入并执行固定native动作；manifest requiresAdministrator。本审计没有运行。 |
| 进程选择、身份与多实例 | 实现进程枚举及War3.exe名称，未证明安全显式PID/多实例冲突策略。 | FindWindowA('Warcraft III','Warcraft III')取一个窗口→PID→Game.dll module snapshot；未见显式PID或opened身份复验。 | Process32First/Next按war3.exe名称找到首匹配即break；无PID选择/多实例拒猜。 |
| 组件安装、网络、产品授权与权限 | UI声明免费；未证明产品授权协议或应用网络endpoint。网络imports存在，只可作库证据。SeDebugPrivilege存在。 | 作者HyperLinker的ShellExecuteA打开URL有实际静态链；不是自动更新或授权交换。未访问链接。 | About有CE主页文本但configured_web_action=False；manifest requireAdministrator。VCL通用网络单元不建立自动联网/授权功能。 |
| 可见上限与完整性边界 | 137控件/22序列事件完整，原215936未解码字节逐区间分类后仍117164字节code/data不透明；候选代码不提升为已证语义。53控件getter-WPM链不能推出全部60checkbox效果。 | 选择集合按当前count完整遍历；69字段是固定UI合同而非完整游戏结构。11版本分支只证明代码存在，未证明当代环境可运行。 | overlay37子记录/28动作完整至EOF；动作通常取单个FirstOfGroup，12玩家循环/六库存格/固定光环清单均是特定操作合同，不是全图解析证明。 |

## 有证据的新旧关系

- **retained_local_implementations**：544共享局部hash组；618旧代码occurrence与630新occurrence命中。许多monolith方法迁到backend/facades/legacy adapter/GUI。 出处：`version-comparison/code-comparison.json`。 限制：函数/class/lambda重复均逐occurrence保留；不是618项独立功能或全程序等价。
- **shared_transport**：26共享局部hash组，27旧/30新occurrence；包括initialize_mapped_imports/diagnose_mapped_loader/remote_thread_call等。 出处：`version-comparison/code-comparison.json`。 限制：仅据此证明实现相同；应用路由和全局bindings另审，不能把该transport纳入RPM-only路径。
- **field_tables_retained**：753技能字段与20物品字段模块保持局部实现/常量；1950基础ID数据逐对象相同。新增描述数据和schema，不扩大对象搜索目录。 出处：`version-comparison/data-contract-comparison.json`。
- **composition_changed**：单脚本+六模块拆为backend、domain、facades、session、profiles、protocols、多个UI层。Web默认，Tk保留；明确PID/创建时间/epoch/source contract更丰富。 出处：`target-2/coverage-ledger.json`、`target-3/coverage.json`、`target-3/scopes/services/README.md`。
- **observed_additions**：新增观察到WebView2/RPC、批量单位编辑、扩展背包/九槽装备/天赋及方案、RPG存码候选、.w3v/.w3z字段、独立新副本定义补齐、游戏速度/地形/金矿等模块。 出处：`target-2/features.json`、`target-3/scopes/ui/README.md`、`target-3/scopes/services/README.md`。 限制：是两个给定标本的静态差异；不追溯所有中间发行版首次出现时间。
- **retired_paths_not_features**：旧native helper代码仍在新backend，但默认managed-session拒绝，旧DLL不在包。OCR/physical screenshot入口在两版都直接抛错；不能把残留辅助函数称可用OCR。 出处：`target-2/features.json#ocr_disabled`、`target-3/scopes/services/README.md`。
- **web_regressions**：Web预热按钮把prewarm_elephant送到不接受该action的通用router；实时英雄按钮受files.length>0隐藏条件；三目录200行、档案100文件切片。 出处：`target-3/scopes/ui/README.md`。 限制：静态路径结论，未实际运行UI。

局部指纹同时比较opcode、所有递归常量、names/varnames/closure、ABI/flags、异常表；仅排除源码路径/行号和函数自身命名以识别搬移。`co_code`相同而常量变化会判变化。示例：`war3_id_catalog.<module>`和`search_id_entries`的co_code本身可相同，完整局部指纹仍不同。

旧→新544组匹配涉及618旧/630新occurrence；hotkeys→新trainer26组涉及27旧/30新occurrence；hotkeys→旧trainer仅7组，主要是RPM资源关闭、u64读取和简单类型/闭包。所有未匹配ID完整保留在`code-comparison.json`，没有强行归为移除功能。

## 应避免的等价推断

- APP_VERSION、FileVersion、游戏版本、profile schema/adapter版本、native排序表ID和各wire魔数是不同命名空间。
- hotkey bridge_protocol4和trainer bridge_profile_version3没有可排序的新旧关系。
- x64游戏classic图形/菜单名称不等于经典x861.24/1.27二进制兼容；七profile全部machine0x8664。
- 普通读取版/normal与read_query标签描述业务/显示模式，不是无远程写入或原生执行承诺。
- 所有当前选中单位不等于地图全部单位；FirstOfGroup单个目标不等于多选完整展示。
- feature记录、字段、按钮、协议操作、代码对象与已证游戏效果不是同一计量单位，六报告计数不可直接求和作功能排行榜。
- 完整字节/反汇编覆盖不等于完整动态可达性、原始源码恢复或实机branch coverage。
- 同名函数/控件/AA标签不建立语义等价；未匹配实现保留unknown/noncomparable。

## unknown ledger

| ID / 状态 | 未确认的问题及后果 |
|---|---|
| all_runtime / unobserved | Can the original tools safely launch and work in the user's present game/session? No target EXE, DLL, bytecode, JS, hook, input or game process was executed/accessed by this audit. No operational recommendation or tested-compatibility badge follows from a version string/profile. |
| function_environment / noncomparable_external_bindings | Do equal local bodies produce equal whole-program behavior? Self methods, globals/imports, profiles, native handlers, environment and call reachability can differ. Code groups establish local implementation migration only; unmatched IDs stay unknown/refactored rather than removed. |
| hotkeys_game_save / unknown | Where and for how long does save_hotkeys persist game bindings? Package Python does not establish final game-side persistence path or restoration on exit. Disabled/paused is not claimed to undo or stop the native override. |
| hotkeys_legacy / unknown | Which older builds work through legacy fallback? Fallback code is not a matching per-build validation or runtime test. Only two explicit x64 profile declarations are enumerated; no classic support assertion. |
| legacy_trainer_builds / unknown | Which exact game builds does the repaired R8 trainer support? Native table PROFILE_ID does not encode a supported-build matrix. Do not equate source comment v2.0/v2.6.4/R8 or product1.0.19 with game compatibility. |
| modern_unknown_build_discovery / static_blocker | Does unknown-build discovery initialize using bundled reference data? All seven references carry digests matching profiles before four layouts.item fields were added, and fail the current canonical digest gate. Automatic support for arbitrary newer builds is not established; exact-profile early path is separate. |
| modern_three_diagnostics / missing_native_counterpart | Are talent_probe/equipment_probe/cooldown_probe native diagnostic entrypoints available? No matching marker/query export in bundled native bridge; other production markers match. Do not count these definitions as available product operations. |
| modern_capacity / unproved_game_bounds | Do wire/list/traversal limits cover every encoded object? MAX_SELECTED/objects/strings/nodes/request and frontend slices have different roles; no global proof converts all to actual game bounds. Full-coverage GameXRay implementations must preserve full sources/counts/diagnostics and discard arbitrary silent ceilings. |
| native4_effects / partial_semantic_recovery_after_event_closure | Do all serialized controls reach the claimed game effect? 137 controls and 22 declared events are complete; 60 checkboxes comprise 53 getter-to-WPM chains, 2 without ID use/zero events, 4 full effect paths unresolved, and 1 no-CD/no-mana callback that reads the no-defeat checkbox. 15/22 callbacks have static WPM reachability; 117164 prior undecoded bytes remain opaque and generated payload semantics remain partial. The serialized-event address-calculation unknown is closed. UI ownership, actual getter input, command submission and gameplay effect remain separate. |
| native5_unknown_config / static_path_bypasses_setup | Can config.ini enable unknown builds? Both empty/nonempty unknown-version branches return through cleanup, bypassing normal setup; prior status can remain optimistic. No generic custom-version support claim. |
| native6_bindings / declaration_only | Do fixed Game.dll labels match a particular 1.24E runtime? No matching Game.dll was analyzed; configured expected-byte patches are empty; AA symbols alone do not validate callee identity. AA call names/parameters are intended behavior; do not assert actual memory writes succeeded or exact runtime compatibility. |
| native_cross_compilation / semantic_concept_only | Are similarly named elephant actions the same implementation? Distinct frameworks/ABIs, game builds, bindings and unresolved native effects; no common code identity established. Compare effect families only; do not infer copied code, compatible offsets, or function equivalence. |
| license_network / bounded_evidence | Are licensing, authenticity and all possible network effects established? First-party negative searches have defined scope; generic imports/linked libraries and component installers differ from product auth/update. No broad never-network/authenticity/redistribution-rights claim is made. |

## 与GameXRay整合时的意义

可以独立参考的是本地数据解析、字段及来源模型、明确PID/创建时间/epoch、typed对象身份、完整候选与失败诊断、文件来源稳定性、GUI过时响应拒绝、可取消后台工作、逐记录报告、数据方案和原子保存。GameXRay现有/待增/必须被动重做的逐功能结论由`project-fit/`现源对账表承担，本分卷不把外部实现直接导入项目。

native getter、read命名、普通读取版标签或read-query白名单都不足以通过只读边界；现成bridge/transport、游戏写入、修改输入与地图定义副本改写是独立效果。字段/目录/扫描器中的任意上限也不符合GameXRay默认全量规则，必须从编码记录与完整诊断重新建立覆盖。

全量功能来源：`target-1/features.json`、`target-2/features.json`、`target-3/features.json`、`target-4/features.json`、`target-5/features.json`、`target-6/features.json`。`feature-registry.json`保留每一原报告ID、标签、状态、限制与来源；`comparison.json`为每张交叉表cell保留证据文件。
