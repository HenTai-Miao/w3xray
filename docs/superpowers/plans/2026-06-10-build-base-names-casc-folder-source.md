# build_base_names 文件夹源（CASC/重制版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给一次性脚本 `build_base_names.py` 增加从普通文件夹读数据的能力，使其能用 CascView/casc-extract 外部导出的重制版（CASC）数据刷新原版内置数据。

**Architecture:** 把脚本的数据源抽象为统一的 `has_file/read_file` 接口；新增 `DirSource` 把一个文件夹伪装成与 `MPQArchive` 同接口的源，匹配大小写/斜杠不敏感且容忍 `war3.w3mod/` 命名空间前缀。CLI 增 `--from-dir`，CASC 格式解析交给外部成熟工具，仓库内只加今天即可在 1.27 上验证的文件夹读取器。

**Tech Stack:** Python 3（标准库 `os`/`argparse`），pytest，现有 `w3xtool.mpq.MPQArchive`。

---

## 文件结构

- 修改：`build_base_names.py`（repo 根）—— 新增 `DirSource`、`build_sources()`、argparse；`main()`/`build_base_objects()` 改为接收数据源与输出目录；守护 `sys.stdout.reconfigure`；新增 `--from-dir` 覆盖报告。
- 新建：`tests/test_build_base_names.py` —— `DirSource` 单元测试 + 文件夹模式端到端冒烟测试（合成数据，不碰真实游戏文件）。
- 修改：`README.md` —— 增「刷新原版数据 / 重制版」小节。

每个任务都是自包含、可独立提交的改动。

---

### Task 1: 让脚本可被测试导入（守护 stdout）

模块顶层 `sys.stdout.reconfigure(...)` 在 pytest 捕获 stdout 时会抛 `AttributeError`，导致 `import build_base_names` 失败。守护它，使脚本可被测试导入，同时不改直接运行时的行为。

**Files:**
- Modify: `build_base_names.py:9`
- Test: `tests/test_build_base_names.py`

- [ ] **Step 1: Write the failing test**

新建 `tests/test_build_base_names.py`，内容：

```python
"""build_base_names.py 的测试：DirSource 文件夹源 + 文件夹模式端到端。

只用合成数据，不读真实游戏文件，因此在经典 1.27（甚至无游戏）环境下也能跑。
"""
import os

import pytest

import build_base_names as bbn


def test_module_imports():
    # 顶层 stdout.reconfigure 被守护后，pytest 捕获下也能导入
    assert hasattr(bbn, "main")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\Program Files (x86)\Warcraft III\地图提取工具\地图提取工具" && uv run pytest tests/test_build_base_names.py -v`
Expected: 收集阶段即报错 —— `AttributeError: '...' object has no attribute 'reconfigure'`（import 失败）。

- [ ] **Step 3: Write minimal implementation**

把 `build_base_names.py:9` 这一行：

```python
sys.stdout.reconfigure(encoding="utf-8")
```

改为：

