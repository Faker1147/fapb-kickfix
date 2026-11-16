# FAPB × ABPB 共存说明

ABPB 4.3.3 是 AiBo 4.3.3（YaPB 分支）的换名版；FAPB 1.6 是 YaPB 2.55b 的换名版。
两者目录、命令、cvar 前缀都不冲突，可以**同时安装**，但同一时间只能有**一个**在管理机器人
（两个都补位会抢 edict / 挤爆 32 槽，最终服务端直接退出）。

ABPB 自带一个"检测到别的 BOT 就让位"的守卫，但它**对 FAPB 是失效的** —— 这就是本文要修的东西。

---

## 1. 为什么 ABPB 检测不到 FAPB

ABPB.dll 里硬编码了一张"其他 BOT"的 cvar 名表（`.rdata`，每项 8 字节
`{const char *name; uint32 len;}`）：

```text
0x27D748  -> "yb_quota"        len 8      0x27D750  -> "yb_version"     len 10
0x27D758  -> "yapb_quota"      len 10     0x27D760  -> "yapb_version"   len 12
0x27D768  -> "sypb_quota"      len 10     0x27D770  -> "sypb_version"   len 12
0x27D778  -> "fapb_quota"      len 0x0A   0x27D780  -> "fapb_version"   len 0x0C   <-- 问题在这
0x27D788  -> "ebot_quota"      len 10     0x27D790  -> "ebot_version"   len 12
...
```

它找的是 `fapb_quota` / `fapb_version`。但 FAPB 1.6（YaPB 2.55b 改名前缀）实际注册的是
**`fb_quota` / `fb_version`**：

```text
$ strings fapb.dll | grep '^fb_'
fb_autovacate  fb_botbuy  fb_chat ... fb_quota ... fb_version ...
```

名字对不上 → 守卫永远认为"没有别的 BOT" → `abpb_quota` 保持 31，FAPB 的 `fb_quota`
一旦大于 0，两边同时补位。

> 顺带一提，`yapb_*` 那一对倒是写对了，所以 ABPB 能认出 YaPB，却认不出 FAPB。

## 2. 修法：把表里的名字改成 FAPB 真正的名字

就地改写（等长或更短，不改变文件布局、不碰重定位表）：

| 位置 | 原内容 | 改为 |
| --- | --- | --- |
| `fapb_quota` 字符串 | `"fapb_quota"` | `"fb_quota"` + `00 00` |
| `fapb_quota` 长度 | `0x0A` | `0x08` |
| `fapb_version` 字符串 | `"fapb_version"` | `"fb_version"` + `00 00` |
| `fapb_version` 长度 | `0x0C` | `0x0A` |

两个构建的文件偏移不同：

| 项 | abpb.1 | abpb.2 |
| --- | --- | --- |
| `fapb_quota` 字符串 | `0x27D834` | `0x27D8F4` |
| `fapb_quota` 长度 dword | `0x27D77C` | `0x27D83C` |
| `fapb_version` 字符串 | `0x27D83F` | `0x27D8FF` |
| `fapb_version` 长度 dword | `0x27D784` | `0x27D844` |

长度字段必须同步改：检测代码是把 `{ptr,len}` 当 `string_view` 传递/哈希的
（源码里能看到 `mov [esp+8], <ptr>` / `mov [esp+0xC], <len>` 的成对立即数），
只改字符串不改长度会哈希到 `"fb_quota\0\0"`，依旧匹配不上。

改动一共 **22 个字节**，全在 `.rdata` 的两段字符串和两个长度 dword 里：

| 构建 | 原版 SHA-256 | 补丁后 SHA-256 |
| --- | --- | --- |
| ABPB 4.3.3-abpb.1 | `ff61716f5eb77d17e27d9dc3e696b0944cad1c17ce3a520828e37fab226cd776` | `675a62ad455240c41c50cd2207519c7367a1b7b1043656d9e4d664bff92669ed` |
| ABPB 4.3.3-abpb.2 | `6ce76d06fcfd3198b1d213bb2576dcceaec432c990cd7cdbf00688df5e26abbd` | `f2750780b14655126f0142d691c6ae5c362eaefa12a9e8a216f082d1e80a254d` |

工具会校验原版哈希、校验每个字节、跑 `--dry-run`，并可 `--revert` 精确还原。
未知构建会被拒绝（不会盲改偏移）。

之所以改 ABPB 而不是改 FAPB：`fb_quota` 变 `fapb_quota` 是**变长**（8→10），
字符串池里没有余量，硬改会破坏相邻数据；而 ABPB 那边是**变短**，天然安全。

