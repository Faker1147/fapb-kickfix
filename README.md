# FAPB 踢 BOT 闪退修复 / FAPB kick-bot crash fix

> Counter-Strike 1.6 · FAPB 1.6（YaPB 2.55b 换名版）· Windows
> 症状：按 `V` 打开 FAPB 菜单，选「队伍管理 → 踢出全部 Bot / 踢出指定 Bot」后 `hl.exe` 直接闪退；
> 有的安装还会在加载时报 `badf load` 或随机堆损坏。

[![Fix](https://img.shields.io/badge/fix-rebuilt%20import%20table-brightgreen)](#修复内容)
[![ABPB](https://img.shields.io/badge/ABPB-4.3.3%20coexistence-blue)](#与-abpb-共存)
[![License](https://img.shields.io/badge/scripts-MIT-blue)](LICENSE)

---

## 一句话结论

FAPB 1.6 发布版 `fapb.dll` 是 **UPX 转储产物**：PE 头里的导入目录仍然只描述 UPX stub，
真正的 84 个 `kernel32` 导入槽（IAT，RVA `0x5A000`）里留着**转储进程的旧地址**。
加载器不会修正这些槽，于是 FAPB 调用 API 时跳到错误地址，表现为 `badf load`、堆损坏、
以及踢 BOT 时在 `fapb.dll+0x18173` 的 `0xC0000005`。

1.2.0 的修复不是再打一个跳转补丁，而是用上游固定版本的打包文件和两份内存转储
**重建一个带真实导入表的 `fapb.dll`**（`scripts/fapb_rebuild.py`，SHA 固定校验）。
1.0/1.1 的 5 字节补丁已废弃：它在发布版上只是碰巧绕过崩溃，在重建版上会**必崩**。

---

## 30 秒修复

> 先**完全退出游戏**（含后台 `hl.exe`）。

```powershell
git clone https://github.com/Faker1147/fapb-kickfix.git
cd fapb-kickfix

# 1) 重建 fapb.dll（首次会自动下载约 1.8 MB 固定版本素材）
python .\scripts\fapb_rebuild.py --download --install `
  --game-dir "D:\Counter Strike 8684(多BOT版)"

# 2) 收敛 Bot 核心（FAPB 单独用，或与 ABPB 共存）
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -GameDir "D:\Counter Strike 8684(多BOT版)"

# 2b) 如果还要和 ABPB 4.3.3 共存（推荐 ABPB 主导）
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
  -GameDir "D:\Counter Strike 8684(多BOT版)" -Mode abpb
```

`fapb_rebuild.py` 会：

1. 校验 `yapb.dll` / `yapb_b1.bin` / `yapb_b2.bin` 的 SHA-256（固定到上游 commit
   `4fae46026d296946c196d4c1bcc25ead3036a9bb`）；
2. 从两份转储恢复 **9796 条重定位**；
3. 生成 `.idata`（1 个 `KERNEL32.dll` 描述符 + 84 条 hint/name + `FirstThunk=0x5A000`）；
4. 输出并校验已知良好哈希 `9AFDAA67…8C96`；
5. 备份原 DLL 到 `cstrike\addons\fapb\backup\rebuild-<时间戳>\`，再替换。

进游戏后控制台确认：

```
meta list          # FAPB 应为 RUN
fapb add 2 t
fapb add 2 ct
fapb kickall       # 不再闪退
```

---

## 症状

| 项 | 值 |
| --- | --- |
| 出错程序 | `hl.exe` 1.1.1.1 |
| 出错模块 | `cstrike\addons\fapb\dlls\fapb.dll` |
| 异常代码 | `0xC0000005`（读访问冲突） |
| 错误偏移 | **`0x00018173`**（发布版，每次都一样） |
| 触发时机 | FAPB 菜单踢 Bot / `fapb kick` / `fapb kickall` / 换图清理 |
| 其他表现 | `badf load`、随机堆损坏、`meta list` 中 FAPB 状态异常 |

Windows 事件查看器里能看到同样的记录，`%LOCALAPPDATA%\CrashDumps\hl.exe.*.dmp`
也有对应转储。

---

## 根因

### 1) 发布版 DLL 的导入表是坏的（真正根因）

发布版：`606E7A6A…3553`，643072 字节。FAPB 1.2–1.6 的所有发布 DLL 都是同一份。

- PE 导入目录只描述 **UPX stub** 的导入；
- 解包后的真实代码使用 `kernel32` 的 84 个函数；
- 这 84 个槽位在 RVA `0x5A000`，但里面是**转储进程里解析好的旧地址**；
- 真正的名字表在 RVA `0xBF008`（`GetProcAddress` … `SetEnvironmentVariableA`），
  发布版却没有把它写进导入目录；
- 加载器按“没有导入”处理，旧地址在 `hl.exe` 的地址空间里无效或指向别的模块。

所以问题不是“某个 cvar 没设对”，而是 DLL 本身缺少可加载的导入表。打一个 5 字节跳转
只能让某一条崩溃路径不执行，不能修复 API 调用和堆损坏。

### 2) 踢 BOT 崩溃点：`CBot::~CBot()` 解引用失效的 `gpGlobals`

```asm
1001811D  A1 DC350B10     mov  eax, [0x100B35DC]   ; 名字表条目数
10018122  33F6            xor  esi, esi
10018124  85C0            test eax, eax
10018126  0F84B4000000    je   0x100181E0          ; 0 条 → 直接出口
10018130  ...             ; 遍历名字表
10018161  8B9794040000    mov  edx, [edi+0x494]    ; m_pEdict
10018167  8B82D0010000    mov  eax, [edx+0x1D0]    ; v.netname
1001816D  8B1548350B10    mov  edx, [0x100B3548]   ; gpGlobals
10018173  038298000000    add  eax, [edx+0x98]     ; <-- pStringBase  ★崩在这
10018180  ...             ; strcmp(名字表[i], STRING(netname))
```

`[0x100B3548]` 是 Metamod 在 `GiveFnptrsToDll()` 里传入的 `globalvars_t*`。在坏导入表 +
多套 Bot 核心的环境里，这个指针会变成悬垂指针；`+0x98` 所在页不可读，踢 Bot 进入析构
函数时必崩。

### 3) 多套 Bot 核心会放大问题（也是 YAPB / FAPB 菜单冲突的根因）

原 `plugins.ini` 同时启用了 YAPB / SYPB / PODBot / EBot / CSBot Enabler / FAPB 六套核心。
它们都去 Hook `GiveFnptrsToDll` / `ServerActivate` / `ClientPutInServer`，引擎全局状态被
反复重建，FAPB 缓存的 `gpGlobals` 更容易失效。

更隐蔽的是，这些“被禁用”的行前面只有一个**空格**，没有 `;`。Metamod 解析时会去掉
行首空白，所以它们实际上全部处于启用状态：

```ini
; win32 addons/yapb/bin/yapb.dll     ; 正确：禁用
 win32 addons/yapb/bin/yapb.dll     ; 错误：仍然启用
```

YAPB 和 FAPB 都是 YaPB 2.55b 的改名分支，都会注册菜单命令并维护自己的
`menuselect` 状态。两套同时加载时，FAPB cmenu 的数字键会被 YAPB 菜单一并看到，
表现为“按数字键弹出/执行 YAPB 菜单”。**这不是 FAPB 菜单代码单独的错误，而是同源
菜单被重复加载。** 只保留 FAPB + ABPB 即可，详见 `docs/menu-conflict.md`。

> 旧版 `docs/diagnosis.md` 记录的 0x18173 取证仍然有效；它解释的是“为什么踢 BOT 会崩”，
> 而 `docs/fapb-dll-repair.md` 补充了更底层的“为什么这个 DLL 从一开始就是坏的”。

---

## 修复内容

### A. 重建 `fapb.dll`（治本，1.2.0）

`scripts/fapb_rebuild.py` 用固定素材重建 PE：

| 区段 | RVA / 大小 | 来源 |
| --- | --- | --- |
| `.text` | `0x1000` / `0x96000` | 转储 b1，YAPB→FAPB 品牌替换 |
| `.data` | `0x97000` / vsize `0x2D000`，无文件数据 | 运行时 BSS |
| `.rsrc` | `0xC4000` / `0x1A00` | 打包文件 |
| `.reloc` | `0xC6000` / `~0x5200` | b1 与 b2 差分恢复，9796 条 |
| `.idata` | `0xCC000` / `0x785` | 新建导入表 |
| 入口 | `0x4437B` | 解包后的真实入口 |

导入表细节：

- 一个描述符：`KERNEL32.dll`
- INT 在 `0xCC028`，DLL 名在 `0xCC17C`
- 84 条 `<WORD hint=0> <name> 00` 记录
- `FirstThunk = 0x5A000`（代码原本就在用的 IAT）
- 导入目录大小 `40`

结果：

- 重建版 SHA-256：`9AFDAA6796E59026BDD65425A29AB46429AEE11D9FEE1205FF05351B2DD08C96`
- 大小：645120 字节
- 在 HLDS 里，首选基址 `0x10000000` 被 `vgui.dll` 占用，FAPB 实际加载到 `0x08290000`；
  重定位正常，`meta list` 显示 `FAPB RUN v2.55b`。

**重建版必须保持未打补丁状态。** 实测：重建版 + 旧 5 字节补丁 = 踢 BOT 时崩在
`hl.exe` `EIP 0x005381E0`（栈里能看到 `~CBot` 在 `fapb+0x18838`）。

### B. `plugins.ini` 只留一套 Bot 核心

`install.ps1` 会注释 YAPB / SYPB / PODBot / EBot / CSBot Enabler，只保留 FAPB；
如果已经装了 ABPB，ABPB 的行不会被删（见下一节）。

> 行首只加空格**不会**禁用插件；Metamod 会忽略前导空格。必须用 `;` 或 `//` 开头。
> 只修菜单冲突、不想改 cvars/DLL 时，运行：
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
>   -GameDir "D:\Counter Strike 8684(多BOT版)" -PluginsOnly
> ```
>
> 关掉 CSBot Enabler 后，如果 AMXX 的 `zbot_strengthen.amxx` 报 `Invalid CVAR pointer`，
> 把该插件也注释掉（它只服务 ZBot，FAPB/ABPB 不需要）。

```ini
win32 addons/amxmodx/dlls/amxmodx_mm.dll

; --- disabled bot cores (only one may be active) ---
; win32 addons/csbot_enabler/csbot_enabler_mm.dll
; win32 addons/sypb/dlls/sypb.dll
; win32 addons/podbot/podbot_mm.dll
; win32 addons/yapb/bin/yapb.dll
; win32 addons/ebot/dlls/ebot.dll

;; --- FAPB active (managed by fapb-kickfix; ABPB lines are untouched) ---
win32 addons/fapb/dlls/fapb.dll
```

### C. 5 字节补丁已废弃

旧补丁把 `0x1001811D` 的 `mov eax,[0x100B35DC]` 改成 `jmp 0x100181E0`：

```diff
- 1001811D  A1 DC350B10   mov eax,[0x100B35DC]
+ 1001811D  E9 BE000000   jmp 0x100181E0
```

- 发布版原始：`606E7A6A…3553`
- 发布版 + 补丁：`18E536C0…2152`
- **重建版 + 补丁：`9F2EBB5A…1CAD` ← 会崩，不要用**

`fapb_patch.py` 现在：

- 在重建版上**拒绝** `--apply`；
- 支持 `--revert`，把误打的重建版恢复成 `9AFDAA67…8C96`；
- 只把 5 字节补丁保留为 `-LegacyPatch` / `-LegacyFapbPatch` 的显式兼容选项。

---

## 与 ABPB 共存

ABPB 4.3.3（AiBo 分支）可以和 FAPB 装在一起，但 ABPB 的“检测到别的 BOT 就让位”守卫
**认不出 FAPB**：它找的是 `fapb_quota` / `fapb_version`，而 FAPB 注册的是
`fb_quota` / `fb_version`。

```powershell
# ABPB 主导（推荐）：ABPB 刷 Bot，FAPB 只挂着不补位
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
  -GameDir "D:\CS1.6" -Mode abpb

# FAPB 主导：ABPB 让位，并给 ABPB.dll 打守卫补丁
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
  -GameDir "D:\CS1.6" -Mode fapb
```

守卫补丁只改 ABPB.dll 的 22 个字节（两段 cvar 名 + 两个长度字段），
把 `fapb_quota` → `fb_quota`、`fapb_version` → `fb_version`，可 `--revert`。
支持两个构建：

| 构建 | 原版 SHA-256 | 补丁后 SHA-256 |
| --- | --- | --- |
| ABPB 4.3.3-abpb.1 | `FF61716F…CD776` | `675A62AD…669ED` |
| ABPB 4.3.3-abpb.2 | `6CE76D06…ABBD` | `F2750780…A254D` |

**运行时会夹 quota**：`ABPB.cfg` 里的 `abpb_quota "31"` 不会超过服务器人数上限。
实测 `maxplayers` 为 8 / 12 / 20 时，运行时 `abpb_quota` 分别变成 8 / 12 / 20。
这是 ABPB 的正常行为，不是配置没生效。

`-Mode abpb` 下保持 `abpb_compat_auto 0`，避免打了守卫补丁的 ABPB 把空闲的 FAPB
误判成“另一个正在管理的 BOT”而自动让位。细节见 [docs/abpb-compat.md](docs/abpb-compat.md)。

---

## 工具

| 脚本 | 作用 |
| --- | --- |
| `scripts/fapb_rebuild.py` | **1.2.0 核心**：重建带真实导入表的 `fapb.dll`，支持下载/本地素材、哈希校验、`--install` |
| `scripts/install.ps1` | 备份 → 单核心 `plugins.ini` → 检查 DLL（默认不再打 5 字节补丁） |
| `scripts/fapb_abpb_setup.ps1` | 让 FAPB 与 ABPB 共存，`-Mode abpb\|fapb`；`-RebuildFapb` 可选重建；`-PluginsOnly` 只修菜单冲突 |
| `scripts/restore.ps1` | 从备份还原 `plugins.ini` / `fapb.dll` / `ABPB.dll` / 两个 cfg |
| `scripts/fapb_patch.py` | 查看/撤销旧 5 字节补丁；拒绝在重建版上打补丁 |
| `scripts/abpb_compat.py` | 修 ABPB 的 BOT 检测表，让它认得出 FAPB（支持 abpb.1 / abpb.2） |
| `scripts/doctor.py` | 体检：Bot 核心数量、DLL 是发布版/重建版/误打补丁、cfg 越界值、WER 转储 |

```powershell
# 只体检，不改任何东西
python .\scripts\doctor.py --game-dir "D:\Counter Strike 8684(多BOT版)" --dumps

# 只重建 DLL（不装）
python .\scripts\fapb_rebuild.py --download

# 使用本地素材重建（离线）
python .\scripts\fapb_rebuild.py --artifacts .\tools\artifacts --install `
  --game-dir "D:\Counter Strike 8684(多BOT版)"

# 只改配置、不动 DLL
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -NoDllPatch

# 只修 YAPB / FAPB 菜单冲突（只改 plugins.ini，不动 cvars/DLL）
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
  -GameDir "D:\Counter Strike 8684(多BOT版)" -PluginsOnly

# 撤销误打的 5 字节补丁
python .\scripts\fapb_patch.py --dll "...\fapb.dll" --revert

# ABPB 守卫补丁
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --apply
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --revert
```

`doctor.py` 输出示例：

```
[1] Metamod 插件列表
    OK  共存模式: FAPB + ABPB 同时加载 (只允许一方补位)
         补位方: ABPB
[2] fapb.dll
    state  : rebuilt   (bytes A1DC350B10 @ RVA 0x1811d)
    sha256 : 9afdaa6796e59026bdd65425a29ab46429aee11d9fee1205ff05351b2dd08c96
    OK  重建版 DLL，未打 5 字节补丁（推荐状态）。
[2b] ABPB.dll
    build  : ABPB 4.3.3-abpb.2 Windows x86
    state  : patched
```

---

## 验证

1. 启动游戏，控制台 `meta list` → FAPB 与 ABPB 都是 `RUN`（若共存）。
2. `fapb add 2 t`、`fapb add 2 ct`，再 `fapb kickall`，服务端不死。
3. `abpb add`（ABPB 主导时）或 `fapb add`（FAPB 主导时）能正常刷 Bot。
4. `%LOCALAPPDATA%\CrashDumps` 里不应再出现新的相关 `hl.exe.*.dmp`。
5. `python scripts\doctor.py --dumps` 应显示 `结论: 一切正常`。

> `fb_followuser "99"` 是 repack 预置值，doctor 会把它标成“已知噪音”而不计入问题；
> 它与踢 BOT 崩溃无关。

---

## 回滚

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 `
  -GameDir "D:\Counter Strike 8684(多BOT版)"
```

会自动挑最新的备份目录还原。`fapb_rebuild.py --install` 也会把原 DLL 备份到
`cstrike\addons\fapb\backup\rebuild-<时间戳>\`。

---

## 想换回 YAPB？

把 `plugins.ini` 里 `yapb.dll` 那行取消注释、注释 `fapb.dll` 那行，然后跑一次
`doctor.py` 确认只有一套 Bot 核心。**任何情况下都不要同时启用两套会补位的核心。**

同时清掉 `config.cfg` / `userconfig.cfg` 里残留的 `bind ... "yb menu"` 或
`bind ... "yb cmenu"`，否则同一个键可能同时触发 YAPB 和 FAPB 的菜单。

---

## 目录结构

```
fapb-kickfix/
├─ README.md
├─ CHANGELOG.md
├─ LICENSE
├─ docs/
│  ├─ diagnosis.md          0x18173 崩溃取证（历史，仍然有效）
│  ├─ fapb-dll-repair.md    导入表损坏、重建过程、哈希、ABPB 细节
│  ├─ abpb-compat.md        ABPB 检测表分析 + 两种共存模式
│  └─ menu-conflict.md      YAPB / FAPB 菜单冲突与“前导空格伪注释”问题
└─ scripts/
   ├─ fapb_rebuild.py       重建 DLL（1.2.0 核心）
   ├─ install.ps1
   ├─ restore.ps1
   ├─ fapb_patch.py         旧 5 字节补丁的查看/撤销
   ├─ abpb_compat.py
   ├─ fapb_abpb_setup.ps1
   └─ doctor.py
```

> 本仓库**不包含** `fapb.dll` / `ABPB.dll` 本体。FAPB 是 YaPB 2.55b 的改名分支、
> ABPB 是 AiBo 4.3.3 的改名分支（均为 GPL 系），重新分发二进制请遵守其许可证并保留
> 原作者署名。这里只放重建工具、差异补丁与文档。

---

## License

脚本：MIT（见 [LICENSE](LICENSE)）。
FAPB / YaPB：遵循其原始许可证（YaPB，GPL）。
