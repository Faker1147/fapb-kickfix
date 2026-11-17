# YAPB 菜单与 FAPB CMENU 冲突

## 症状

- 按 `-` / `.` / `,` / `]` 打开 FAPB 控制菜单（`fapb cmenu`）时，YAPB 的菜单也出现，
  或按数字键后执行的是 YAPB 菜单里的项目。
- FAPB 菜单选择一项后立刻被关闭，或者选错项目。
- 服务器日志里同时出现 `[YAPB]` 和 `[FAPB]`，`yapb.txt` 与 `fapb.txt` 的时间戳
  完全同步。
- `meta list` 能看到 YAPB、FAPB，甚至 SYPB / PODBot / EBot / CSBot Enabler 同时加载。

## 根因：前导空格不是注释

`cstrike/addons/metamod/plugins.ini` 里曾经出现这样的写法：

```ini
 win32 addons/yapb/bin/yapb.dll
 win32 addons/sypb/dlls/sypb.dll
 win32 addons/podbot/podbot_mm.dll
 win32 addons/ebot/dlls/ebot.dll
 win32 addons/csbot_enabler/csbot_enabler_mm.dll
```

这些行前面只有一个空格，没有 `;`。Metamod 1.21 在解析前会去掉行首空白，
因此它们**仍然是启用状态**。只有以下两种写法才算注释：

```ini
; win32 addons/yapb/bin/yapb.dll     ; 禁用
// win32 addons/yapb/bin/yapb.dll    ; 禁用
 win32 addons/yapb/bin/yapb.dll     ; 仍然启用！
```

结果服务器一次加载了 7 个 Bot 核心：

```text
CS Bot Enabler v1.0.1
POD-Bot mm
ABPB v4.3.3
[SyPB] Game Registered
[YAPB] Game Registered
[ebot] Game Registered
[FAPB] Game Registered
```

YAPB 和 FAPB 都是 YaPB 2.55b 的改名分支，都会注册自己的菜单命令、维护自己的
`menuselect` 菜单状态。两套菜单同时存在时，数字键会被两边看到，FAPB cmenu 的选择
会被 YAPB 的菜单逻辑覆盖或截走，于是表现为“菜单冲突”。

`cstrike/addons/yapb/conf/yapb.cfg` 里还带有一条建议绑定：

```ini
bind "-" "yb menu"
```

而 `cstrike/config.cfg` / `userconfig.cfg` 把 `-` 绑定到了 `fapb cmenu`。如果 YAPB 的
配置被实际执行，或者玩家的 `userconfig.cfg` 里残留 `yb menu`，同一个键还会直接打开
YAPB 菜单。禁用 YAPB 后这条绑定不会再起作用。

## 修复

只保留 FAPB + ABPB，把其余核心真正注释掉：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\fapb_abpb_setup.ps1 `
  -GameDir "D:\Counter Strike 8684(多BOT版)" -PluginsOnly
```

`-PluginsOnly` 只改 `plugins.ini`，不动 cvars、DLL 和当前补位方。

> 关闭 CSBot Enabler 后，AMXX 的 `zbot_strengthen.amxx` 会因为找不到 ZBot 的 cvars
> 反复打印 `Invalid CVAR pointer`。如果不用 ZBot，把 `addons/amxmodx/configs/plugins.ini`
> 里的 `zbot_strengthen.amxx` 也注释掉即可。

修复后的文件应为：

```ini
win32 addons/amxmodx/dlls/amxmodx_mm.dll

; win32 addons/csbot_enabler/csbot_enabler_mm.dll
; win32 addons/sypb/dlls/sypb.dll
; win32 addons/podbot/podbot_mm.dll
; win32 addons/yapb/bin/yapb.dll
; win32 addons/ebot/dlls/ebot.dll

;; --- FAPB + ABPB (managed by fapb-abpb-setup) ---
win32 addons/fapb/dlls/fapb.dll
win32 addons/ABPB/bin/ABPB.dll
```

然后启动服务器，确认：

```text
meta list
```

应只看到 FAPB 和 ABPB。`yapb.txt` 不再更新，`fapb.txt` 继续更新，说明 YAPB 已不再
加载。

`doctor.py` 也会检查这种“只有前导空格”的伪注释行，并直接提示用
`fapb_abpb_setup.ps1 -PluginsOnly` 修复。

## 验证记录

本机实测：

| 状态 | HLDS 加载的核心 | 结果 |
| --- | --- | --- |
| 修复前 | CS Bot Enabler / PODBot / ABPB / SyPB / YAPB / EBot / FAPB | 菜单冲突，`yapb.txt` 与 `fapb.txt` 同步写入 |
| 修复后 | ABPB / FAPB | 菜单正常，`yapb.txt` 不再更新，`doctor.py` 报告“一切正常” |

注意：不要把 `csbot_enabler` 当成“只是开关”就随手启用；它同样会注册 Hook。
如果确实要回到 YAPB，请只启用 YAPB，并禁用 FAPB，反之亦然。
