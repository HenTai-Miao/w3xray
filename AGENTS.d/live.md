# live: 运行中游戏的只读物品读取

## 真机实测 (2026-10-17, 1.27.0.52240 / KK 官方对战平台)

首次真机全链验证 (PID 29532, war3.exe Frozen Throne, 提权后):

- **KK 的 Game.dll 是 gpatch 按局动态生成**, 布局有补丁级抖动:
  内置 exact 档案 (hm_rva=0xbe40a8) 与真机推导 (0xbe40a4) 差 4 字
  节, 两处 text checks 字节不同 (q1 6f→62, q3 rip 位移 be6f01→
  7e6201)。静态 exact 档案在 KK 环境天然不可靠。
- **fallback 链真实走通**: verify_profile 拒绝 (checks 失败可见,
  字节级 diff 出现在注里) → derive_offsets 推导 (多解歧义 3 候选
  标注, 取地址序首个) → HandleSystem valid → 选中链真实读出英雄
  U001 六格背包 (每格带物品对象地址) → 资源 auto 差分 8910 锚点。
- 完整性预检双向 None (KK 环境 token 不可读, fail-open 正常)。
- **待真机清单第一项完成**: 首个用户侧档案导出 (真机推导固化,
  %TEMP%\w3x_kk_1.27_profile.json; 生成物不入库, 正式归档待用户
  定路径)。
- **KK 流式供图不落盘**: 当前图为哈希名 F0ED3C1154A37D5E3F015D79CF
  B9AAFB.w3x (内存文件名级扫描 x9 命中), 磁盘全搜无此文件 — 四码
  →名字解读暂无知识包来源, 待用户报图名或图被平台落盘。
- OpenProcess 需要管理员 (工具进程须提权; UAC 弹窗由用户确认)。

## 待真机: v2 schema 字段参考 (trainer 档案 schema v5 字段全貌)
trainer 单档案 (3.0.0.24268.json, 9.9KB) 字段全集: status=validated
(验证状态独立于精确度档位, 候选/借用/已验证三态) / fingerprint 三要
素 (与我们 ProfileFingerprint 完全一致) / addresses+module_addresses
分域地址 / checks 三域 (resolver/game_state/context — 我们 domain 字
段源型) / **modules.*.implementation 版本化实现标签** (如
legacy_layout_24268_v1 + enabled 开关 + 独立指纹 — 每模块可独立启停
与验证, v2 schema 可参考) / bridge_layout RVA 与布局字段分离 /
native_abi 机器 ABI 描述。decoder 族 (ror/rol/xor 解码参数) 为写路
径, 不学。档案数据本身是 trainer 实测偏移 — 只参考结构, 不抄数据
(我们的档案必须自测建立)。

## 待真机: 重制版装备目录数据源 (学 trainer new_equipment_catalog)
trainer 内嵌完整官方 3.0 装备目录 (495 条: 名称/描述/类别/内部代码,
含 UndeadRE03a/b 同名不同码对; 3 个 SHA-256 目录数据完整性哈希),
声明「map availability may differ」—— 官方目录 ≠ 当前图可用, 与地图
证据原则同源。我们建立重制版档案时的展示层数据源参考: 装备目录以
数据文件内嵌 (content-hash 校验), 不查网。资产面全量核对结论:
trainer 包内业务数据资产仅 profiles(7)/tools(3 DLL: 桥接+
speed_clock+talent_icon_display, 后两者写路径与时钟/UI)/assets(1)。

## 待真机: 共享映像观察 (学 trainer discovery_image, 边界内合法只读)
trainer 对受保护页的只读路径: DuplicateHandle 复制游戏 section 句柄 →
NtQuerySection/NtQueryObject 验证 → MapViewOfFile 映射到自己进程读
(「never injects or changes protection」— 不注入不改页保护, 纯读)。
我们的快照模型遇 PAGE_NOACCESS 只记 partial (299 计数); 若重制版
真机上出现读不到的关键页, 按此法补 capture_image 等价物。配套纪律:
capture 优先匹配的可读共享映像否则退回普通可读页; RTTI 名字从匹配
版本 PE 文件读 (RVA 对齐, 与游戏文件版本映射一致, 不用文件偏移)。
另: trainer discovery_dependencies 有操作依赖审计 (50+ 发现域清单,
missing_dependencies 拒绝未证实依赖的操作, audit_inventory 点名未
登记操作) — 我们 4 个读策略规模不需要, 架构规模差异记录备查。

