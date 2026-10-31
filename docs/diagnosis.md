# 取证记录：fapb.dll+0x18173 读访问冲突

本文是结论的依据，记录**怎么定位**到那条指令，以及为什么认为补丁是安全的。
环境：Windows 11（WOW64），CS 1.6 repack `Counter Strike 8684(多BOT版)`，Metamod 1.19，AMXX 1.8.1。

---

## 1. 现场：事件查看器

七次崩溃记录完全一致：

```
出错应用程序名称: hl.exe, 版本: 1.1.1.1, 时间戳: 0x5f28cd59
出错模块名称:     fapb.dll, 版本: 0.0.0.1966, 时间戳: 0x4a2d569d
异常代码:         0xc0000005
错误偏移:         0x00018173
```

固定偏移说明是**同一条指令**，不是随机内存踩踏。

## 2. 现场：WER 转储

`%LOCALAPPDATA%\CrashDumps\hl.exe.*.dmp`（共 6 份，`hl.exe.14348.dmp` 等）。

解析 `MINIDUMP_EXCEPTION_STREAM`：

```
EXCEPTION: code=0xc0000005 address=0x2ef68173
  params: 0x0(read), 0x30376b8(address)
registers: Edi=0x3207eaf0 Esi=0 Eax=0x11360684 Edx=0x03037620 Ecx=0x2f687c18 Eip=0x2ef68173 Esp=0x1afc48
```

- `0x2ef68173 - fapb.dll base 0x2ef50000 = 0x18173` ✔ 与事件日志一致
- 访问类型 `0` = 读，出错地址 `0x030376b8`
- `Edx = 0x03037620`，而 `0x03037620 + 0x98 = 0x030376b8` —— 正好是出错地址

再看 6 份转储里 `fapb.dll+0xB3548` 的值（`gpGlobals` 的存放位置）：

| 转储 | fapb 基址 | gpGlobals | 出错地址 |
| --- | --- | --- | --- |
| hl.exe.5580.dmp | 0x2F140000 | 0x03217620 | 0x032176b8 |
| hl.exe.23256.dmp | 0x2CD30000 | 0x03037620 | 0x030376b8 |
| hl.exe.20924.dmp | 0x2CD50000 | 0x03037620 | 0x030376b8 |
| hl.exe.31448.dmp | 0x2D080000 | 0x03037620 | 0x030376b8 |
| hl.exe.10872.dmp | 0x2EF70000 | 0x03037620 | 0x030376b8 |
| hl.exe.14348.dmp | 0x2EF50000 | 0x03037620 | 0x030376b8 |

`0x03037620` 在 `metamod.dll`、`yapb.dll`、`podbot_mm.dll`、`ebot.dll`、`sypb.dll`、
`csbot_enabler_mm.dll`、`amxmodx_mm.dll` 的 `.data` 里都能搜到同一个值 —— 这是
**Metamod 发给每个插件的同一个 `globalvars_t*`**，不是 FAPB 自己算错的偏移。

> 关键推理：`0x3037620` 与 `0x30376B8` 在**同一个 4 KB 页**（`0x3037000`）。
> 如果 `0x3037620` 指向的是一块真实分配，那么同页的 `+0x98` 必然可读。
> 现在它不可读，说明**整页都没映射** —— `gpGlobals` 是悬垂指针，内存已被回收。

## 3. 现场：这条指令属于谁

对 `fapb.dll`（PE, ImageBase `0x10000000`）做静态反汇编，`0x100180E0` 是
`CBot::~CBot()`：

- 开头 `push -1 / push 0x1005707C / mov eax, fs:[0]` —— MSVC 的 SEH 函数框架
- 中间遍历一个 `std::vector` 风格的全局表（`0x100B35BC`，元素 16 字节，`+0xC` 是 `bool used`）
- 用 `strcmp` 把表里的名字和 `STRING(m_pEdict->v.netname)` 比对，命中就把 `used` 清零
- 结尾 `lea eax,[edi+0x580] ... call` 析构成员

谁调用它（`E8` 相对调用扫描）：

| 调用点 | 函数 |
| --- | --- |
| `0x100187F8` | `CBotManager::RemoveAllBots()`（遍历 32 个槽位） |
| `0x10018833` | `CBotManager::RemoveBot(index)` |
| `0x1001889A` | `CBotManager::~CBotManager()` |

也就是说：**踢 Bot（菜单 3/4/5）、`fapb kick`、`fapb kickall`、换图清理** 都会走到这里。

`0x100247F0` 是导出函数 `GiveFnptrsToDll`（导出表可见），里面：

```asm
10024852  BF 00300B10      mov  edi, 0x100B3000
10024857  F3A5             rep movsd                ; 复制 enginefuncs 到自己的 .data
10024859  891D 48350B10    mov  [0x100B3548], ebx   ; gpGlobals = 参数 2
```

