# Changelog

## 1.1.0 — 2026-11-11

让 FAPB 与 ABPB 4.3.3 共存。

### 修复
- **ABPB 的 BOT 检测表**：ABPB 守卫找的是 `fapb_quota` / `fapb_version`，
  而 FAPB 注册的是 `fb_quota` / `fb_version`，导致守卫永远检测不到 FAPB。
  `abpb_compat.py` 就地改写 ABPB.dll 的两段 cvar 名与两个长度字段（共 22 字节）：
  - 原版 SHA-256 `ff61716f...cd776` → 补丁后 `675a62ad...92669ed`
  - 等长/变短改写，不动文件布局与重定位；支持 `--dry-run`、`--revert`

### 新增
- `scripts/fapb_abpb_setup.ps1` — 双模式共存安装：
  - `-Mode abpb`：ABPB 补位，FAPB 强制 `fb_quota 0`；
  - `-Mode fapb`：FAPB 补位，ABPB 强制 `abpb_quota 0` + 守卫补丁；
  - 自动注释 YAPB/SYPB/PODBot/EBot/CSBot 等冲突核心，备份全部相关文件。
- `scripts/abpb_compat.py` — ABPB 守卫补丁工具（哈希固定 + 字节校验）。
- `docs/abpb-compat.md` — 检测表结构、偏移、为什么改 ABPB 而不是改 FAPB。
- `restore.ps1` 现在会一并还原 `ABPB.dll` / `fapb.cfg` / `ABPB.cfg`。

### 说明
- ABPB 升级后 ABPB.dll 哈希会变，补丁工具会拒绝执行（安全设计），需要按新版偏移更新。
- 两套 BOT 同时加载仍建议只让一方管理；如出现菜单/说话异常，退回只加载一套。

## 1.0.0 — 2026-10-31

首个版本，针对 `fapb.dll+0x18173` 读访问冲突（`0xC0000005`）。

### 修复
- **配置**：`cstrike/addons/metamod/plugins.ini` 收敛为只启用 `fapb.dll` 一套 Bot 核心；
  YAPB / SYPB / PODBot / EBot / CSBot Enabler 全部注释（文件保留），并处理
  `amxmodx_mm.dll` 与 `amxmodx_bl_mm.dll` 同时加载的重复模块问题。
- **二进制**：`fapb.dll` RVA `0x1811D` 5 字节补丁，`CBot::~CBot()` 跳过会解引用
  失效 `gpGlobals->pStringBase` 的名字槽释放循环。
  - 原始 SHA-256 `606e7a6ab8793553847bcbf2d5665d29edea0b3529eaca537d7e76de7b6e3553`
  - 补丁后 SHA-256 `18e536c00cc58573f3d4d0a803aedc9b4d0e4993654612e62b7c48b756762152`

### 新增
- `scripts/install.ps1` — 备份 + 改配置 + 打补丁，支持 `-WhatIf`、`-NoDllPatch`、`-GameDir`。
- `scripts/restore.ps1` — 从备份还原。
- `scripts/fapb_patch.py` — PE 解析、补丁应用/还原/校验；带字节指纹、分支目标安全检查、`--dry-run`、`--json`。
- `scripts/doctor.py` — 体检：Bot 核心数量、补丁状态、`fapb.cfg` 越界值、WER 转储 `0x18173` 签名扫描。
- `docs/diagnosis.md` — 转储取证、寄存器、指令流、排除法与补丁安全性论证。

### 已知取舍
- 补丁后踢 Bot 不再把名字标记为未占用；名字池 146 条且换图重载，只在单图创建/踢掉上百个 Bot 时才可能见到重名。
- 补丁只覆盖 `CBot` 析构这条路径。根治仍然是"同一时间只启用一套 Bot 核心"，这已由 `install.ps1` 保证。