## 3. 两种共存模式

| | `-Mode abpb`（推荐） | `-Mode fapb` |
| --- | --- | --- |
| 谁补位 | ABPB | FAPB |
| `abpb_quota` | 保持（默认 31） | 强制 `0` |
| `abpb_autovacate` | `1` | `0` |
| `abpb_compat_auto` | `0`（不要被 FAPB 触发让位） | `1`（让位给 FAPB） |
| `fb_quota` | 强制 `0` | 保持 |
| `fb_autovacate` | `0` | `0` |
| 是否需要打 ABPB.dll | 可选（建议打，方便识别/切换模式） | 需要（守卫才会认 FAPB） |

`-Mode abpb` 是"新 BOT 主导"：ABPB 用它的 Human Copycat / 学习 / 聊天，FAPB 只作为
备选保留在 `meta list` 里，不补位也不踢人。`-Mode abpb` 下保持 `abpb_compat_auto 0`，
避免打了守卫补丁的 ABPB 把空闲的 FAPB 误判成"正在管理的 BOT"而自动让位。
`-Mode fapb` 是"老 BOT 主导"：ABPB 被完全让位（quota 0），守卫补丁让它即使
`compat_auto 1` 也不会误解锁。

FAPB 侧建议先跑 `fapb_rebuild.py` 换成重建版 DLL；1.2.0 起 `fapb_abpb_setup.ps1` 默认
只检查、不再自动打 5 字节补丁。需要重建时加 `-RebuildFapb`：

```powershell
powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 `
  -GameDir "D:\CS1.6" -Mode abpb -RebuildFapb
```

> **quota 会被夹到 maxplayers**：`ABPB.cfg` 里写 `abpb_quota "31"` 时，运行时实际值
> 不会超过服务器人数上限。实测 `+maxplayers 8/12/20` 对应运行时 `abpb_quota 8/12/20`。
> 这是 ABPB 的正常行为，不是配置没生效。

## 4. 用法

```powershell
# 同时装好 FAPB 和 ABPB（把 ABPB 压缩包的 addons 合并到 cstrike 之后）
powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode abpb -WhatIf
powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode abpb

# 想换 FAPB 主导
powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode fapb

# 只打/撤守卫补丁
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --apply
python .\scripts\abpb_compat.py --dll "...\addons\ABPB\bin\ABPB.dll" --revert
```

脚本会先把 `plugins.ini`、`fapb.dll`、`ABPB.dll`、`fapb.cfg`、`ABPB.cfg` 备份到
`cstrike\addons\fapb\backup\abpb-<时间戳>\`，`restore.ps1` 可以整体回滚。

## 5. 验证

```text
meta list          -> 同时列出 FAPB 与 ABPB
abpb version
fapb version
```

- `-Mode abpb`：`abpb_quota` 为 31（或你设的值），`fb_quota` 为 0；ABPB 正常刷 BOT，FAPB 不补位。
- `-Mode fapb`：`abpb_quota` 为 0，FAPB 补位；ABPB 控制台会打印
  `[ABPB] Other bot system detected (fb_quota)... abpb_quota and abpb_autovacate were set to 0`。

## 6. 注意

- **不要**同时让两个系统都补位。守卫只是兜底，正确做法是显式设 quota。
- ABPB 升级后 `ABPB.dll` 哈希会变，`abpb_compat.py` 会拒绝打补丁（这是故意的），
  重新用 `--dll` 指向新版并核对偏移后再更新脚本。
- 两套 BOT 同时加载意味着两套引擎 Hook（`ClientCommand` / `SayText` / `ServerActivate` 等）。
  ABPB 官方文档也只承诺"可同时安装、单方管理"。如果出现菜单错乱、说话重复之类的怪现象，
  退回 `plugins.ini` 只留一套（上一版 `install.ps1` 做的就是这个）。
- 本文的偏移覆盖 **ABPB 4.3.3-abpb.1** 和 **abpb.2** 两个构建；两者的补丁后哈希
  分别是 `675a62ad…669ed` / `f2750780…254d`。其它版本偏移不同，不要套用。
- 1.2.0 起 FAPB 使用重建版 DLL（`9afdaa67…8c96`），**不要**再给它打 0x1811D 的
  5 字节补丁；重建版 + 补丁会踢 BOT 崩溃（见 `docs/fapb-dll-repair.md`）。
