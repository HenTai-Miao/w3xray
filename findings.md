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