```python
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: PASS（`test_module_imports`）。

- [ ] **Step 5: Commit**

```bash
git add build_base_names.py tests/test_build_base_names.py
git commit -m "test: 守护 stdout.reconfigure 使 build_base_names 可被测试导入"
```

---

### Task 2: `DirSource` —— 把文件夹伪装成数据源

新增 `DirSource`，实现 `has_file/read_file`，匹配大小写/斜杠不敏感并容忍命名空间前缀。

**Files:**
- Modify: `build_base_names.py`（在 `from w3xtool.mpq import MPQArchive` 之后、`GAME = ...` 之前插入类定义）
- Test: `tests/test_build_base_names.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_build_base_names.py` 追加：

```python
def test_dirsource_case_and_sep_insensitive(tmp_path):
    d = tmp_path / "Units"
    d.mkdir()
    (d / "HumanUnitStrings.txt").write_text("[hfoo]\nName=步兵\n", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    # 查询用 MPQ 风格反斜杠，磁盘是子目录正斜杠
    assert src.has_file("Units\\HumanUnitStrings.txt")
    assert "步兵" in src.read_file("Units\\HumanUnitStrings.txt").decode("utf-8")


def test_dirsource_lowercase_disk(tmp_path):
    d = tmp_path / "units"
    d.mkdir()
    (d / "humanunitstrings.txt").write_text("x", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    # 查询混合大小写，磁盘全小写
    assert src.has_file("Units\\HumanUnitStrings.txt")


def test_dirsource_w3mod_prefix(tmp_path):
    # 模拟 casc-extract 的 war3.w3mod 命名空间前缀
    d = tmp_path / "war3.w3mod" / "units"
    d.mkdir(parents=True)
    (d / "itemfunc.txt").write_text("y", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert src.has_file("Units\\ItemFunc.txt")


def test_dirsource_basename_fallback(tmp_path):
    # 路径结构对不上，但文件名唯一 -> 兜底命中
    d = tmp_path / "whatever" / "deep"
    d.mkdir(parents=True)
    (d / "UnitData.slk").write_text("z", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert src.has_file("Units\\UnitData.slk")


def test_dirsource_missing_returns_none(tmp_path):
    (tmp_path / "a.txt").write_text("z", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert not src.has_file("Units\\Nope.txt")
    with pytest.raises(FileNotFoundError):
        src.read_file("Units\\Nope.txt")


def test_dirsource_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        bbn.DirSource(str(tmp_path))


def test_dirsource_nonexistent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        bbn.DirSource(str(tmp_path / "nope"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: 新增的 7 个 `test_dirsource_*` 全部 FAIL（`AttributeError: module ... has no attribute 'DirSource'`）。

- [ ] **Step 3: Write minimal implementation**

在 `build_base_names.py` 顶部 `from w3xtool.mpq import MPQArchive` 之后插入：

```python
import os


class DirSource:
    """把一个普通文件夹伪装成与 MPQArchive 同接口的数据源（has_file/read_file）。

    用于读 CASC/重制版数据：先用 CascView 或 wc3tools/casc-extract 把游戏文件导到
    一个文件夹，再让本脚本从该文件夹读。匹配大小写不敏感、斜杠方向不敏感，并容忍
    war3.w3mod\\ 等命名空间前缀。
    """

    def __init__(self, root):
        if not os.path.isdir(root):
            raise FileNotFoundError(f"--from-dir 目录不存在: {root}")
        self.root = root
        self._by_rel = {}        # 规范化相对路径 -> 实际磁盘绝对路径
        self._by_base = {}       # 文件名(小写) -> [规范化相对路径, ...]
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                norm = os.path.relpath(full, root).replace("\\", "/").lower()
                self._by_rel[norm] = full
                self._by_base.setdefault(fn.lower(), []).append(norm)
        if not self._by_rel:
            raise FileNotFoundError(f"--from-dir 目录为空（无任何文件）: {root}")

    @staticmethod
    def _norm(name):
        return name.replace("\\", "/").lstrip("/").lower()

    def _resolve(self, name):
        q = self._norm(name)
        # 1. 精确相对路径
        if q in self._by_rel:
            return self._by_rel[q]
        # 2. 以查询路径结尾（吃掉 war3.w3mod/ 等命名空间前缀）
        cands = [r for r in self._by_rel if r.endswith("/" + q)]
        if cands:
            best = min(cands, key=len)
            if len(cands) > 1:
                print(f"  [warning] {name} 有 {len(cands)} 个候选，取最短: {best}")
            return self._by_rel[best]
        # 3. 文件名兜底
        bcands = self._by_base.get(q.rsplit("/", 1)[-1], [])
        if bcands:
            best = min(bcands, key=len)
            if len(bcands) > 1:
                print(f"  [warning] {name} 按文件名有 {len(bcands)} 个候选，取最短: {best}")
            return self._by_rel[best]
        return None

    def has_file(self, name):
        return self._resolve(name) is not None

    def read_file(self, name):
        path = self._resolve(name)
        if path is None:
            raise FileNotFoundError(name)
        with open(path, "rb") as f:
            return f.read()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: 全部 PASS（含 `test_module_imports` 与 7 个 `test_dirsource_*`）。

- [ ] **Step 5: Commit**

```bash
git add build_base_names.py tests/test_build_base_names.py
git commit -m "feat: build_base_names 新增 DirSource 文件夹数据源"
```

---

### Task 3: CLI 与数据源装配（`build_sources` + argparse + `--out-dir`）

把数据源装配与输出目录抽出来，新增 `--from-dir`/`--game`/`--out-dir`；`main()` 与 `build_base_objects()` 改为接收参数。`--out-dir`（默认 `w3xtool`）让端到端测试不会覆盖真实生成文件。

**Files:**
- Modify: `build_base_names.py`（`main` 签名与开头、三处输出路径、`build_base_objects` 签名与输出路径、`__main__` 块）

- [ ] **Step 1: 加 `build_sources()`（在 `def main` 之前插入）**

```python
def build_sources(args):
    """按 CLI 参数返回数据源列表。

    --from-dir: 单个 DirSource（CASC 已是当前 build 最终态，无需多层覆盖）。
    否则: 经典 MPQ 列表（低->高优先级，后者覆盖前者）。
    """
    if getattr(args, "from_dir", None):
        return [DirSource(args.from_dir)]
    game = getattr(args, "game", None) or GAME
    sources = []
    for mq in MPQS:
        try:
            sources.append(MPQArchive(f"{game}/{mq}"))
        except Exception as e:
            print("跳过", mq, e)
    return sources
```

- [ ] **Step 2: 改 `main()` 签名与数据源装配**

把 `build_base_names.py` 中：

```python
def main():
    names = {}
    total_files = 0
    archives = []
    for mq in MPQS:
        try:
            archives.append(MPQArchive(f"{GAME}/{mq}"))
        except Exception as e:
            print("跳过", mq, e)
```

替换为：

```python
def main(args):
    out_dir = getattr(args, "out_dir", None) or "w3xtool"
    names = {}
    total_files = 0
    archives = build_sources(args)
```

- [ ] **Step 3: 三处输出路径改用 `out_dir`**

`base_names.py` 输出，把：

```python
    with open("w3xtool/base_names.py", "w", encoding="utf-8") as f:
```

改为：

```python
    with open(os.path.join(out_dir, "base_names.py"), "w", encoding="utf-8") as f:
```

`westrings.py` 输出，把：

```python
    with open("w3xtool/westrings.py", "w", encoding="utf-8") as f:
```

改为：

```python
    with open(os.path.join(out_dir, "westrings.py"), "w", encoding="utf-8") as f:
```

`build_base_objects` 调用，把：

```python
    build_base_objects(archives)
```

改为：

```python
    build_base_objects(archives, out_dir)
```

- [ ] **Step 4: 改 `build_base_objects` 签名与输出路径**

把：

```python
def build_base_objects(archives):
```

改为：

```python
def build_base_objects(archives, out_dir):
```

把其中：

```python
    with open("w3xtool/base_objects.py", "w", encoding="utf-8") as f:
```

改为：

```python
    with open(os.path.join(out_dir, "base_objects.py"), "w", encoding="utf-8") as f:
```

- [ ] **Step 5: 改 `__main__` 块加 argparse**

把文件末尾：

```python
if __name__ == "__main__":
    main()
```

替换为：

```python
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="从游戏数据生成原版对象内置数据（base_names/base_objects/westrings）")
    p.add_argument("--from-dir", dest="from_dir",
                   help="从已提取的散文件夹读（CASC/重制版：先用 CascView 或 "
                        "casc-extract 导出，再指向该文件夹）")
    p.add_argument("--game", help="经典 MPQ 安装目录（默认硬编码 GAME 路径）")
    p.add_argument("--out-dir", dest="out_dir", default="w3xtool",
                   help="生成的 .py 写到哪个目录（默认 w3xtool）")
    main(p.parse_args())
```

- [ ] **Step 6: Run existing tests to verify no breakage**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: 仍全部 PASS（本任务未加新测试，确认重构未破坏导入/DirSource）。

- [ ] **Step 7: Commit**

```bash
git add build_base_names.py
git commit -m "feat: build_base_names 加 --from-dir/--game/--out-dir 与数据源装配"
```

---

### Task 4: `--from-dir` 覆盖报告

文件夹模式下逐类打印关键文件「找到/未找到」，方便用户拿真实重制版排查暴雪挪动/改名的文件。把 SLK 分组提到模块级常量供报告与 `build_base_objects` 共用（DRY）。

**Files:**
- Modify: `build_base_names.py`

- [ ] **Step 1: 提取 `SLK_GROUPS` 到模块级**

在模块级 `SLK_LABEL = { ... }` 字典定义之后，新增：

```python
SLK_GROUPS = {
    "单位": ["UnitData.slk", "UnitBalance.slk", "UnitUI.slk", "UnitWeapons.slk", "UnitAbilities.slk"],
    "物品": ["ItemData.slk"],
    "技能": ["AbilityData.slk"],
    "科技": ["UpgradeData.slk"],
}
```

并把 `build_base_objects` 内部原有的局部 `groups = { ... }` 字面量删除，改为复用模块级常量。即把：

```python
    groups = {
        "单位": ["UnitData.slk", "UnitBalance.slk", "UnitUI.slk", "UnitWeapons.slk", "UnitAbilities.slk"],
        "物品": ["ItemData.slk"],
        "技能": ["AbilityData.slk"],
        "科技": ["UpgradeData.slk"],
    }
    out = {}
    for cat, files in groups.items():
```

替换为：

```python
    out = {}
    for cat, files in SLK_GROUPS.items():
```

- [ ] **Step 2: 加报告函数（在 `def main` 之前插入）**

```python
WESTRING_FILES = [r"UI\WorldEditStrings.txt", r"UI\WorldEditGameStrings.txt"]


def report_dir_coverage(src):
    """文件夹模式：打印关键文件找到/未找到清单，便于排查重制版布局差异。"""
    slk = ["Units\\" + f for fs in SLK_GROUPS.values() for f in fs]
    groups = [("名称(Strings/Func)", FILES), ("基础字段(SLK)", slk),
              ("编辑器字符串", WESTRING_FILES)]
    print("\n[--from-dir 覆盖报告]")
    for label, files in groups:
        missing = [f for f in files if not src.has_file(f)]
        print(f"  {label}: 找到 {len(files) - len(missing)}/{len(files)}")
        for m in missing:
            print(f"    未找到 {m}")
```

- [ ] **Step 3: 在 `main()` 中调用报告**

在 `main()` 里 `archives = build_sources(args)` 之后紧接插入：

```python
    if getattr(args, "from_dir", None):
        report_dir_coverage(archives[0])
```

- [ ] **Step 4: 写测试验证报告不崩且能数缺失**

在 `tests/test_build_base_names.py` 追加：

```python
def test_report_dir_coverage_runs(tmp_path, capsys):
    d = tmp_path / "Units"
    d.mkdir()
    (d / "ItemData.slk").write_text("a", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    bbn.report_dir_coverage(src)
    out = capsys.readouterr().out
    assert "覆盖报告" in out
    assert "未找到" in out  # 绝大多数文件缺失
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: 全部 PASS（含 `test_report_dir_coverage_runs`）。

- [ ] **Step 6: Commit**

```bash
git add build_base_names.py tests/test_build_base_names.py
git commit -m "feat: build_base_names 加 --from-dir 覆盖报告并复用 SLK_GROUPS"
```

---

### Task 5: 文件夹模式端到端冒烟测试

构造合成文件夹（含 `*Strings.txt` 与 `*.slk`），跑 `main(--from-dir, --out-dir=tmp)`，断言生成的 `base_names.py` 含预期名字。证明整条文件夹模式链路正确，且不碰真实生成文件。

**Files:**
- Test: `tests/test_build_base_names.py`

- [ ] **Step 1: Write the test**

在 `tests/test_build_base_names.py` 追加：

```python
import types


def test_folder_mode_end_to_end(tmp_path):
    # 合成一个最小的「游戏数据文件夹」
    units = tmp_path / "src" / "Units"
    units.mkdir(parents=True)
    (units / "HumanUnitStrings.txt").write_text(
        "[hfoo]\nName=步兵\n", encoding="utf-8")
    (units / "ItemData.slk").write_text(
        'ID;PWIDTH\nID;Y;K"code";X\nC;Y2;K"ratf"\nID;Y;K"goldcost";X\nC;X2;K200\nE\n',
        encoding="utf-8")

    out = tmp_path / "out"
    out.mkdir()
    args = types.SimpleNamespace(
        from_dir=str(tmp_path / "src"), game=None, out_dir=str(out))
    bbn.main(args)

    names_py = (out / "base_names.py").read_text(encoding="utf-8")
    assert "hfoo" in names_py and "步兵" in names_py
    # 三个产物都应生成
    assert (out / "base_objects.py").exists()
    assert (out / "westrings.py").exists()
```

注：SLK 字面量只需让 `parse_slk` 不报错即可；断言聚焦 `base_names.py`。若实测 `parse_slk` 对该最小 SLK 解析方式不同，按 `w3xtool/slk.py` 的实际格式微调这串内容，保持「至少生成三个产物且 base_names 含 hfoo/步兵」的断言不变。

- [ ] **Step 2: Run test to verify behavior**

Run: `uv run pytest tests/test_build_base_names.py::test_folder_mode_end_to_end -v`
Expected: PASS。若因 SLK 字面量格式 FAIL，读 `w3xtool/slk.py` 确认 `parse_slk` 期望的最小有效 SLK，调整 Step 1 的 `ItemData.slk` 内容后重跑至 PASS。

- [ ] **Step 3: Run full test file**

Run: `uv run pytest tests/test_build_base_names.py -v`
Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/test_build_base_names.py
git commit -m "test: build_base_names 文件夹模式端到端冒烟测试"
```

---

### Task 6: 文档（docstring + README）

更新脚本 docstring 与 README，写清 `--from-dir` 与重制版提取流程。

**Files:**
- Modify: `build_base_names.py:1-5`（模块 docstring）
- Modify: `README.md`

- [ ] **Step 1: 更新模块 docstring**

把 `build_base_names.py` 顶部：

```python
"""一次性脚本：从游戏 MPQ 提取 原版对象 码→中文名，生成 w3xtool/base_names.py。

数据来源：war3/{war3,War3x,War3Patch,War3xLocal}.mpq 里的 Units\\*Strings.txt。
重装/换语言后可重跑本脚本刷新。
"""
```

替换为：

```python
"""一次性脚本：从游戏数据提取 原版对象 码→中文名/默认字段，生成 w3xtool/*.py。

经典版（<=1.29，MPQ）：默认从 war3/{war3,War3x,War3Patch,War3xLocal}.mpq 读
    Units\\*Strings.txt / *Func.txt / *Data.slk。可用 --game 覆盖安装目录。
重制版（1.30+，CASC）：游戏数据改为 CASC，本脚本不内置 CASC 读取。先用 CascView
    或 wc3tools/casc-extract 把 war3.w3mod 下的 units/* 等导到一个文件夹，再：
        python build_base_names.py --from-dir <该文件夹>
    匹配大小写/斜杠不敏感、容忍 war3.w3mod\\ 前缀；--from-dir 会打印找到/未找到清单。
重装/换语言/升级后可重跑本脚本刷新。
"""
```

- [ ] **Step 2: README 增小节**

在 `README.md` 的「## 重新打包 exe」小节之后，插入：

```markdown
## 刷新原版数据（base_names / base_objects / westrings）
`w3xtool/base_names.py` 等三份内置数据由 `build_base_names.py` 从**游戏本体**一次性生成，运行时不读游戏。换语言/升级后想刷新：

- **经典版（≤1.29，MPQ）**：
  ```bash
  uv run build_base_names.py                 # 默认硬编码安装目录
  uv run build_base_names.py --game "D:/Warcraft III/war3"
  ```
- **重制版（1.30+，CASC）**：游戏数据改为 CASC，本脚本不内置 CASC 读取。先用外部工具导出，再指向文件夹：
  1. 用 [CascView](http://www.zezula.net/en/casc/main.html)（GUI）或 `wc3tools/casc-extract`（CLI，如 `casc-extract war3.w3mod:units/*` ）把游戏 `units/` 下的 `*Strings.txt`/`*Func.txt`/`*Data.slk` 与 `ui/WorldEdit*Strings.txt` 导到一个文件夹。
  2. `uv run build_base_names.py --from-dir <该文件夹>`，按打印的「找到/未找到」清单确认覆盖。
```

- [ ] **Step 3: 校验文档无破坏（跑全套测试）**

Run: `uv run pytest -q`
Expected: 全套测试 PASS（确认文档改动未影响代码）。

- [ ] **Step 4: Commit**

```bash
git add build_base_names.py README.md
git commit -m "docs: build_base_names 说明 --from-dir 与重制版(CASC)刷新流程"
```

---

## 真实对拍（手动验证，非自动测试）

实现完成后，在你本地 1.27（经典 MPQ）上验证文件夹读取器逻辑等价：

1. 用本工具或 CascView/Ladik 的 MPQ 工具，把 `war3.mpq`/`War3x.mpq`/`War3Patch.mpq`/`War3xLocal.mpq` 里 `Units\*` 与 `UI\WorldEdit*Strings.txt` 导到一个文件夹 `dump/`。
2. 分别跑：
   ```bash
   uv run build_base_names.py --out-dir /tmp/a            # MPQ 模式
   uv run build_base_names.py --from-dir dump --out-dir /tmp/b   # 文件夹模式
   ```
3. `diff /tmp/a/base_names.py /tmp/b/base_names.py`，预期一致或仅极少差异（多 MPQ 覆盖层 vs 单文件夹），证明 DirSource 读取等价。

将来拿到重制版时，同法用 CascView 导出后跑 `--from-dir`，对照覆盖报告调整缺失文件。

---

## Self-Review

- **Spec 覆盖**：DirSource(组件1)→Task2；build_sources/CLI(组件2、3)→Task3；覆盖报告(组件4)→Task4；单元测试→Task2、Task4；端到端→Task5；真实对拍→文末手动步骤；文档→Task6。「单个 DirSource 不做多层覆盖」→Task3 `build_sources`。无遗漏。
- **占位符**：无 TBD/TODO；每个代码步骤含完整代码与精确命令。Task5 对 SLK 字面量给了明确的「若 FAIL 如何调整」回退指引（非占位）。
- **类型/命名一致**：`DirSource.has_file/read_file/_resolve/_norm`、`build_sources(args)`、`main(args)`、`build_base_objects(archives, out_dir)`、`report_dir_coverage(src)`、`SLK_GROUPS`、`WESTRING_FILES`、`FILES` 跨任务一致。`args` 字段名 `from_dir/game/out_dir` 与 argparse `dest` 一致。