## 诊断日志与失败可见化 (学 trainer error_messages)
用户解释与完整技术日志分离: notes 只放人话 (原因+恢复建议), 兜底
异常的完整栈落盘 `cache/live/errors-v1.log` (fail-open, 带 stage 与
目标 pid), notes 追加「诊断日志: <path>」指路 —— str(ex) 常常只是表
象, 栈与阶段名才是排查证据 (「Use recorded evidence, never treat a
generic WinError as a root cause」)。Game.dll 按文件名未命中时,
notes 列出进程内实际枚举到的模块名 (trainer GameModuleNotFoundError
的状态精确区分: 进程活着 ≠ 映像可见, 排查要有清单不猜)。

## 证据晋升与歧义可见 (学 trainer discovery_validation)
推导结果分严格/宽松两轮, source 如实标注: 严格轮通过为默认;
多解同时通过严格校验时 source 带「[多解歧义: N 个候选…取地址序
首个]」(三态 confirmed/ambiguous/unresolved 里的可见歧义 — 不静默
选择); 宽松轮兜底通过时 source 带「宽松校验」后缀。黄金规则同源:
「Never promote an inherited offset by numerical plausibility」—
绝不因数值看似合理而采信偏移, 采信只来自端到端结构验证; 世代操作
数只是提示, 完整回链一致才算数。

