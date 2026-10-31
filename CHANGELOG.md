# Changelog

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
