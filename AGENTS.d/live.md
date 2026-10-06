# live: 运行中游戏的只读物品读取

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
```

- 不带 `--unit`: 自动识别**当前选中单位**并读其 6 格背包, 同时列出全图带物品单位
  (英雄 / 宝宝 / 背包马甲 / 祭台守卫等)。
- `--unit`: 名字子串或四码匹配 (寒冰 → 寒冰游侠; h00X → 所有宝宝)。
  玩家自己起的角色昵称 (如「艾希」) 不在地图单位表里, 匹配不到时先不带
  `--unit` 看全列表, 再按类型名/四码取。
- 需要管理员权限 (SeDebugPrivilege + OpenProcess); 游戏没开则报告"war3 未运行"。

## 输出含义
- 槽位 = 背包 6 格 (0-5); 名字来自地图知识包 `物品.tsv`, 四码是地图物品 ID。
- 全图单位列表可用来确认宝宝马甲等副背包; 读到的就是实时状态 (合成/换装即时可见)。

## 原理 (`w3xtool/live_handle_chain.py`)
全部偏移经 Game.dll 静态反汇编 (capstone) 验证, 纯 ReadProcessMemory 只读:

1. 句柄系统: `[dll+0xBE40A8]`=句柄管理器, 双表 (bit31 选表), 8 字节条目
   {标记, 包装指针}; 包装 +0x18=世代校验, +0x20=0 存活, +0x54=对象指针。
2. 选中链 (SelectUnit/ClearSelection 反汇编): `[dll+0xBE4238]`=vmctx →
   +0x28(字)=本地玩家号 → [vmctx+0x58+玩家号*4]=玩家上下文 → +0x34=选中管理器
   → +0x1E0=当前选中条目 → +0xC/+0x10=句柄对 → 解出选中单位。
3. 背包: 单位 +0x30=类型四码, +0x1F8=背包; 槽区 = 背包+0x70+12*k,
   12 字节句柄对, 空 = (lo&hi)==0xFFFFFFFF 或 (lo|hi)==0; 物品 +0x30=物品四码。

策略顺序: auto → handle (本链, 版本已知时) → chain (启发式) → icons (截图匹配)。

## 版本适配 (换 1.24 / 1.3x 时)
`HANDLE_CHAIN_OFFSETS` 目前收录 1.27.0.52240 (KK 平台)。换版本:
1. 内存快照里找 native 名字**堆副本** (`SelectUnit\0` 等), numpy searchsorted
   找指向它的 dword = 原生表条目, 邻近 Game.dll .text 指针 = 实现地址。
2. capstone 反汇编 SelectUnit/ClearSelection/UnitItemInSlot 实现, 提取全局 RVA
   与结构偏移, 新增一条 `HANDLE_CHAIN_OFFSETS`。
3. 跑 `uv run python -X utf8 -m pytest -q tests/test_live_handle_chain.py` 回归。

## 边界
只读: ReadProcessMemory / PrintWindow 快照; 永不注入、永不写游戏内存、
永不执行提取出的二进制/地图载荷。见 AGENTS.md Boundaries。
