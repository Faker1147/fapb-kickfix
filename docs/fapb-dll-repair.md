# FAPB 1.6 DLL 导入表修复记录

本文记录 1.2.0 的根因分析：为什么 FAPB 1.6 发布版 `fapb.dll` 会 `badf load` / 堆损坏 /
踢 BOT 崩溃，以及 `scripts/fapb_rebuild.py` 如何重建一个可正常加载的 PE。

- 发布版：`606E7A6A…3553`，643072 字节
- 重建版：`9AFDAA67…8C96`，645120 字节
- 重建版 + 旧 5 字节补丁：`9F2EBB5A…1CAD`（**禁止使用**，踢 BOT 会崩）

> FAPB 1.2–1.6 的发布 DLL 是同一份文件；只改版本号不改二进制。

---

## 1. 发布版的 PE 事实

发布版是 **UPX 转储产物**：

- PE 头里的导入目录只描述 UPX stub 自己的导入；
- 解包后的代码使用 `kernel32` 的 **84 个函数**；
- 这些函数的名字表还在文件里：RVA `0xBF008`，格式为 `01 <name> 00`
  （`GetProcAddress` … `SetEnvironmentVariableA`）；
- 真实代码调用的 IAT 在 RVA `0x5A000`，共 84 个槽位；
- 这些槽位里保存的是**转储进程里已经解析好的地址**，不是待加载器填充的 RVA/0。

加载 `fapb.dll` 时，Windows 只按 PE 导入目录工作，不会去 `0xBF008` 找名字，也不会
重写 `0x5A000`。于是 FAPB 一调用 API 就跳到旧进程的地址空间：

- 轻则 `badf load`；
- 重则堆损坏、随机崩溃；
- 踢 BOT 时走到 `CBot::~CBot()` 的 `gpGlobals` 访问，就是事件日志里的 `0x18173`。

这也解释了为什么“只注释掉其它 Bot 核心”并不能彻底修好：配置只减少了触发概率，
DLL 的导入表仍然是坏的。

## 2. 上游重建素材

FAPB 仓库（固定 commit `4fae46026d296946c196d4c1bcc25ead3036a9bb`）里有：

| 文件 | 大小 | SHA-256 | 用途 |
| --- | --- | --- | --- |
| `tools/artifacts/yapb.dll` | 188416 | `00DFB600…80C2` | UPX 打包的 YaPB 2.55b |
| `tools/artifacts/yapb_b1.bin` | 811008 | `3A49067E…F075` | 内存转储 @ `0x10000000` |
| `tools/artifacts/yapb_b2.bin` | 811008 | `247DA26C…65BC` | 内存转储 @ `0x0A630000` |

两份转储都覆盖 `0xC6000` 字节的镜像。b1 是首选基址，b2 被加载到另一个基址，
两者相减就能恢复重定位信息。

## 3. 重建步骤

### 3.1 恢复重定位（9796 条）

对 `.text` 范围内每个 4 字节 dword：

```text
v1 = dword(b1, off)
v2 = dword(b2, off)
if 0x10000000 <= v1 < 0x100C6000 and (v2 - v1) == (0x0A630000 - 0x10000000):
    relocation at off
```

得到 **9796** 条 HIGHLOW（type 3）项，按 4 KB 页分组写入 `.reloc`。
最终 `.reloc` vsize = `0x5028`，raw = `0x5200`。

> 这一步很关键：HLDS 里首选基址 `0x10000000` 已被 `vgui.dll`（大小 `0x63000`）占用，
> FAPB 实际加载到 `0x08290000`。没有重定位表，所有绝对地址都会指错。

### 3.2 新建导入表

`.idata` 布局：

```text
0xCC000  IMAGE_IMPORT_DESCRIPTOR[0]   -> KERNEL32.dll
0xCC014  IMAGE_IMPORT_DESCRIPTOR[1]   -> 全 0（结束）
0xCC028  INT (OriginalFirstThunk)     -> 84 个 hint/name RVA + 0
0xCC17C  "KERNEL32.dll\0"
0xCC18B  84 条 IMAGE_IMPORT_BY_NAME   -> <WORD 0> <name> \0
```

描述符：

```text
OriginalFirstThunk = 0xCC028
TimeDateStamp      = 0
ForwarderChain     = 0
Name               = 0xCC17C
FirstThunk         = 0x5A000   <-- 代码原本就在用的 IAT
```

导入目录大小 = `40`（2 个描述符 × 20 字节）。

转储里的名字是 `01 <name> 00`（只有 1 字节标志，没有真正的 hint word）；
重建时必须合成标准的 `<WORD hint=0> <name> 00`，否则加载器解析会错位。

### 3.3 区段布局

| 区段 | RVA | vsize | raw | rawsize |
| --- | --- | --- | --- | --- |
| `.text` | `0x1000` | `0x96000` | `0x400` | `0x96000` |
| `.data` | `0x97000` | `0x2D000` | 0 | 0 |
| `.rsrc` | `0xC4000` | `0x2000` | `0x96400` | `0x1A00` |
| `.reloc` | `0xC6000` | `0x5028` | `0x97E00` | `0x5200` |
| `.idata` | `0xCC000` | `0x785` | `0x9D000` | `0x800` |

