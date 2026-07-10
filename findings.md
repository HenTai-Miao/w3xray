# 发现 / 研究记录

## MPQ 格式（WC3 .w3x）
- 文件头：`HM3W`(4) + unknown(4) + 地图名(以\0结尾) + flags(4) + maxplayers(4)，之后对齐到 512，再是 MPQ。
- 本测试地图 MPQ 偏移 = 512。
- MPQ Header v0：magic `MPQ\x1a`, headerSize, archiveSize, formatVersion(0), sectorSizeShift, hashTablePos, blockTablePos, hashTableCount, blockTableCount。
- 扇区大小 = 512 << sectorSizeShift。本地图 shift=3 → 4096。

## 已验证（测试地图 杂交版1.00d）
- block flags：0x200(COMPRESS) 730 个 / 0x0(未压缩) 401 个；无 IMPLODE(0x100) 单标志文件
- 压缩实际为 zlib/pkware（掩码字节），解压器全部工作
- 该地图用 **war3map.j（JASS，旧引擎）**，无 war3map.lua
- (listfile) 不全（只有 4 条）→ 按已知文件名读取，不依赖 listfile
- 关键文件均成功：w3u 121KB / w3t / w3a 219KB / w3q / wts 568KB / doo / w3i

## 对象数据格式（实测 head 均为 \x02 00 00 00 = version 2）
- 结构：int32 version；原始对象表；自定义对象表。每表：int32 count + 若干 Object。
- Object：char[4] oldId, char[4] newId(原始表为0000), int32 numMods, Mod[]。
- Mod：char[4] fieldId, int32 type(0 int/1 real/2 unreal/3 string),
       【w3a/w3q/w3d 额外】int32 level, int32 dataPtr，
       value(按 type)，int32 末尾校验(=oldId 或 newId)。
- hasLevelData = 扩展名 ∈ {w3a, w3q, w3d}（待解析时用末尾校验验证）

## 原版 box 实现机制（DLL 逆向分析结论）
- box = StormLib.dll(读写MPQ) + Get.dll(注入游戏读内存) + VMProtect壳exe。
- StormLib：标准开源 MPQ 库（SFileOpenArchive/ReadFile/SCompExplode…），已用纯Python复刻，对等。
- Get.dll(32位)：导出 GetLocalPlayer/SetPlayerNameA/GetMyFilePath；导入 GetCurrentProcess+
  GetModuleHandleA+IsBadReadPtr+GetWindowThreadProcessId（无 ReadProcessMemory）→
  **被注入魔兽进程内读游戏内存**。加密图能抓数据靠的是读内存，不是解析文件。
- 取证：41553CA6(400MB) 的 war3map.w3u 哈希在 MPQ 哈希表中根本不存在 → 文件被剥离进脚本，
  任何静态读文件工具(含StormLib/box)都拿不到；box靠Get.dll读内存才"看得见"。
- 结论：静态读文件这条路我已与 box 对等；差距在内存注入(外挂)，不复刻。

## 提取"不全"的三类原因（逐图验证）
- A 解析崩溃：对象文件尾部多4字节 → 已修(容忍尾字节+单文件try兜底)。
- B 真无 w3u/w3t：加密/优化图剥离到脚本，静态无解。
- C 物品无名称字段：解析正确但数据本身没名字，与box对等。

## 对象数据文件
- war3map.w3u 单位 / w3t 物品 / w3a 技能 / w3q 升级(科技) / w3b 可破坏物 / w3d 装饰物 / w3h buff
- war3mapUnits.doo 预放置单位
- 已有参考：盒子目录 `提取的ID/` 里的 单位ID.txt 等是成品样例

## 不可信文件健壮性审计（会话 9）
- **BLP 解压炸弹**：BLP 头里的 `width*height` 直接驱动 `bytearray(n*4)` 分配。一个 100 多字节、把尺寸篡改成 `0xFFFF×0xFFFF` 的恶意 BLP，本机实测真分配 ~17GB（17s 才返回）。必须对单边尺寸设硬上限（现 `_MAX_DIM=4096`）——纯 Python 也挡不住头字段驱动的内存放大。
- **MPQ 扇区偏移表**：偏移来自(解密后的)文件数据，逆序/越界时旧码切片成空段被**静默接受**→产出错误解压结果。校验单调+在数据内、否则抛 `ValueError` 才不会悄悄给错数据。
- **搜索解析器**：递归下降对深嵌套括号靠 `_MAX_DEPTH` 截断时，吞掉多余 `(` 却不配对 `)`，会把组之后的查询条件整段丢弃（过滤静默失效）。深嵌套场景下"截断递归"和"不丢内容"互斥，正解是**改迭代（调度场算法）**彻底去递归。
- **逐对象 vs 整文件**：对象档解析一处错位若让整文件丢弃，则尾部一坏会让整类对象凭空消失；应逐对象容错、保留出错前已成功的对象。

