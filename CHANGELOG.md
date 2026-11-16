# Changelog

## 1.2.0 — 2026-11-16

找到并修复了 1.0/1.1 没有触及的根因：**FAPB 1.6 发布版 `fapb.dll` 的导入表是坏的**。
5 字节补丁降级为兼容选项，重建 DLL 才是正式修复。

### 修复
- **`fapb.dll` 导入表**：发布版 DLL（`606E7A6A…3553`，643072 字节）是 UPX 转储产物，
  PE 导入目录只描述 UPX stub；真实代码使用的 84 个 `kernel32` 导入槽（IAT，RVA `0x5A000`）
  仍保存着转储进程的旧地址。加载器不会修正它们，导致 `badf load`、堆损坏和踢 BOT 崩溃。
- **`scripts/fapb_rebuild.py`（新增）**：用固定上游素材重建正常 PE：
  - 固定 `Faker1147/FAPB@4fae46026d296946c196d4c1bcc25ead3036a9bb`；
  - 校验 `yapb.dll` / `yapb_b1.bin` / `yapb_b2.bin` 的 SHA-256；
  - 从两份转储恢复 **9796 条重定位**；
  - 新建 `.idata`：1 个 `KERNEL32.dll` 描述符、84 条 hint/name、`FirstThunk=0x5A000`；
  - 输出 SHA-256 固定为 `9AFDAA67…8C96`（645120 字节），不符则报错；
  - 支持 `--download`、`--artifacts`、`--install`（自动备份原 DLL）。
- **5 字节补丁废弃**：`fapb_patch.py` 现在识别四种状态（released / released-legacy-patched /
  rebuilt / rebuilt-legacy-patched），在重建版上**拒绝** `--apply`，并支持 `--revert`。
  重建版 + 旧补丁（`9F2EBB5A…1CAD`）实测踢 BOT 时崩在 `hl.exe` `EIP 0x005381E0`。
- **`install.ps1`**：默认不再给 DLL 打 5 字节补丁；新增 `-RebuildDll`、`-ArtifactsDir`、
  `-LegacyPatch`。检测到重建版误打补丁时会自动 revert。
- **`fapb_abpb_setup.ps1`**：默认只检查 DLL，不再自动打补丁；新增 `-RebuildFapb`、
  `-ArtifactsDir`、`-LegacyFapbPatch`；`-NoFapbPatch` 仍保留为显式跳过。
- **`doctor.py`**：区分发布版 / 重建版 / 误打补丁，给出对应修复命令；不再把 repack 预置的
  `fb_followuser 99` 计入问题。

### 新增
- `docs/fapb-dll-repair.md` — 导入表诊断、重建布局、哈希、ABPB 偏移、quota 夹取说明。
- `abpb_compat.py` 支持 **ABPB 4.3.3-abpb.1** 和 **abpb.2** 两个构建
  （abpb.2 补丁后 `F2750780…A254D`）。
- ABPB 运行时 `abpb_quota` 会被夹到 `maxplayers` 的说明（实测 8 / 12 / 20）。

### 变更
- README 重写：以“重建导入表”为主线，5 字节补丁移到历史/兼容章节。
- `fapb_patch.py` 的 `--apply` 现在会打印废弃警告；重建版直接拒绝。
- 新增 `.gitignore` 条目：`tools/artifacts/`、`dist/`。

### 验证
- 重建版在 HLDS 中：`meta list` 显示 `FAPB RUN v2.55b`；`fapb add` + `fapb kickall` 不崩。
- 重建版与 ABPB 4.3.3-abpb.2 共存：`fapb kickall`、ABPB 正常补位均通过。
- `doctor.py`：`state: rebuilt`，结论“一切正常”。

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
