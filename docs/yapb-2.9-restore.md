# YAPB 2.9 恢复说明（repack 原版 DLL）

> 适用：`Counter Strike 8684(多BOT版)` 这类自带 YAPB 2.9 的整合包。
> 症状：`plugins.ini` 启用 `yapb.dll` 后，控制台报
> `couldn't exec addons/yapb/config/yapb.cfg`，`yapb.txt` 反复写
> `Name configuration file not found.` / `General configuration file not found.`。
> 原因通常不是配置写错，而是 **`addons/yapb/bin/yapb.dll` 被换成了 YaPB 2.55b**。

---

## 1. 两套目录不能混用

YaPB 2.9 和 2.55b 的 DLL 文件名完全一样，但读取的配置目录不同：

| DLL | 版本 | 配置目录 | 典型文件名 |
| --- | --- | --- | --- |
| repack 原版 | **2.9** | `addons/yapb/conf/` | `yapb.cfg`、`general.cfg`、`chatter.cfg`、`lang/chs_lang.cfg` |
| 旧构建 | **2.55b** | `addons/yapb/config/` | `yapb.cfg`、`general.cfg`、`chatter.cfg`、`language/*.cfg` |

2.55b 的 DLL 放进 2.9 的目录后，会去找 `addons/yapb/config/yapb.cfg`：

```text
couldn't exec addons/yapb/config/yapb.cfg
```

随后 `yapb.txt` 里会出现：

```text
[..] Error: Name configuration file not found.
[..] Error: Chat file not found.
[..] Error: General configuration file not found. Loading defaults
[..] Error: Couldn't open chatter system configuration
[..] Error: de_dust2_2x2.pwf does not exist
```

这不是“少装了一个 cfg”，而是 **DLL 和目录结构代际不匹配**。把 2.9 的 DLL 放回去，
`conf/` 下的配置和 `data/` 下的路点就能正常读取，`yapb.txt` 也不再新增这些错误。

---

## 2. 认准真正的 2.9 DLL

本机 repack 压缩包 `D:\Counter Strike 8684(多BOT版).zip` 里的原版文件：

```text
Counter Strike 8684(多BOT版)/cstrike/addons/yapb/bin/yapb.dll
```

| 项 | 值 |
| --- | --- |
| 大小 | `741152` 字节 |
| SHA-256 | `3B9FDE328872D19D33FD7ADC08597F3F720613BCFC7CCCF25B690A29467F27D4` |
| 文件版本 | `2.9` |
| 产品版本 | `2.9` |
| 描述 | `Yet Another POD-Bot v2.9 - The Counter-Strike Bot` |
| 构建号 | `5395` |
| 编译时间 | `Oct 28 2018, 16:27:19` |
| Git Hash | `5f6a1638d6ec6866db86d898557d20ed3ac8387d` |

被误装进来的 2.55b：

| 项 | 值 |
| --- | --- |
| 大小 | `188416` 字节 |
| SHA-256 | `00DFB600184F4819623701A0450FEC39CFF73CAE270862A7FB52C51EF93080C2` |
| 文件版本 | `2.55b` |
| 描述 | `YaPB v2.55b - The Counter-Strike 1.6 Bot` |

加载成功后，控制台第一行应该是：

```text
[YAPB] Bot v2.9.0.5395 Loaded. Game detected as Counter-Strike: v1.6 (BV) (SVC)
```

`meta info yapb` 应显示 `version: 2.9`、`date: Oct 28 2018`、`url: https://yapb.ru/`；
`yb version` 会打印完整的 Build 5395 与 Git Hash。

---

## 3. 从 repack 压缩包恢复 DLL

> 先把正在运行的 HLDS / 游戏完全退出，避免 DLL 被占用。