## 预放置实例 .doo 格式（会话 13，借鉴 KKWE/w3x2lni + 真图验证）
- **来源**：KKWE 编辑器自带 w3x2lni 开源源码 `core/slk/frontend_doo.lua`（装饰物）。单位 doo w3x2lni 只有「写空文件」的 backend、无解析器，故单位布局靠 62 张真实地图反推 + 「解析完恰好到 EOF」证伪。
- **war3map.doo（装饰物/可破坏物）**：头 `'W3do'` + i32 版本(=8) + i32(=11)；对象数 i32，每个：id(4cc) variation(i32) 坐标(3×f32) 角度(f32 弧度) 缩放(3×f32) 可见(u8) 生命(u8) 掉落表指针(i32) 掉落数(i32)+掉落[{id 4cc, 几率 i32}] 编号(i32)；之后特殊物段：版本 i32(=0) + 数量 i32 + 每个{id i32, 未知 i32, 坐标 2×i32}（本工具只取主表）。
- **war3mapUnits.doo（单位，TFT 版本 8/子版本 11）**：头 `'W3do'`+i32 版本+i32 子版本+i32 单位数；每单位：typeId(4cc) variation(i32) 坐标(3×f32) 朝向(f32 弧度) 缩放(3×f32) flags(u8) 玩家(i32) 未知(2×u8) 生命(i32) 魔法(i32) 掉落表指针(i32) 掉落组数(i32)+组[物品数 i32+{id 4cc, 几率 i32}] 金币(i32) 目标获取范围(f32) 英雄等级(i32) 力量/敏捷/智力(3×i32) 背包数(i32)+{槽位 i32, id 4cc} 技能数(i32)+{id 4cc, 自动施法 i32, 等级 i32} 随机标志(i32: 0→读1×i32 / 1→2×i32 / 2→数量 i32+{id 4cc,几率 i32}) 自定义颜色(i32) 传送门(i32) 编号(i32)。
- **验证**：61/62 张真图按此布局解析后游标**恰好落在 EOF**（如 Fireball 图 189 单位 20995/20995 字节）；自适应错位绝不可能在上千单位上对齐，故布局可信。
- **RoC 版本 7/子版本 9 差异**：1 张老 .w3m 的单位记录比 TFT 短 1 个 i32（115→111），变长尾部布局与 TFT 不同。样本仅 1 个最简 sloc 单位、不足以钉死老布局，故按版本不强解、损坏即优雅降级（保前置字段后停）。modern 图全是 v8，不受影响。

