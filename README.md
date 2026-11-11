# FAPB 踢 BOT 闪退修复 / FAPB kick-bot crash fix

> Counter-Strike 1.6 · FAPB 1.6（YAPB 2.55b 换名版）· Windows
> 症状：按 `V` 打开 FAPB 菜单，选「队伍管理 → 踢出全部 Bot / 踢出指定 Bot」后 `hl.exe` 直接闪退。

[![Fault](https://img.shields.io/badge/crash-fapb.dll%2B0x18173-c0000005-red)](#原因)
[![Patch](https://img.shields.io/badge/patch-5%20bytes-brightgreen)](#修复内容)
[![License](https://img.shields.io/badge/scripts-MIT-blue)](LICENSE)

---

## 一句话结论

`CBot::~CBot()` 在释放 Bot 名字槽时读取 `gpGlobals->pStringBase`（`fapb.dll+0x18173`），
而这个 `gpGlobals` 指针在运行时已经失效（并且当时有 **6 套 Bot 核心同时在跑**）。
本仓库把这个必崩的读取点用 **5 字节补丁** 绕开，并把 `plugins.ini` 收敛到**只留 FAPB 一套 Bot 核心**。

---

## 30 秒修复

> 先**完全退出游戏**（含后台 `hl.exe`）。

```powershell
git clone https://github.com/Faker1147/fapb-kickfix.git
cd fapb-kickfix

# 自动定位 CS 1.6 目录（也可 -GameDir "D:\Counter Strike 8684(多BOT版)"）
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -GameDir "D:\Counter Strike 8684(多BOT版)"
```

脚本会：

1. 备份 `plugins.ini` 和 `fapb.dll` 到 `cstrike\addons\fapb\backup\<时间戳>\`；
2. 重写 `cstrike\addons\metamod\plugins.ini`，把 YAPB / SYPB / PODBot / EBot / CSBot Enabler 全部注释掉，只留 `fapb.dll`；
3. 给 `fapb.dll` 打 5 字节补丁（见下）。

然后进游戏，控制台确认：

```
meta list          # 只应看到 FAPB 一个 Bot 核心
fapb version
```

再按 `V → 1 → 4/5` 踢 Bot，不再闪退。

---

## 症状

| 项 | 值 |
| --- | --- |
| 出错程序 | `hl.exe` 1.1.1.1 |
| 出错模块 | `cstrike\addons\fapb\dlls\fapb.dll` |
| 异常代码 | `0xC0000005` (读访问冲突) |
| 错误偏移 | **`0x00018173`**（每次都一样） |
| 触发时机 | FAPB 菜单里踢 Bot / `fapb kick` / `fapb kickall` / 换图清理 Bot |

Windows 事件查看器里能看到一模一样的记录，`%LOCALAPPDATA%\CrashDumps\hl.exe.*.dmp` 也有对应转储。

---

## 原因

### 1) 直接原因：把失效的 `gpGlobals` 当有效指针用

崩溃点落在 `CBot::~CBot()`（`fapb.dll` VA `0x100180E0`）：

```asm
1001811D  A1 DC350B10     mov  eax, [0x100B35DC]   ; 名字表条目数
10018122  33F6            xor  esi, esi
10018124  85C0            test eax, eax
10018126  0F84B4000000    je   0x100181E0          ; 没有名字 → 直接结束
10018130  ...             ; 遍历名字表：
10018161  8B9794040000    mov  edx, [edi+0x494]    ; m_pEdict
10018167  8B82D0010000    mov  eax, [edx+0x1D0]    ; v.netname (string_t)
1001816D  8B1548350B10    mov  edx, [0x100B3548]   ; gpGlobals
10018173  038298000000    add  eax, [edx+0x98]     ; <-- pStringBase  ★崩在这
10018180  ...             ; strcmp(名字表[i], STRING(netname))
```

`[0x100B3548]` 是 Metamod 在 `GiveFnptrsToDll()` 里塞进来的 `globalvars_t*`。
从崩溃转储里读出来的实际值（多份转储一致）是 `0x03037620`，而 `0x03037620 + 0x98 = 0x030376B8`
所在页**根本没有映射**，所以 `add eax, [edx+0x98]` 必崩。

> 注意：`0x3037620` 和 `0x30376B8` 在**同一页**（`0x3037000`）。同一页里前 0x98 字节可读、后面不可读是不可能的——
> 说明整个 `gpGlobals` 指向的内存已经被释放/回收，指针是**悬垂指针**，不是"偏移算错"。

### 2) 触发条件：同时加载了 6 套 Bot 核心

崩溃当时的进程模块列表（来自 `hl.exe.*.dmp`）：

```
csbot_enabler_mm.dll   0x60DE0000
sypb.dll               0x60D00000
podbot_mm.dll          0x2F220000
yapb.dll               0x2F350000
ebot.dll               0x5FC50000
fapb.dll               0x2EF50000      <-- 和上面 5 套一起加载
```

而 `plugins.ini` 原样是这样：

```ini
win32 addons/amxmodx/dlls/amxmodx_mm.dll
win32 addons/csbot_enabler/csbot_enabler_mm.dll
win32 addons/sypb/dlls/sypb.dll
win32 addons/podbot/podbot_mm.dll
 win32 addons/yapb/bin/yapb.dll
 win32 addons/ebot/dlls/ebot.dll
win32 addons/fapb/dlls/fapb.dll
```

FAPB 自带的 `README_FAPB.txt` 第七节写得很清楚：**YAPB / SYPB / PODBot / EBot / CSBot 与 FAPB 同一时间只能启用一套**，
否则"重复 Bot、抢 Hook、菜单错乱甚至崩溃"。多套 Bot 核心都去 Hook `GiveFnptrsToDll` /
`ServerActivate` / `ClientPutInServer` 这些入口，引擎侧的全局状态被反复重建，FAPB 缓存的
`gpGlobals` 就成了悬垂指针 —— 平时不访问所以看不出来，一旦踢 Bot 进析构函数就爆。

详细取证过程见 [docs/diagnosis.md](docs/diagnosis.md)。

---

## 修复内容

### A. `plugins.ini` 只留一套 Bot 核心（治本）

```ini
win32 addons/amxmodx/dlls/amxmodx_mm.dll

; --- disabled bot cores (only one may be active) ---
; win32 addons/csbot_enabler/csbot_enabler_mm.dll
; win32 addons/sypb/dlls/sypb.dll
; win32 addons/podbot/podbot_mm.dll
; win32 addons/yapb/bin/yapb.dll
; win32 addons/ebot/dlls/ebot.dll

;; --- FAPB: the only active bot core (managed by fapb-kickfix) ---
win32 addons/fapb/dlls/fapb.dll
```

### B. 5 字节补丁（止血）

`fapb.dll` 的 `CBot::~CBot()` 入口改成直接跳过"释放名字槽"那段循环：

```diff
- 1001811D  A1 DC350B10   mov eax,[0x100B35DC]
+ 1001811D  E9 BE000000   jmp 0x100181E0
```

- 文件偏移：`0x1751D`（RVA `0x1811D`，`.text`）
- 原始 SHA-256：`606e7a6ab8793553847bcbf2d5665d29edea0b3529eaca537d7e76de7b6e3553`
- 补丁后 SHA-256：`18e536c00cc58573f3d4d0a803aedc9b4d0e4993654612e62b7c48b756762152`
- 除这 5 字节外**没有任何改动**（工具会校验、会拒绝在字节不符时动手）

跳转落在 `0x100181E0`，正好是原来的循环出口（SEH 状态复位 + 成员析构 + 函数返回），
`edi`（`this`）保持不变，控制流完整。

**代价**：踢掉 Bot 后不再把它的名字标记为"未占用"。名字池是 `config/language/en_names.cfg`
里的 146 条，而且**每次换图都会重新加载**，所以只有在同一张图里连续创建/踢掉上百个 Bot 才可能有影响
（后果是 Bot 名字重复，不会崩）。这个取舍是为了"绝不闪退"。

---

## 与 ABPB 共存（1.1.0 新增）

ABPB 4.3.3（AiBo 分支）可以和 FAPB 装在一起，但 ABPB 的"检测到别的 BOT 就让位"守卫
**认不出 FAPB**：它找的是 `fapb_quota` / `fapb_version`，而 FAPB 注册的是
`fb_quota` / `fb_version`。结果两边都保持补位，还是会出事。

```powershell
# ABPB 主导（推荐）：ABPB 刷 Bot，FAPB 只挂着不补位
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode abpb

# FAPB 主导：ABPB 让位，并给 ABPB.dll 打守卫补丁
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode fapb
```

守卫补丁只改 ABPB.dll 的 22 个字节（两段 cvar 名字 + 两个长度字段），
把 `fapb_quota` → `fb_quota`、`fapb_version` → `fb_version`，可 `--revert`。
细节和取证见 [docs/abpb-compat.md](docs/abpb-compat.md)。

---

## 工具

| 脚本 | 作用 |
| --- | --- |
| `scripts/install.ps1` | 一键：备份 → 单核心 `plugins.ini` → DLL 补丁 |
| `scripts/restore.ps1` | 从备份完整还原（含 ABPB 相关文件） |
| `scripts/fapb_patch.py` | 打补丁 / 还原 / 校验，支持 `--dry-run`、`--json` |
| `scripts/doctor.py` | 体检：Bot 核心数量、补丁状态、`fapb.cfg` 越界值、WER 崩溃转储 |
| `scripts/fapb_abpb_setup.ps1` | 让 FAPB 与 ABPB 共存，`-Mode abpb\|fapb` |
| `scripts/abpb_compat.py` | 修 ABPB 的 BOT 检测表，让它认得出 FAPB |

```powershell
# 只体检，不改任何东西
python .\scripts\doctor.py --game-dir "D:\Counter Strike 8684(多BOT版)" --dumps

# 只修配置、不动 DLL
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -NoDllPatch

# 只打/撤补丁
python .\scripts\fapb_patch.py --dll "...\fapb.dll" --apply
python .\scripts\fapb_patch.py --dll "...\fapb.dll" --revert

# ABPB 守卫补丁
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --apply
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --revert
```

`doctor.py` 输出示例：

```
[1] Metamod 插件列表
    OK  只有一个 Bot 核心: win32 addons/fapb/dlls/fapb.dll
[2] fapb.dll
    state  : patched   (bytes E9BE000000 @ RVA 0x1811d)
[3] fapb.cfg 关键参数
    fb_quota           = 0
    fb_followuser      = 99      !! 超出合理范围 (0/1 或玩家序号; 99 是无效值)
```

---

## 验证

1. 启动游戏，控制台 `meta list` → 只有一条 FAPB。
2. `V → 1 → 4`（踢出全部 Bot）、`V → 1 → 5`（踢出指定 Bot）各点几次。
3. `%LOCALAPPDATA%\CrashDumps` 里不应再出现新的 `hl.exe.*.dmp`；事件查看器无新的 `0x18173`。
4. `python scripts\doctor.py --dumps` 应显示 `结论: 一切正常`。

---

## 回滚

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 -GameDir "D:\Counter Strike 8684(多BOT版)"
```

会自动挑最新的备份目录还原 `plugins.ini` + `fapb.dll`。

---

## 想换回 YAPB？

把 `plugins.ini` 里 `yapb.dll` 那行取消注释、注释 `fapb.dll` 那行，然后跑一次 `doctor.py` 确认只有一套 Bot 核心。
**任何情况下都不要同时启用两套。**

---

## 目录结构

```
fapb-kickfix/
├─ README.md
├─ CHANGELOG.md
├─ LICENSE
├─ docs/
│  ├─ diagnosis.md          完整取证：转储、寄存器、PE、指令流
│  └─ abpb-compat.md        ABPB 检测表分析 + 两种共存模式
└─ scripts/
   ├─ install.ps1
   ├─ restore.ps1
   ├─ fapb_patch.py
   ├─ abpb_compat.py
   ├─ fapb_abpb_setup.ps1
   └─ doctor.py
```

> 本仓库**不包含** `fapb.dll` / `ABPB.dll` 本体。FAPB 是 YaPB 2.55b 的改名分支、
> ABPB 是 AiBo 4.3.3 的改名分支（均为 GPL 系），重新分发二进制请遵守其许可证并保留原作者署名。
> 这里只放差异补丁与工具。

---

## License

脚本：MIT（见 [LICENSE](LICENSE)）。
FAPB / YaPB：遵循其原始许可证（YaPB，GPL）。