入口点重建为 `0x4437B`。`.text` 来自 b1，`.rsrc` 来自打包文件，二者都做
`YAPB → FAPB` 品牌替换（含 `yb_ → fb_`、UTF-16 字符串；保留 `YaPB Development Team`
的原始署名）。

最终输出 645120 字节，SHA-256：

```text
9afdaa6796e59026bdd65425a29ab46429aee11d9fee1205ff05351b2dd08c96
```

## 4. 为什么旧 5 字节补丁在重建版上会崩

旧补丁把 `CBot::~CBot()` 的名字槽释放循环整段跳过：

```diff
- 1001811D  A1 DC350B10   mov eax,[0x100B35DC]
+ 1001811D  E9 BE000000   jmp 0x100181E0
```

在发布版上它“碰巧”能阻止 `0x18173` 的读访问，但析构函数的后续清理并没有按原逻辑完成。
放到重建版上，踢 BOT 时实测：

- 异常 `0xC0000005`
- `EIP = 0x005381E0`（`hl.exe` 内）
- 栈回溯可见 `~CBot` 位于 `fapb+0x18838`
- 同一操作在**未打补丁的重建版**上正常

因此 `fapb_patch.py` 现在会在重建版上拒绝 `--apply`，只允许 `--revert`。

## 5. 验证

在 HLDS（`hlds.exe`，`+maxplayers 12`，`de_dust2`）中：

```text
meta list
  [2] FAPB  RUN  -  fapb.dll  v2.55b  ini  Start Never

fapb add 2 t
fapb add 2 ct
fapb kickall
  [FAPB] Bots are removed from server.
  [FAPB] Bot 'FAPB | Kshap' kicked
```

- 服务端不退出；
- `%LOCALAPPDATA%\CrashDumps` 无新 `hl.exe.*.dmp`；
- 与 ABPB 4.3.3-abpb.2 共存时，`fapb kickall` 同样通过；
- 加载基址 `0x08290000`（`vgui.dll` 占用了 `0x10000000`），重定位正常。

另外用重建逻辑处理 YaPB 2.55b 打包件并作为 `yapb.dll` 加载，`yapb kickall` 也通过，
说明问题不在“FAPB 改名”，而在导入表/重定位本身。

## 6. ABPB 守卫补丁（abpb.1 / abpb.2）

`abpb_compat.py` 把 ABPB 检测表里的 `fapb_*` 改成 FAPB 实际注册的 `fb_*`。
两个构建的偏移不同：

| 项 | abpb.1 | abpb.2 |
| --- | --- | --- |
| `fapb_quota` 字符串 | `0x27D834` | `0x27D8F4` |
| `fapb_quota` 长度 dword | `0x27D77C` | `0x27D83C` |
| `fapb_version` 字符串 | `0x27D83F` | `0x27D8FF` |
| `fapb_version` 长度 dword | `0x27D784` | `0x27D844` |

| 构建 | 原版 SHA-256 | 补丁后 SHA-256 |
| --- | --- | --- |
| ABPB 4.3.3-abpb.1 | `FF61716F…CD776` | `675A62AD…669ED` |
| ABPB 4.3.3-abpb.2 | `6CE76D06…ABBD` | `F2750780…A254D` |

具体改动：2 段字符串 + 2 个长度 dword，共 22 字节；全部等长或变短，不移动文件布局。

## 7. ABPB quota 夹取

`cstrike/addons/ABPB/conf/ABPB.cfg` 里常见 `abpb_quota "31"`，但 ABPB 运行时会把它
**夹到服务器 `maxplayers`**。实测：

| 启动参数 | 运行时 `abpb_quota` |
| --- | --- |
| `+maxplayers 8` | 8 |
| `+maxplayers 12` | 12 |
| `+maxplayers 20` | 20 |

所以 cfg 里写 31 并不意味着能刷到 31 个 Bot；要看服务器人数上限。这是 ABPB 的正常行为。

## 8. 复现命令

```powershell
# 下载并重建（输出 dist\fapb.dll）
python .\scripts\fapb_rebuild.py --download

# 本地素材 + 直接安装（自动备份）
python .\scripts\fapb_rebuild.py `
  --artifacts .\tools\artifacts `
  --install `
  --game-dir "D:\Counter Strike 8684(多BOT版)"

# 查看当前 DLL 状态
python .\scripts\fapb_patch.py --game-dir "D:\Counter Strike 8684(多BOT版)"

# 体检
python .\scripts\doctor.py --game-dir "D:\Counter Strike 8684(多BOT版)" --dumps
```

`fapb_rebuild.py` 会校验输入与输出哈希；如果输出不是 `9AFDAA67…8C96`，会以非 0 退出，
除非显式加 `--force`。

## 9. 素材不可达时

`--download` 从固定 commit 的 raw 地址取文件：

```text
https://raw.githubusercontent.com/Faker1147/FAPB/4fae46026d296946c196d4c1bcc25ead3036a9bb/tools/artifacts/<name>
```

如果 GitHub 被墙/DNS 污染，可以手动下载这 5 个文件（3 个二进制 + 2 个 `.txt` sidecar）
放进 `tools/artifacts/`，再运行：

```powershell
python .\scripts\fapb_rebuild.py --artifacts .\tools\artifacts --install
```

脚本不信任文件名，只认 SHA-256 和 sidecar 里的基址。