## war3map.imp 导入清单格式（会话 13）
- 头：i32 版本 + i32 数量；每条 1 字节标志 + `\0` 结尾路径。与 w3x2lni `search_imp` 一致。
- 用途：优化/保护图删了 (listfile) 时，imp 仍记着自定义导入文件名，可补全导出清单。imp 内多为相对名，直查不到时补 `war3mapImported\` 前缀再试（与 w3x2lni 一致）。
- **本批样本实测**：62 张 demo 图里仅 3 张有 imp，且其 imp 名要么档内无数据、要么 listfile 本就完整 → 这批图 imp 额外导出 0 个。功能正确且安全（注水 count/截断均优雅返回），增益面向真正「剥 listfile + 内嵌导入」的保护图，本样本未踩到。

## w3i / wct 格式 + 字段全量标签（会话 14，多代理析 KKWE 后实装）
- **war3map.w3i（地图信息）**：首 int32 即 file_version(18=RoC/25=TFT/28=重制1.31/31=1.32)。顺序(移植 w3x2lni frontend_w3i.lua)：版本→map_ver→we_ver→(v≥28: 4×i32 war3版本)→z 地图名/作者/描述/推荐人数→8×f32 镜头边界→4×i32 镜头补足→i32 宽/高→u32 flag 位域(bit2=对战图 bit6=自定义队伍 bit7=自定义科技树 bit8=自定义技能 bit9=自定义升级)→c1 主地表→(v≥25: 载入屏 i32+4z、game_data_set i32、序章 4z、雾 i32+3f+4B、环境 c4+z+c1+4B；v≥28: i32 脚本类型 0=JASS/1=Lua；v≥31: 2×i32)→(v18: 载入屏 i32+3z、序章 i32+3z)→玩家段 i32 count×{i32 id/type/race/fixstart, z 名, 2×f32 开局, 2×u32 同盟[, v≥31: 2×i32]}→队伍段 i32 count×{u32 flag(bit0 同盟/bit1 同盟胜利/bit3 共享视野/bit4 共享控制), u32 玩家位掩码, z 名}→升级/科技/随机段(段前 peek 单字节==0xFF 判空)。本工具只取到玩家/队伍段。z 串经 wts 还原 TRIGSTR。**62/62 真图解析通过**(版本 25×61 + 18×1)。
- **war3map.wct（自定义脚本）**：L 版本(>1 则==0x80000004 重制，再读 L 真版本==1)；全局块 z 注释+i32 size(≠0 则 z 代码)；触发器块经典 i32 count 循环 / 重制无 count 读到 EOF，每块 u32 size(0=空，否则 size-1 字节代码+1 字节 NUL)。**62/62 真图解析通过**，全是经典 v1。原始 wct 是二进制，解码后并入 md.scripts 供导出。
- **字段全量标签**：fields.py 原仅 ~80 手挑字段。用 KKWE 8 个 MetaData.slk(字段码→displayName(WESTRING_*)+type) + 本项目 westrings.py 链式还原，离线生成 field_meta.py 的 1444 个中文标签 + 1521 个类型。label_for 改两层(精选优先→全量兜底→原码)。generator=build_field_labels.py。
- **三层并集枚举**：mpq.list_files 原仅读 (listfile)。加内置 STATIC_MAP_FILES(war3map.* 全集 + 战役级 + MPQ 内部表)，只收 has_file 验证存在的；再并 war3map.imp 导入名(相对名补 war3mapImported\ 前缀)。删了 listfile 的保护图也能枚举固定名文件。本批 demo 图 listfile 本就全，仅补出 (listfile) 自身。
- **多代理分析全清单**：见 docs/KKWE借鉴清单.md（14 项增强 + 不建议做项；落地 #1/#3/#4/#5/#9 + 可选 #6-lite/#8/#11/#14）。
- **可选增强批次（同会话后续）**：
  - **#11 war3campaign.w3f 战役头**（w3i.py parse_w3f）：i32 version+i32 campaign_version+i32 editor_version+z 名/难度/作者/描述（移植 frontend_w3f.lua，KKWE 自身也只解到头）。当时无 `.w3n` 样本；现已由仓库内 StormLib 战役 fixture 覆盖。
  - **#8 多值字段列表化**（fields.CONCAT_TYPES + api._expand_codes）：abilityList/unitList 等 concat 类型字段把逗号分隔的码逐项还原「原版名(码)」；实测「技能列表: 蝗虫(Aloc), 无敌的(Avul)」。
  - **#6-lite 整数码识别**（script_scan._codes_in + _int_to_code）：JASS 里 'hpea' 常写成 1752196449 或 0x68706561，按阈值 0x41303030('A000')+4 字节全可打印过滤普通数字后并入对象码（原仅认 'xxxx'/$XX/FourCC）。
  - **#14 WTS 注释行 { 加固**（wts._OPEN 独占行锚定）：STRING 头与正文间注释行（如 `// 备注 {x}`）里的 { 不再被当成正文起点；找不到独占行 { 时退回首个 { 不回归。62 张真图新旧解析**完全一致**（零回归）。**编码改动（mbcs）评估后不做**：简中系统 mbcs≡gbk 无收益，非简中系统会把 GBK 老图错解成乱码（净风险）。