```powershell
$game = 'D:\Counter Strike 8684(多BOT版)\Counter Strike 8684(多BOT版)'
$zip  = 'D:\Counter Strike 8684(多BOT版).zip'
$dst  = Join-Path $game 'cstrike\addons\yapb\bin\yapb.dll'

# 1) 备份当前 DLL
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bakDir = Join-Path $game "cstrike\addons\yapb\backup\yapb-$stamp"
New-Item -ItemType Directory -Path $bakDir -Force | Out-Null
Copy-Item -LiteralPath $dst -Destination (Join-Path $bakDir 'yapb.dll') -Force

# 2) 从原版压缩包取出 2.9 DLL
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $entry = $z.Entries | Where-Object {
        $_.FullName -eq 'Counter Strike 8684(多BOT版)/cstrike/addons/yapb/bin/yapb.dll'
    }
    if (-not $entry) { throw '压缩包里找不到 addons/yapb/bin/yapb.dll' }
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dst, $true)
} finally {
    $z.Dispose()
}

# 3) 校验
$f = Get-Item -LiteralPath $dst
"{0} bytes  {1}" -f $f.Length, (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
$f.VersionInfo | Select-Object FileVersion, ProductVersion, FileDescription
```

期望输出：

```text
741152 bytes  3B9FDE328872D19D33FD7ADC08597F3F720613BCFC7CCCF25B690A29467F27D4
2.9           2.9           Yet Another POD-Bot v2.9 - The Counter-Strike Bot
```

目录应为：

```text
cstrike/addons/yapb/
├─ bin/yapb.dll          <- 2.9，741152 字节
├─ conf/                 <- 2.9 配置（不是 config/）
│  ├─ yapb.cfg
│  ├─ general.cfg
│  ├─ chatter.cfg
│  └─ lang/
└─ data/                 <- 路点 / pwf / 日志
```

`conf/yapb.cfg` 是用户配置，不要用压缩包里的原版整个覆盖。本机当前配置与压缩包原版
**只差最后一行按键**：

```diff
-bind "-" "yb menu"
+bind "N" "yb menu"
```

保留本机的 `bind "N"` 即可。

---

## 4. 测试时只启用 YAPB 一套核心

YAPB 2.9 与 FAPB / ABPB 都是同源 Bot 管理器，**不能同时补位**。平时默认仍是
FAPB + ABPB；只有测试 YAPB 时，才临时把 `plugins.ini` 收敛为 AMXX + YAPB：

```ini
;; Metamod plugins.ini —— 临时测试
win32 addons/amxmodx/dlls/amxmodx_mm.dll
win32 addons/yapb/bin/yapb.dll
```

测试完成后必须恢复默认的 FAPB + ABPB 配置（见第 6 节）。

启动 HLDS 后依次确认：

```text
meta list          -> yapb.dll  RUN  v2.9
meta info yapb     -> version: 2.9 / date: Oct 28 2018
yb version         -> Version: 2.9 (Build: 5395)
```

### 4.1 验证 bot 真的能进来

从服务端控制台执行 `yb add` / `yb add_t` / `yb add_ct` 只是把 bot 排进连接队列；
`wait` 在 GoldSrc 里**只等 1 帧**，不是睡眠。紧接着执行 `status` 会看到 0 人，
再执行 `yb kickall` 还会把刚排队的 bot 清掉，容易误判成“2.9 加不了 bot”。

推荐用 `yb_quota` 做自动补位测试：在 `cstrike/server.cfg` 末尾临时加：

```cfg
echo YAPB_QUOTA_BEGIN
yb_quota 4
yb_autovacate 0
echo YAPB_QUOTA_END
```

启动服务器并保持约 25 秒，`qconsole.log` 里应出现：

```text
YAPB_QUOTA_BEGIN
YAPB_QUOTA_END
Connecting Bot...
Connecting Bot...
Connecting Bot...
Connecting Bot...
yapb// <bot 的聊天消息>
```

这说明 2.9 不仅加载成功，而且能正常创建并接入 bot。测试完把 `server.cfg`
恢复原样（不要留下 `yb_quota 4`）。

> `yb cmenu` 在服务端控制台会回 `You're dead, and have no access to this menu`，
> 这是正常的：菜单命令需要由一个活着的玩家执行。

