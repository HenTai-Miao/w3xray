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

# 列出每个真人玩家号下的单位 (所有者 + 坐标)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --players

# 校准并读取全部玩家资源 (金币/木材/人口): 传当前 HUD 显示的自己的金木值
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources 169 808

# 自动差分 (免报数, 连拍3快照找上涨金币列; 打钱时效果最好)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources auto

# 按玩家号标注真实玩家名 (大厅号=名字, 逗号分隔; 不传则用该玩家号主英雄名)
uv run --with numpy --with pillow python -X utf8 main.py live <地图路径> --resources auto --nick "1=大白海岸,2=飞信对信,3=萌新"
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
  超量槽位 (单玩家号挂上千生成物件, 整个槽位被上限过滤成空) 会从带物品单位
  中打捞条目补录 (`salvage_big_owner_units`), 英雄/坐骑/商店等交互对象不再丢失。
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

## 版本适配 (换 1.24 / 1.26 / 其他平台时)

**首选: 自动推导 (无版本依赖)**。版本号不在 `HANDLE_CHAIN_OFFSETS` 里时,
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

**兜底: 手工反汇编** (自动推导失败时):
1. 内存快照里找 native 名字**堆副本** (`SelectUnit\0` 等), numpy searchsorted
   找指向它的 dword = 原生表条目, 邻近 Game.dll .text 指针 = 实现地址。
2. capstone 反汇编 SelectUnit/ClearSelection/UnitItemInSlot 实现, 提取全局 RVA
   与结构偏移, 新增一条 `HANDLE_CHAIN_OFFSETS`。
3. 跑 `uv run python -X utf8 -m pytest -q tests/test_live_handle_chain.py` 回归。

## 边界
只读: ReadProcessMemory / PrintWindow 快照; 永不注入、永不写游戏内存、
永不执行提取出的二进制/地图载荷。见 AGENTS.md Boundaries。