## 重制版 .doo 皮肤字段（会话 15，实测 Reforged 2.0.4 安装目录）
- **当时现象**：用户重制版安装目录 `C:\Program Files (x86)\Warcraft III` 是 **CASC 存储**（`.build.info`+`Data/data/*.idx`+`data.###`），无散装地图；该轮尚未接入游戏本体数据源，当前能力以本节末尾“CASC 游戏本体数据（更新）”为准。用户下载的地图（Documents\Warcraft III\Maps）仍是 MPQ，w3xray 能提（实测 `Darkborne RPG v23` 70MB 保护图：591 单位/383 物品/620 技能等全出）。
- **重制版 doo 格式差异**：实测重制版地图的 war3map.doo 与 war3mapUnits.doo **每条记录在 scale 后多一个 4 字节皮肤(skin)码**，但 version/sub 仍是 8/11，**无法靠版本号区分**经典/重制。
  - 证据：Darkborne 的 war3map.doo（33944 装饰物）按经典布局第 0 条 ndrops 即 -1（错位）；加 skin 后 1833000/1833000 字节恰好到 EOF。Amazonia 的 units.doo（98 单位）同理：skin 后 11670/11670 到 EOF。
  - 解法：parse_doodads/parse_units 改**两种布局都试、取能完整读完所有 count 的那个**（经典 skin=False 先试，完整即返回；否则试 skin=True）。各 count 字段加 _CAP=256 上限，错位布局快速触发换试。经典图永远先命中 skin=False，无回归。
  - 实测：27 张 Season1 重制版对战图 → 27 有装饰物、25 有单位（修前全 0）。这就是之前因"无实据"暂缓的清单 #13，现已有实据并实现。
- **CASC 游戏本体数据（当前）**：已实现固定版本 CascLib 的 Windows 已知路径读取和全 Root 流式枚举；未知原路径条目保留 CascLib 返回的 `FILE%08X.dat`/CKey/EKey 名称，可按原名重开。其他平台或 DLL 不可用时使用散文件/path-map 回退。真实 Windows 魔兽安装仍需 workflow 证据，不宣称真机已验证；该能力不改变单张 `.w3x` 的 MPQ 静态提取路径。

## 保护图：block 表注水越界（幻想未来v1.366）
- 加固手法：MPQ 头 `header_size` 填 `0xFFFFFFFF`(垃圾哨兵)、`block_count` 注水(2049，比 hash_count 多 1)，使 block 表声明长度超出文件尾约 16KB(实际只 ~1006 条在档内)；hash 表本身完整。
- StormLib 容忍：只读落在文件内的 block 条目即可加载。本项目 `_read_tables` 本就按 `avail=实际字节//16` 截断、`read_file` 也挡 `block_index ≥ len(block_table)`；唯一卡点是 `_validate_header` 过严(要求整张 block 表在文件内)。
- 修法：block 表只校验"起点在文件内"，越界尾部丢弃；hash 表仍要求整表在文件内(既是正确性——hash_count 是查找取模基数，也是反 DoS——把 hash_count 卡在 文件大小/16 内)。
- 与"真·加密保护图"的区别：本类只是头部字段注水，文件数据本身在档且未加密；真加密图(如千风同类)会把业务数据移出可静态恢复的 MPQ 结构。此时应由地图作者提供未保护文件、明文/listfile/key；本项目不执行内嵌 loader，也不做运行时内存 dump、调试器或平台保护绕过。

## 完整静态提取总验收（会话 53）
- WTG ECA 已形成明确的三层能力：无 schema 保留触发器头；有 `TriggerData.txt` 展开函数体；再有 `TriggerStrings.txt` 输出本地化语义文本。
- Windows CascLib 已实现已知逻辑路径读取和完整 Root 枚举，散文件/path-map 为回退；macOS fake-native、源码构建和打包已验证，但没有本轮 Windows 魔兽真机证据。
- 真实 fixture 端到端生成 72 个资料包文件，覆盖 UI 文本、资源本体、配置格式、存档/ID、对象 ID、ECA、外部 listfile 诊断和提取完整性；导出过程不修改 `MapData`。
- 安全复审发现并修复两个边界：锚定输出采用临时文件、既有目标备份和越界恢复，不再在祖先校验前截断最终名或在发布窗口丢失原文件；外部 listfile 增加字节、行长和条目数上限并改为逐行迭代。全量验证为 **684 passed, 16 skipped, 1 subtest passed**。