`g_pGlobals` 全模块只有这一个写入点，读取点 57 处，其中 4 处会 `+0x98` 取 `pStringBase`。

## 4. 排除法

| 猜测 | 结论 |
| --- | --- |
| DLL 重定位表被改坏（重打包导致绝对地址没修正） | 否。`.reloc` 有 9796 条 HIGHLOW，`mov edx,[0x100B3548]` 的立即数 `RVA 0x1816F` **有**重定位项；`.text` 里 3338 处绝对数据引用只有 3 处"缺"，且都不是真指针 |
| `gpGlobals` 为 NULL | 否。值为 `0x3037620`，非 0；且和 Metamod 各插件里的值一致 |
| `m_pEdict` 为空/野指针 | 否。那样会崩在 `0x18167`（读 `[edx+0x1D0]`），不是 `0x18173` |
| 名字表为空导致越界 | 否。为空时 `0x18126` 直接跳到 `0x181E0`，根本不会执行到 `0x18173` |
| **`gpGlobals` 指向的内存已被回收** | **是**。同页不可读 + 多份转储值一致 |

## 5. 为什么会变成悬垂指针

崩溃时的模块列表（同一份转储）：

```
0x60DE0000 csbot_enabler_mm.dll
0x60D00000 sypb.dll
0x2F220000 podbot_mm.dll
0x2F350000 yapb.dll
0x5FC50000 ebot.dll
0x2EF50000 fapb.dll
0x61010000 amxmodx_mm.dll
```

六套 Bot 核心 + AMXX 全部在场，而 `plugins.ini` 也是这么写的（只有 YAPB/EBot 行首多了一个空格，仍然生效）。

FAPB 的 `README_FAPB.txt` 第 7.3 节：

> YAPB、SYPB、FAPB 都属于"Bot 核心"，都会接管 Bot 管理、引擎回调、say/menuselect 等事件。
> 同一时间只能启用一套 Bot 核心 …… 同时加载两套 Bot 核心会出现重复 Bot、抢 Hook、菜单错乱甚至崩溃。

同一份包里的 `BUILD_INFO.txt` 也把"offset 0x18173 崩溃"归因于"多套 Bot 核心同时加载导致 FAPB 的运行时指针失效"，
并说明 `install_fapb.ps1` 会注释掉冲突行 —— 但**这个脚本从未在这个安装上执行过**
（`cstrike\addons\metamod\` 下没有 `plugins.ini.fapb.bak`，`plugins.ini` 的修改时间也晚于安装脚本）。

所以：**配置从未真正修好，崩溃自然一直在。**

## 6. 补丁为什么安全

```asm
1001811D  A1 DC350B10   mov eax,[0x100B35DC]     ; 取名字表条目数
10018122  33F6          xor esi,esi
10018124  85C0          test eax,eax
10018126  0F84B4000000  je  0x100181E0           ; 0 条 → 直接出口
```

`0x1001811D` 改成 `E9 BE000000`（`jmp 0x100181E0`）后：

- 目标 `0x100181E0` 正是原来的循环出口：`mov [esp+0x18],-1`（SEH 复位）→
  `lea eax,[edi+0x580]` → 析构成员 → `pop`/`ret`，**不依赖循环里的任何寄存器**
- `esi` 只在该循环内使用，函数末尾 `pop esi` 直接丢弃，跳过它无副作用
- `0x1001811D` 不是任何跳转的目标（工具会全 `.text` 扫描 `E9/EB/E8/0F 8x` 的 rel32/rel8 目标来确认，
  发现被引用就拒绝打补丁）
- 打完 `fapb.dll` 与原始文件**只差 5 个字节**（偏移 `0x1751D..0x17521`），
  工具用 SHA-256 双向校验：`606e7a6a…3553` ⇄ `18e536c0…2152`

### 代价

名字槽不再被释放。名字池 146 条、每张图重新加载，实际影响是"同一张图里反复踢上百个 Bot 之后
Bot 名字可能重复"，**不会崩**。用 `fapb_patch.py --revert` 可还原成原始字节。

## 7. 复现命令

```powershell
# 找崩溃
Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error'} -MaxEvents 20 |
  Where-Object { $_.Message -match 'fapb' } |
  ForEach-Object { $_.Message }

# 看转储
python ..\..\scripts\doctor.py --game-dir "D:\Counter Strike 8684(多BOT版)" --dumps
```

分析用的脚本（PE 解析、反汇编、转储解析）在本次排查中是一次性的，核心逻辑已经收敛进
`fapb_patch.py`（PE 映射 + 分支目标扫描 + 字节校验）和 `doctor.py`（转储签名识别）。