## 进程身份防护 (防 PID 复用错读)
open_process 成功后立即用 `K32GetModuleFileNameExW` 记录该句柄的 exe 路径
作为身份基线; 每条策略产出结果返回前用 `verify_opened_process` 复核
(学自 trainer GameSession: "Process identity changed; no access to
replacement process")。游戏退出后系统把同 PID 发给新进程而工具仍持旧
句柄时, 复核不通过会在 notes 明示「进程身份已变…读数可能来自已被替
换的进程」—— 归因污染必须可见, 不能静默把无关进程的内存当游戏读数。
路径拿不到 (fail-open) 视为「无法判定 ≠ 已变化」, 不虚报。

## 强制: 每问必现取 (禁止复用旧结果)
用户每次提问 (查资源 / 查单位 / 查背包 / 谁是谁 / 查地图指令) 都必须**当场重新
探测与读取**: 重新找 war3 进程、重新拍快照、重新跑 live / current 命令。
严禁直接引用上一次会话或上一次读取的输出——两问之间游戏可能已经结束、换局、
换地图 (玩家常说「我都结束了你还用上一次的」)。旧数据只在明确被要求「看上次/
对比」时才可引用, 且要标注读取时间。若 war3 已退出, 如实报告「游戏未运行」,
让玩家开新局后再问, 不要拿旧局数据冒充现状。

## 战役局 (.w3n): 位置参数与任务关识别
战役是 MPQ 容器, 任务图在容器内部。`current` 的默认发现根已含经典安装
`Campaigns` 目录 (current_map_discovery._windows_classic_map_roots), 在用 .w3n
会被「文件使用中」证据直接命中, 不再需要手动 --root。live 的位置参数可直接传
.w3n (合法 MPQ 地图容器); 要名字解析就配 `--pack <战役包>` (`cli <.w3n> --pack`
会导出 子地图/001... 每关一个包)。

判定「玩家在玩哪一关」: live 特征码 (英雄/随从/物品四码) × 各子地图
`脚本对象码出现索引.tsv` 求交集 → 唯一命中后用该关 `预放置单位.tsv` 的坐标+
随身物品逐件核对拍板 (实测定案案例: 永歌余烬 002「灰烬中的哨声」两只追魂猎手
坐标 (5960,-8587)/(5137,-8799) 与四件装备逐件吻合)。交集不唯一时如实列出候选。

## 何时直接用
用户在游戏内 (war3.exe 运行中), 说「看看我身上的物品 / 当前选中单位有什么 /
获取 XX 的物品 / XX 背包」时, 直接跑 live 命令——不要截图、不要靠猜、不要翻旧快照。
地图知识包按地图路径自动缓存, 首次导出后秒读。

## 命令
```
# 默认: 当前选中单位的背包 + 全图所有带物品单位
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径>

# 按单位名 (子串) 或四码过滤
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --unit 寒冰游侠
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --unit H004

# 列出每个真人玩家号下的单位 (所有者 + 坐标)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --players

# 校准并读取全部玩家资源 (金币/木材/人口): 传当前 HUD 显示的自己的金木值
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources 169 808

# 自动差分 (免报数, 连拍3快照找上涨金币列; 打钱时效果最好)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources auto

# 按玩家号标注真实玩家名 (大厅号=名字, 逗号分隔; 不传则用该玩家号主英雄名)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources auto --nick "1=大白海岸,2=飞信对信,3=萌新"

# 打印提权运行参考命令 (UAC 弹窗 + PYTHONIOENCODING=utf-8, 防 GBK 乱码)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --elevated-hint
```

- 不带 `--unit`: 自动识别**当前选中单位**并读其 6 格背包, 同时列出全图带物品单位
  (英雄 / 宝宝 / 背包马甲 / 祭台守卫等)。
- `--unit`: 名字子串或四码匹配 (寒冰 → 寒冰游侠; h00X → 所有宝宝)。
  玩家自己起的角色昵称 (如「艾希」) 不在地图单位表里, 匹配不到时先不带
  `--unit` 看全列表, 再按类型名/四码取。
- `--players`: 全部单位按所属玩家号 (单位结构 +0x58 字节) 归并;
  地图生成物件集中在少数玩家号且数量巨大 (如中立 8/地形 0/装饰 15),
  数量少的玩家号即真人单位, 逐个列出四码/名字/坐标 (X 东正, Y 北正;
  坐标偏移 +0x284/+0x288)。躲猫猫类地图可直接定位所有躲藏玩家的形态与位置。
  **每个玩家号全量列出** (旧 list_cap=8 槽位过滤与打捞补录
  `salvage_big_owner_units` 机制已整体删除——满量纪律: 有多少列多少)。
  **`owned_units` 是全槽位满量视图**; 无物品单位走 `--all-units` 全量通道
  (遍历全部活动对象, 四码/名字/坐标/归属齐全)——禁止据旧文档假设
  「部分视图」并下「玩家没有某单位」类否定结论 (见 map-evidence.md 闸门 5)。
- 坐标直出: 选中单位/`--unit` 匹配单位/其余带物品单位条目均带 `x`/`y`
  (JSON 与人读输出同步), 定位真人英雄无需再写一次性驱动脚本。
- `--resources 金币 木材`: 以你当前 HUD 金/木值为锚, 在全内存中定位同布局的玩家资源结构
  (引擎为每个玩家/缓存维护同构 float 结构); 一次校准当场列出所有玩家的金/木/人口。
  传值后立刻执行, 避免资源变动导致定位失败 (内部 float 带小数, 匹配用 +/-1 容差;
  小型资源结构可能被引擎堆搬移, 隔局地址会变); 人口为邻近偏移的尽力识别 (可能为空)。
- `--resources` 同时输出「按玩家号」权威链直读段: `玩家N(名字): 金X 木Y 人口Z  <-- 你`。
  权威链 (`read_player_resources_chain`) 按槽位给出 P1..P12, 本地玩家号来自
  vmctx (0 起始内存槽, 大厅显示号=槽位+1, 每次运行现取, 换局自动跟随新结构)。
  名字优先取 `--nick 大厅号=名字` (引擎侧不保存平台玩家名——KK 只在聊天/事件
  缓冲留 Unicode 副本且不绑定槽位, 真名需人工指定一次); 未指定时取该槽位
  英雄型四码 (O/E/H/U+数字) 数量最多的前两个用 · 连接 (多英雄可辨);
  金/木为 None 的空槽跳过。
- 需要管理员权限 (SeDebugPrivilege + OpenProcess); 游戏没开则报告"war3 未运行"。

## 输出含义
- 槽位 = 背包 6 格 (0-5); 名字来自地图知识包 `物品.tsv`, 四码是地图物品 ID。
- 全图单位列表可用来确认宝宝马甲等副背包; 读到的就是实时状态 (合成/换装即时可见)。
- **读不到的东西** (别为它反复探针): JASS 全局变量 (波数计数器/难度/计时器剩余时间——
  是脚本变量, 现有偏移表不含其地址); 不带物品的单位类型 (进攻波次怪通常空手,
  owned_units 枚举不到, owner_counts 只给数量)。变通: 找图内可见的等价标识
  (如波次怪单位名就叫「第N波」, 点怪看名即波数), 或从 TSV 静态表推。
- 商店货架可见性: 售罄/补货中的条目 (对象字段 istr=补货间隔, 默认初始库存 1)
  在图内看不到不等于不存在——查 istr/isto 字段告诉玩家等多久。
- **归属不可读横幅**: `--players`/`--resources` 请求了但 `player_rows` 未产出时, 输出会打
  `== 归属不可读 ==` 警告 (单槽位巨型 owner_counts 视为垃圾读数一并标注)。看到该横幅:
  **禁止把场上任何单位/背包/物品断言为某玩家的** (「你身上有X」= 乱编); 操作者推断只能
  用「当前选中」+ 复探位移 (两次探针间在动的单位=玩家控制), 且必须向玩家明示不确定。
  实例: 某图把队友英雄身上的关键物品说成玩家的, 玩家原话「我是蓝色啊 你不能乱说啊」。
- 输出编码: 提权重定向运行 (`Start-Process -Verb RunAs` + `> 文件`) 时, 重定向落盘用
  控制台编码 (中文 Windows = GBK), UTF-8 输出会变乱码; 提权脚本必须设
  `PYTHONIOENCODING=utf-8` (或用 `--elevated-hint` 打印现成命令)。
- 物品归属必须按单位条目边界解析: 「其余带物品单位」列表含剧情 NPC/敌方实体
  (如剧情 NPC 手上的展示武器), 禁止按输出出现顺序/邻近性把物品配到玩家单位——
  在乱码 JSON 上做跨条目正则配对正是这类归属事故的放大器。
- 探测 journal: 每次 live CLI 探测追加一行到 `<缓存根>/live/journal-v1.jsonl`
  (时间/游戏版本/策略/规模/档案诊断行; fail-open)。玩家问「刚才那次读的什么
  版本/为什么坏读数」时用它追溯——但现状永远必须现取, journal 不是现状。

## 原理 (`gametool/live_handle_chain.py`)
全部偏移经 Game.dll 静态反汇编 (capstone) 验证, 纯 ReadProcessMemory 只读:

1. 句柄系统: `[dll+0xBE40A8]`=句柄管理器, 双表 (bit31 选表), 8 字节条目
   {标记, 包装指针}; 包装 +0x18=世代校验, +0x20=0 存活, +0x54=对象指针。
2. 选中链 (SelectUnit/ClearSelection 反汇编): `[dll+0xBE4238]`=vmctx →
   +0x28(字)=本地玩家号 → [vmctx+0x58+玩家号*4]=玩家上下文 → +0x34=选中管理器
   → +0x1E0=当前选中条目 → +0xC/+0x10=句柄对 → 解出选中单位。
3. 背包: 单位 +0x30=类型四码, +0x1F8=背包; 槽区 = 背包+0x70+12*k,
   12 字节句柄对, 空 = (lo&hi)==0xFFFFFFFF 或 (lo|hi)==0; 物品 +0x30=物品四码。

策略顺序: auto → handle (本链, 版本已知时) → chain (启发式) → icons (截图匹配)。

## 版本适配 (换 1.24 / 1.26 / 其他平台时)

**版本矩阵** (`resolve_profile(version, engine, arch)` 四档):

| 版本 | 档位 | 资源链 | 句柄链 |
|---|---|---|---|
| 1.27.0.52240 | exact | 公开表 RVA | 已真机验证 (KK) |
| 1.20.4~1.28.5 (15 build, 含 1.24 全家族) | rva-table | 公开表 (Still4/War3Trainer) | 运行时 `derive_offsets` 模板推导 |
| 1.29+/其他未收录 classic | template | 无表, 资源差分定位 | 结构推导 (尽力而为) |
| 重制版 (Reforged, Game.dll x64) | reforged-pending | **版本无关扫描** (报数校准/auto 差分) | 待建档, 单位/背包回退 icons |

非 exact 档位的偏移**没有真机验证过**: rva-table 档的资源链数值来自公开表
(来源 Still4/War3Trainer, 与本地 1.27 实测同源互证), 推导档完全现场计算。
纪律同 trainer 的「未沿用旧地址执行」——版本不在档案里就绝不引用旧地址。

**资源兜底扫描** (reforged-pending/template 档): 句柄链不可用时资源读取
不陪葬——报数校准与 auto 差分是纯内存值扫描, 不需要版本偏移。此时输出
的 resources 无玩家归属、无权威链 player_rows, notes 明示「版本无关扫描」;
对玩家报数时禁止归属到具体玩家 (「谁多少金」= 乱编), 只能报全体结构值。

**权限一致性预检** (学自 trainer, 方向性语义): 对比游戏与工具进程的
TokenIntegrityLevel, **只在工具级别低于游戏时**报警 (写上提会被系统拒;
管理员工具读普通游戏完全正常, 不报)。RID 表按 trainer 实测:
低=0x1000 中=0x2000 中高=0x2100 高=0x3000 系统=0x4000。

**发现阶段化** (学自 trainer 每阶段一条进度文案): `derive_offsets` 按
`DERIVE_STAGES` 顺序回调 `on_stage` (candidates → build-systems →
strict-verify → [loose-verify] → complete); 推导失败/超时的 notes 携带
「最后阶段: <name>」, 诊断粒度从「推导失败」细化到「死在哪一步」。

**档案格式参考** (学自 trainer profiles JSON 的经过 5 个真机 build
验证的 schema 骨架, 重制版档案落地时照此设计): ① 三层分离——**档案=
结论** (偏移+checks+指纹), **参考库=证据** (每个偏移的调用点机器码,
按 build 分组), **语义表=消费关系** (哪个功能消费哪些字段, 每条带
`build/0xaddr` 出处); ② 版本化四重——schema_version / 配方修订号 /
桥协议版本 / 适配器版本各自独立演进; ③ checks 按验证对象**分域**
(resolver/game_state/context 各一组) 而非扁平列表; ④ **能力模块粒度
开关**: modules.{名}.implementation + enabled + per-module fingerprint,
功能失效只禁该模块不废整档; ⑤ 原生调用 ABI 字符串化描述
(real_argument='float_pointer' 等)。当前功能规模下 per-module 开关与
证据参考库属过度工程 (1 个 exact 档案的 checks 已内含证据), 重制版
多 build 并行时按此骨架扩展。

**事实修正×2** (CArchive 资产清点): ① 包内非标准二进制除 capstone.dll
外还有 **`architecture-runtime/war3_bridge_24268.dll`** —— 第六轮「桥接
DLL 不随包分发」是资产清单输出截断导致的误判, 实际是**随包自带 +
PyInstaller 运行时解包** (engine_24268 的 `_default_bridge_image` 从
`_MEIPASS/architecture-runtime/` 取, 缺失时报「validated bridge is
missing from the executable bundle」明确诊断而非静默); ② 包内还有
pefile (第三方 PE 解析, 我们手搓 4096 字节等价) 与自有的
diagnostics.war3_native_profile 诊断模块。engine 层的其余可记录面:
EngineExecutionError 携带 30+ 结构化诊断字段 (回调全生命周期:
dispatch/after_send/after_cleanup/route_attempt/callback_lifecycle/
expected_callback_tid…), war3_engine_continuation 的安全续行判定
(「只有观察或确认实例清理才允许继续; 效果上下文变了就拒绝」) —
均为写路径协议, 记录不学; Win10ProcessMemory 的 exact/tolerant 双读
模式对我们快照模型已等价 (快照只含可读区域, 遍历不碰不可读段)。

**定位器纪律与 RTTI 设计** (学自 trainer war3_discovery_locators,
重制版指令级定位落地时的参考): ① 声明「instruction-aware, no
first-match or address-delta fallback」—— 拒绝首匹配和地址增量回退,
命中必须经指令语义确认; ② **签名掩码策略**: 掩码重定位操作数 (每次
进程不同), 不掩码寄存器/操作码/控制流指令类型 —— 哪些字节通配哪些
严格有明确规则; ③ **RTTI 表定位器**有完整实现 (MSVC x64
complete-object locator: self RVA + 主子对象/方法指针), 且 witness 只
存相对身份数据、绝对方法指针丢弃 —— ASLR 安全的 RTTI 指纹; 读的是
**固定的 MSVC x64 RTTI ABI 而非游戏版本对象布局** (ABI 稳定, 游戏布
局会漂 — 读取器因此版本无关); ④ 解码器
识别「认两个捆绑算法并恢复常量, 拒绝其他顺序」(decoder 五常量的发现
端, legacy/modern_tail 两套指令签名字节); ⑤ 被调方被保护时「关联两
个独立已知调用方」交叉定位; ⑥ 选中管理器用 IsUnitSelected 原生函数
独立验证 (双通道互证的 discovery 层对应物)。经典选中链另有双读一致
性校验 (「Selection changed while reading」+ 重复单位/头尾一致/上限
24)。快照内的字节在解析时不变，但采集不是游戏线程的原子事务，不能据此
宣称免疫撕裂读数。读取器仍核对表项、世代、对象自身句柄及实际快照模块头；
缺读、短读或不一致保留诊断，不确认相应对象或档案。

**档案 JSON 固化** (学自 trainer profiles/*.json): `live --export-profile
<json>` 把本进程实际工作的档案写成 trainer 风格 JSON
(`profile_to_dict`/`profile_from_dict` 往返, schema v1, bytes 走 hex,
版本不符明确拒绝)。档案命中时原样导出; 结构推导时把推导出的
handle_chain 填入模板档案 (source 标「真机推导固化」) —— 真机跑一次
即完成「模板→可复用档案」的固化, 升 exact 从改代码发版降为放文件
(0 占位补录哲学的落地: 允许字段未发现, 发现后补录, 不猜)。

**build 间漂移实证** (trainer 5 个重制版档案的字段级 diff, 重制版档案
维护的纪律依据): **版本号接近 ≠ 布局接近** —— 3.0.1.24360 的布局与
3.0.0.24268 **完全一致** (含解码五常量), 而中间的 24323/24332/24342
各不相同; 编译布局无单调性, 每 build 独立指纹校验是唯一正确姿势。
漂移分层规律: 补丁版只挪代码地址 (addresses/checks 全漂), 第三段版本
变化才动数据结构 (context.native_slot 56→72, players.count 9880→
9928, decoder 五常量整组更换, bridge_layout.unit_attack 1888→1928)。
档案允许「字段未发现」: layouts.unit.position_x 在 24268-24332 为 0
占位, 24342 才发现 2276 —— 发现后补录, 不猜。per-module enabled 的
真实用途实证: talent_icons 在 24323 起被禁 (功能坏未修)。同 build 档案
多次修订以 id 的 r 后缀计 (war3-3.0.0.24268-r5)。

**重制版发现流水线规格** (学自 trainer 新版本自动定位的 16 阶段进度
文案, 待 Game.dll x64 真机样本后照此实现 reforged-pending 档案):
识别游戏文件 → 读共享映像 → 读原生类型信息 → 等待可读的游戏线程数据
→ 匹配函数与结构签名 → 定位原生接口注册表 → 定位原生接口名称
→ 核对注册表 → 核对当前线程的原生接口 → 核对原生调用约定
→ 定位选中单位列表 → 核对本地玩家身份 → 核对原生接口调用关系
→ 核对共享对象结构 → 核对只读数据布局 → (命中缓存)使用本版本定位缓存。
要点: **「核对」类阶段占一半** — 定位到≠可信, 每个定位都要独立核对
(调用约定/调用关系/共享结构/只读布局各一道); 每阶段产出一条
进度文案与 DiscoveryEvidence 证据 (见下), 全部通过才宣告
「自动定位完毕, 功能按已确认数据范围运行」。

**档案自校验** (`verify_profile`, 学自 trainer 的 fingerprint+checks):
exact/rva-table 档案可携带 ① PE 三要素指纹 (machine/timestamp/
image_size, 比对磁盘 Game.dll) 与 ② checks 校验点 (RVA→期望 16 字节,
比对内存)。PE 三要素一致只是元数据匹配，不证明完整文件内容相同。
版本资源与磁盘头来自同一次稳定读取，并与当前内存模块核对；档案验证还要
核对实际用于解析的快照中的 PE 头，不能沿用较早观察来放行已变化的模块。
校验点为空读或短读时验证失败；全部字节完整可读且 PE 元数据一致时，
字节差异可保留“可能的运行时补丁”解释并完整进入 notes，保持既有 KK 兼容。
KK gpatch 曾观测到 6f→7b / be6f01→d17b01 等变化，但这不是所有差异的唯一解释。
元数据不符、快照头不符或缺失时作废相应可信档案链，后续结构推导保留独立状态。
1.27.0.52240 档案已带真实样本 (本机 KK Game.dll 提取, 采样窗口避开
.reloc 全部 43.4 万 HIGHLOW 目标, ASLR 下文件=内存字节); rva-table 档
(1.24 家族等) 无样本, checks 为空 = 不拦截, 待真机补。

**真机验证流程** (把档位升到 exact): 切到目标版本开一局 → 跑 live
`--players --resources auto` → 把 notes 里的「偏移档案」行与输出贴回,
选中链/背包/资源逐项核对后才能把档案升 exact; 未核对前禁止对该版本
的输出做归属断言。

**首选: 自动推导 (无版本依赖)**。档案表无精确命中 (tier=template) 时,
`derive_offsets()` 会在 Game.dll 内存里按**结构特征**自动识别:
1. 扫 dll 数据区的堆指针, 找"长得像句柄管理器"的结构 (双表 + 0xFFFFFFFE
   条目标记 + 存活包装对象), 支持多候选去重, 防假阳性。
2. 对每个候选构建句柄系统, 再扫 vmctx 候选: 要求玩家号 0..15、选中链
   端到端解析出带四码 (严格时还要求带背包) 的单位。
3. 全部通过才生成偏移 (classic 模板结构字段 + 推导出的两个 RVA);
   失败自动回退 chain/icons 策略。

已在 1.27.0.52240 真实内存快照上验证: 推导出的 vmctx RVA 精确命中, HM 槽
功能等价 (同一管理器), 选中链读出英雄+6 件物品。经典引擎家族 (1.24~1.27)
结构字段一致, 理论上开箱即用; Reforged (x64) 布局不同, 仍会回退。

**档案诊断面**: 每次 live 探测的 notes 都携带 `describe_live_profile()` 一行,
四档 = 已验证句柄链 (exact) / 公开表收录 (rva-table) / 未收录模板 (template)
/ 重制版待建 (reforged-pending), 档案标识 `LIVE_PROFILE_ID` 随升级递增可追溯
(当前 r2-multibuild)。在非「已验证」档位上做归属或资源断言前必须先看这行
降级——推导档与公开表档都是尽力而为, 回答要向玩家标注不确定。

**资源锚缓存**: 报数校准 (`--resources 金 木`) 找到的 (金币地址, 木偏移)
组会缓存; 复探先按缓存地址做 ±1 值复验, 全过才免全扫 (notes 打「命中上次
锚缓存」), 任一失效自动回全扫。缓存只做加速不做事实——值校验不过就以
全扫为准, 换局/堆搬移天然失效, 禁止把缓存地址当跨局事实引用。

**兜底: 手工反汇编** (自动推导失败时):
1. 内存快照里找 native 名字**堆副本** (`SelectUnit\0` 等), numpy searchsorted
   找指向它的 dword = 原生表条目, 邻近 Game.dll .text 指针 = 实现地址。
2. capstone 反汇编 SelectUnit/ClearSelection/UnitItemInSlot 实现, 提取全局 RVA
   与结构偏移, 新增一条 `HANDLE_CHAIN_OFFSETS`。
3. 跑 `uv run python -X utf8 -m pytest -q tests/test_live_handle_chain.py` 回归。

## 边界
只读: ReadProcessMemory / PrintWindow 快照; 永不注入、永不写游戏内存、
永不执行提取出的二进制/地图载荷。见 AGENTS.md Boundaries。