## Windows/CASC 闭环恢复点（会话 54）
- 当前未提交实现已扩展到 CascLib 3.0 全 Root 枚举，未知逻辑路径条目保留 `FileDataID`、CKey、EKey，可按枚举身份再次读取和导出。
- CASC 浏览器已有 GUI 分页、TSV 清单和 `main.py casc inventory/extract`；`write_casc_inventory()` 已改为约 64 KiB 分块写同目录 stage，不再滞留完整 TSV。
- 作者明文补充包、真实存档只读分析、CLI/GUI 验收、Windows 打包与 self-hosted Warcraft workflow 均在工作区；本轮必须以新鲜测试和 workflow 结果区分“代码已实现”与“真实环境已验证”。
- 仓库新增 StormLib `.w3n`、StormLib Huffman MPQ、wc3libs 旧 SLK 真实格式 fixture，用于替代本机不存在的私有 Windows 样本路径。
- 恢复时定位的 CASC 清单内存缺口是：旧 `write_casc_inventory()` 虽消费生成器，却累积全部 TSV 行再发布。该实现已被有界分块 stage + 原子发布替换，并由枚举未结束时 stage 增长测试锁定。
- 现有 `safe_output` 已有同目录唯一临时文件、锚定目录句柄、发布前复核和恢复逻辑，但公共 API 只接收完整 `bytes`/`str`。CASC 清单应复用这套 staging/publication 机制，新增受控的分块生产者入口，而不是另写一个弱化安全边界的 `NamedTemporaryFile + replace`。
- 锚定实现的关键边界可直接复用：`open_staged_file()` 创建 no-follow/O_EXCL stage，`publish_staged_file()` 对既有目标建立私有硬链接备份并在越界时恢复，`remove_owned_staged_file()` 只按 inode 清理自己的 stage。新增分块入口只应替换“向 stage 写完整 bytes”这一段，发布协议保持不变。
- 新增流式输出四个核心模块的 basedpyright 结果为 **0 errors, 0 warnings**。扩大到非 GUI 新核心模块为 **0 errors, 55 warnings**；剩余告警主要来自 ctypes 动态 `_fields_`、旧 `MapData` 未参数化容器以及兼容 MPQ 内部 `_data`，不是运行错误。对 GUI mixin 文件单独执行 strict 检查会暴露大量既有组合式继承属性告警，不能据此宣称新增 GUI 运行失败。
- 仓库中 `typing.Generator` 的三个遗留导入（CASC 浏览器、CascLib source、对应测试）已全部改为 `collections.abc.Generator`；CASC 浏览器自身状态字段补了显式类型。
- Windows 资产初检：hosted workflow 使用 `windows-latest` 完成依赖、固定 CascLib、全测、onedir 打包、打包 EXE acceptance 和 artifact 上传；真实客户端 workflow 明确绑定 `[self-hosted, Windows, X64, w3xray-war3]`，调用 `run_windows_acceptance.ps1` 并要求 `.build.info`。脚本中的默认地图与战役 fixture 路径都已指向仓库内文件。
- `actionlint` 对自托管自定义标签会按预期报“未知 runner label”；忽略这一个仓库外部标签后，两个 workflow 语义检查为零问题。`war3_dir` 和 evidence 路径已改经 step `env` 传入 PowerShell，不再把 dispatch 输入直接插入 `run` 源码。
- “无借口样本检查”直接指定仓库内真实格式 fixture：StormLib `.w3n`、StormLib Huffman MPQ、wc3libs 旧 SLK 共 **19 passed, 0 skipped**。因此这三类不再依赖私有 Windows 文件或测试跳过。
- review-work 安全审查确认三项需修阻断边界：真实存档在 `stat` 后按路径重开存在换包竞态；作者明文 `files/` symlink 会被 `.resolve()` 当成可信根且验证后 `read_bytes()` 无界；MPQ 内成员在声明大小/聚合预算检查前已解压。self-hosted workflow 还需固定 `local` ref、最小权限、environment 审批和禁用 checkout 凭据持久化。
- 对固定 CascLib commit `4971d...` 的源码核对证实：`CascLib.h` 明确写明 `CASC_FIND_DATA.szFileName` 的 Full/DataId/CKey/EKey 四种名字都可用 `CASC_OPEN_BY_NAME(0)` 直接交给 `CascOpenFile`。FileDataID 实际伪名格式是大写十六进制 `FILE%08X.dat`；测试已改用真实格式，Windows integration/acceptance 会重开一个未知条目并核对大小。
- 旧“仅已知 CASC 路径/不做全 Root”句子已在 `findings.md`、`progress.md` 与 `docs/KKWE借鉴清单.md` 统一更新；当前结论是“全 Root 代码与跨平台代理测试已完成，真 Windows 证据待 workflow”。