### 4.2 命令别名

从 2.9 DLL 的字符串表可以确认这些别名（`yb <别名>`）：

| 功能 | 命令 |
| --- | --- |
| 加一个 bot | `addbot` / `add` |
| 加 T / CT | `addbot_t` / `add_t`、`addbot_ct` / `add_ct` |
| 加“高手”bot | `addbot_hs` / `addhs` |
| 踢 T / CT | `kickbot_t` / `kick_t`、`kickbot_ct` / `kick_ct` |
| 杀 T / CT | `killbots_t` / `kill_t`、`killbots_ct` / `kill_ct` |
| 踢全部 | `kickall` |
| 补满服务器 | `fillserver` / `fill` |
| 主菜单 / 命令菜单 | `menu` / `botmenu`、`cmenu` / `cmdmenu` |
| 路点菜单 | `wp menu` |

---

## 5. 日志怎么读

| 文件 | 作用 |
| --- | --- |
| `yapb.txt`（游戏根目录） | YAPB 启动/配置错误日志；2.9 正常加载后不再新增 2.55b 那组错误 |
| `cstrike/addons/yapb/data/logs/yapb.log` | 旧版留下的日志，2.9 默认不一定写入，mtime 不变是正常的 |
| `qconsole.log` | HLDS 控制台日志；用 `-condebug` 启动才有，跨会话追加，按字节偏移截取本次运行 |

判断 2.9 是否真正读到了 `conf/`，最直接的证据就是 `yapb.txt` 的修改时间不再变化，
且 `qconsole.log` 中没有 `couldn't exec addons/yapb/config/yapb.cfg`。

---

## 6. 测试后恢复默认（FAPB + ABPB）

```powershell
$game = 'D:\Counter Strike 8684(多BOT版)\Counter Strike 8684(多BOT版)'

# 1) 恢复 server.cfg（去掉 yb_quota / echo 测试行）
Copy-Item -LiteralPath `
  'C:\path\to\server.cfg.bak' `
  -Destination (Join-Path $game 'cstrike\server.cfg') -Force

# 2) 恢复 FAPB + ABPB 的 plugins.ini
Copy-Item -LiteralPath `
  (Join-Path $game 'cstrike\addons\fapb\backup\abpb-20261117-160523\plugins.ini') `
  -Destination (Join-Path $game 'cstrike\addons\metamod\plugins.ini') -Force

# 3) 体检
python .\scripts\doctor.py --game-dir $game
```

恢复后的 `plugins.ini` 应只有两套活动核心：

```ini
win32 addons/amxmodx/dlls/amxmodx_mm.dll

; win32 addons/csbot_enabler/csbot_enabler_mm.dll
; win32 addons/sypb/dlls/sypb.dll
; win32 addons/podbot/podbot_mm.dll
; win32 addons/yapb/bin/yapb.dll
; win32 addons/ebot/dlls/ebot.dll

win32 addons/fapb/dlls/fapb.dll
win32 addons/ABPB/bin/ABPB.dll
```

`doctor.py` 应输出：

```text
OK  共存模式: FAPB + ABPB 同时加载 (只允许一方补位)
    补位方: ABPB
结论: 一切正常
```

---

## 7. 常见坑

- **不要把 2.55b 的 `config/` 改名成 `conf/` 混用**：文件名相近但格式/键名并不完全兼容，
  正确做法是换回 2.9 的 DLL。
- **不要在 FAPB / ABPB 还在 `plugins.ini` 里活动时启用 YAPB**：三套同源核心会抢菜单、
  抢 `menuselect`，甚至同时补位挤爆 edict。
- **不要看到 `status` 0 人就判定失败**：先给 bot 连接时间，或用 `yb_quota` 观察
  `Connecting Bot...`。
- **不要覆盖 `conf/yapb.cfg` 的按键绑定**：本机使用的是 `bind "N" "yb menu"`。
- **`yb` 菜单命令需要玩家**：服务端控制台执行 `yb cmenu` 报 `You're dead` 是预期行为。
