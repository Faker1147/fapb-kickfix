<#
.SYNOPSIS
    Make FAPB and ABPB coexist on one CS 1.6 server.

.DESCRIPTION
    ABPB (AiBo 4.3.3 fork) and FAPB (YaPB 2.55b fork) may be *installed*
    side by side, but only ONE of them may manage bots.  This script:

      1. locates the real game root (also handles the common
         "Counter Strike 8684(多BOT版)\Counter Strike 8684(多BOT版)" nesting);
      2. backs up plugins.ini, both DLLs and both configs;
      3. enables exactly FAPB + ABPB and disables YAPB / SYPB / PODBot /
         EBot / CSBot Enabler (and duplicate amxmodx_bl_mm.dll);
      4. forces the "yielding" side to quota 0 / autovacate 0;
      5. patches ABPB.dll so its compat guard can finally see FAPB
         (ABPB looks for "fapb_quota", FAPB uses "fb_quota");
      6. checks fapb.dll: rebuilt (recommended) / released (needs rebuild) /
         harmful legacy patch (auto-reverted).  The deprecated 5-byte patch
         is only applied with -LegacyFapbPatch.

    Close the game first.  Everything is backed up and reversible.

.PARAMETER Mode
    abpb : ABPB manages the bots, FAPB stays loaded but idle.  (recommended)
    fapb : FAPB manages the bots, ABPB yields automatically.

.PARAMETER Quota
    Bot quota for the manager (0..32).  Default 31.  ABPB clamps the
    runtime value to the server's maxplayers.

.PARAMETER NoGuardPatch
    Do not patch ABPB.dll.  -Mode abpb does not strictly need it, but keeping
    it lets ABPB recognise FAPB in the logs / after a mode switch.

.PARAMETER RebuildFapb
    Run fapb_rebuild.py --download --install before finishing.  This is the
    recommended way to fix the released DLL's broken import table.

.PARAMETER ArtifactsDir
    Local folder with yapb.dll / yapb_b1.bin / yapb_b2.bin for -RebuildFapb.

.PARAMETER LegacyFapbPatch
    Apply the deprecated 5-byte kick patch to a released fapb.dll.  Refused
    on rebuilt DLLs (it crashes on bot kick there).

.PARAMETER NoFapbPatch
    Do not inspect or touch fapb.dll at all (legacy flag).

.PARAMETER Force
    Continue even if hl.exe is running.  Not recommended.

.PARAMETER WhatIf
    Report what would change; write nothing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode abpb
    powershell -ExecutionPolicy Bypass -File .\fapb_abpb_setup.ps1 -GameDir "D:\CS1.6" -Mode fapb -WhatIf
#>
[CmdletBinding()]
param(
    [string]$GameDir = "",
    [ValidateSet("abpb", "fapb")]
    [string]$Mode = "abpb",
    [ValidateRange(0, 32)]
    [int]$Quota = 31,
    [switch]$NoGuardPatch,
    [switch]$RebuildFapb,
    [string]$ArtifactsDir = "",
    [switch]$LegacyFapbPatch,
    [switch]$NoFapbPatch,
    [switch]$Force,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-GameRoot {
    param([string]$Path)
    if (-not $Path) { return $false }
    return ((Test-Path -LiteralPath (Join-Path $Path 'hl.exe')) -and
            (Test-Path -LiteralPath (Join-Path $Path 'cstrike')))
}

function Find-GameDir {
    param([string]$Hint)
    $cands = @()
    if ($Hint) { $cands += ($Hint.Trim().Trim('"')) }
    if ($env:FAPB_GAME_DIR) { $cands += $env:FAPB_GAME_DIR }
    foreach ($k in @(
            'HKLM:\SOFTWARE\WOW6432Node\Valve\CounterStrike',
            'HKLM:\SOFTWARE\Valve\CounterStrike',
            'HKCU:\SOFTWARE\Valve\CounterStrike')) {
        try {
            $v = (Get-ItemProperty -Path $k -Name InstallPath -ErrorAction Stop).InstallPath
            if ($v) { $cands += $v }
        } catch { }
    }
    foreach ($d in $cands) {
        if (-not $d -or -not (Test-Path -LiteralPath $d)) { continue }
        if (Test-GameRoot $d) { return (Resolve-Path -LiteralPath $d).Path }
        $hit = Get-ChildItem -LiteralPath $d -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue |
            Where-Object { Test-GameRoot $_.FullName } |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return ""
}

function Write-TextFile {
    param([string]$Path, [string[]]$Lines)
    $text = (($Lines -join "`r`n") + "`r`n")
    [IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Set-CvarLine {
    param([string]$Path, [string]$Name, [string]$Value, [System.Collections.Generic.List[string]]$Log)
    if (-not (Test-Path -LiteralPath $Path)) {
        $Log.Add("skip (missing): $Path")
        return $false
    }
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    $re = '^\s*' + [regex]::Escape($Name) + '(\s|$)'
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $re) {
            $lines[$i] = "$Name `"$Value`""
            $found = $true
        }
    }
    if (-not $found) {
        $lines += ""
        $lines += "// managed by fapb-abpb-setup"
        $lines += "$Name `"$Value`""
    }
    if (-not $WhatIf) { Write-TextFile -Path $Path -Lines $lines }
    $Log.Add(("{0} = {1}   [{2}]" -f $Name, $Value, (Split-Path -Parent $Path)))
    return $true
}

function Get-PythonExe {
    foreach ($c in @('python', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Invoke-PythonTool {
    param([string]$Tool, [string[]]$Arguments)
    $py = Get-PythonExe
    if (-not $py) { throw "python not found; cannot run $Tool" }
    & $py $Tool @Arguments | Out-Host
    return $LASTEXITCODE
}

$GameDir = Find-GameDir -Hint $GameDir
if (-not $GameDir) {
    Write-Host "Cannot locate CS 1.6 (hl.exe + cstrike)." -ForegroundColor Yellow
    $GameDir = (Read-Host "Enter the game root folder (contains hl.exe)").Trim().Trim('"')
    if (-not (Test-GameRoot $GameDir)) { throw "Not a CS 1.6 root: $GameDir" }
}
if (-not (Test-GameRoot $GameDir)) { throw "Not a CS 1.6 root: $GameDir" }

if ((Get-Process -Name hl -ErrorAction SilentlyContinue) -and -not $Force -and -not $WhatIf) {
    throw "hl.exe is running. Close the game first (or pass -Force)."
}

$cstrike = Join-Path $GameDir 'cstrike'
$plugins = Join-Path $cstrike 'addons\metamod\plugins.ini'
$fapbDll = Join-Path $cstrike 'addons\fapb\dlls\fapb.dll'
$abpbDll = Join-Path $cstrike 'addons\ABPB\bin\ABPB.dll'
$fapbCfg = Join-Path $cstrike 'addons\fapb\config\fapb.cfg'
$abpbCfg = Join-Path $cstrike 'addons\ABPB\conf\ABPB.cfg'

foreach ($p in @($plugins, $fapbDll, $abpbDll)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}
if (-not (Test-Path -LiteralPath $abpbCfg)) {
    Write-Warning "ABPB.cfg not found: $abpbCfg (values will be appended where possible)"
}

Write-Host "Game folder : $GameDir" -ForegroundColor Cyan
Write-Host "Mode        : $Mode  (bot manager), quota $Quota" -ForegroundColor Cyan

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $cstrike "addons\fapb\backup\abpb-$stamp"
if (-not $WhatIf) {
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    foreach ($p in @($plugins, $fapbDll, $abpbDll, $fapbCfg, $abpbCfg)) {
        if (Test-Path -LiteralPath $p) {
            Copy-Item -LiteralPath $p -Destination (Join-Path $backupDir (Split-Path -Leaf $p)) -Force
        }
    }
    Write-Host "Backup      : $backupDir" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- plugins ---
$botCoreRe = '^\s*(win32\s+)?addons[\\/](yapb|sypb|podbot|ebot|csbot_enabler|fapb|ABPB)[\\/]'
$fapbRe = 'addons[\\/]fapb[\\/]dlls[\\/]fapb\.dll'
$abpbRe = 'addons[\\/]ABPB[\\/]bin[\\/]ABPB\.dll'
$amxxBlRe = '^\s*win32\s+addons[\\/]amxmodx[\\/]dlls[\\/]amxmodx_bl_mm\.dll'
$amxxMainRe = '^\s*win32\s+addons[\\/]amxmodx[\\/]dlls[\\/]amxmodx_mm\.dll'

$lines = @(Get-Content -LiteralPath $plugins -Encoding UTF8)
$hasAmxxMain = $false
foreach ($l in $lines) { if ($l -match $amxxMainRe) { $hasAmxxMain = $true } }

$out = New-Object System.Collections.Generic.List[string]
$disabled = 0

foreach ($line in $lines) {
    if ($line -match 'fapb-abpb-setup') { continue }
    # Drop every previous FAPB/ABPB line (active or commented); they are
    # re-added once at the end so repeated runs do not accumulate junk.
    if ($line -match $fapbRe -or $line -match $abpbRe) { continue }
    if ($line -match $botCoreRe) {
        if ($line.TrimStart().StartsWith(';')) { $out.Add($line) }
        else { $out.Add('; ' + $line.Trim()); $disabled++ }
        continue
    }
    if ($hasAmxxMain -and ($line -match $amxxBlRe) -and (-not $line.TrimStart().StartsWith(';'))) {
        $out.Add('; ' + $line.Trim())
        $disabled++
        continue
    }
    $out.Add($line)
}
if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne '') { $out.Add('') }
$out.Add(';; --- FAPB + ABPB (managed by fapb-abpb-setup) ---')
$out.Add('win32 addons/fapb/dlls/fapb.dll')
$out.Add('win32 addons/ABPB/bin/ABPB.dll')

if ($WhatIf) {
    Write-Host "[WhatIf] plugins.ini: comment $disabled core(s), enable fapb + ABPB" -ForegroundColor Yellow
} else {
    Write-TextFile -Path $plugins -Lines $out
    Write-Host "plugins.ini : comment $disabled core(s); fapb + ABPB enabled" -ForegroundColor Green
}

# ------------------------------------------------------------------- cvars --
$log = New-Object System.Collections.Generic.List[string]
if ($Mode -eq 'abpb') {
    # ABPB owns the bots; FAPB must not fill or vacate.
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_quota' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_autovacate' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_quota' -Value "$Quota" -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_autovacate' -Value '1' -Log $log)
    # ABPB is the owner.  Keep compat_auto off so the (patched) guard does not
    # make ABPB yield to the idle FAPB installation.
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_compat_auto' -Value '0' -Log $log)
} else {
    # FAPB owns the bots; ABPB must not fill.
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_quota' -Value "$Quota" -Log $log)
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_autovacate' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_quota' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_autovacate' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_compat_auto' -Value '1' -Log $log)
}
Write-Host "cvars       :" -ForegroundColor Green
foreach ($l in $log) { Write-Host "   $l" }

# --------------------------------------------------------------- guard patch -
$guardOk = $true
if ($NoGuardPatch) {
    Write-Host "guard patch : skipped (-NoGuardPatch)" -ForegroundColor DarkGray
} else {
    $mutex = if ($WhatIf) { '--dry-run' } else { '--apply' }
    try {
        $code = Invoke-PythonTool -Tool (Join-Path $scriptRoot 'abpb_compat.py') `
            -Arguments @('--dll', $abpbDll, $mutex)
        if ($code -ne 0) { throw "exit $code" }
    } catch {
        $guardOk = $false
        Write-Warning "ABPB guard patch failed: $_"
        if ($Mode -eq 'fapb') { throw "ABPB guard patch is required in -Mode fapb" }
        Write-Warning "continuing: -Mode abpb does not require the guard patch"
    }
}

# --------------------------------------------------------------- fapb dll ---
if ($NoFapbPatch) {
    Write-Host "fapb.dll    : skipped (-NoFapbPatch)" -ForegroundColor DarkGray
} elseif ($RebuildFapb -and $LegacyFapbPatch) {
    throw "-RebuildFapb and -LegacyFapbPatch are mutually exclusive"
} elseif ($RebuildFapb) {
    $py = Get-PythonExe
    if (-not $py) { throw "python not found; cannot run fapb_rebuild.py" }
    $pyArgs = @((Join-Path $scriptRoot 'fapb_rebuild.py'), '--download', '--game-dir', $GameDir)
    if ($ArtifactsDir) { $pyArgs += @('--artifacts', $ArtifactsDir) }
    if ($WhatIf) {
        Write-Host "fapb.dll    : [WhatIf] would rebuild + install" -ForegroundColor Yellow
    } else {
        $pyArgs += '--install'
        & $py @pyArgs | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "fapb.dll rebuild failed (exit $LASTEXITCODE)" }
    }
} elseif ($LegacyFapbPatch) {
    $mutex = if ($WhatIf) { '--dry-run' } else { '--apply' }
    try {
        $code = Invoke-PythonTool -Tool (Join-Path $scriptRoot 'fapb_patch.py') `
            -Arguments @('--dll', $fapbDll, $mutex)
        if ($code -ne 0) { throw "exit $code" }
    } catch {
        Write-Warning "legacy fapb.dll patch failed: $_"
        if ($Mode -eq 'fapb') { throw "FAPB cannot manage bots without a working DLL" }
    }
} else {
    # Default: inspect only.  Never apply the harmful patch automatically.
    $py = Get-PythonExe
    if (-not $py) {
        Write-Warning "python not found; cannot inspect fapb.dll"
    } else {
        $raw = & $py (Join-Path $scriptRoot 'fapb_patch.py') --dll $fapbDll --json
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "fapb_patch.py failed (exit $LASTEXITCODE)"
        } else {
            $st = $raw | ConvertFrom-Json
            Write-Host "fapb.dll    : $($st.state)  ($($st.sha256))" -ForegroundColor Cyan
            switch ($st.state) {
                'rebuilt' {
                    Write-Host "              OK: rebuilt DLL, unpatched." -ForegroundColor Green
                }
                'rebuilt-legacy-patched' {
                    Write-Host "              harmful 5-byte patch found; reverting..." -ForegroundColor Yellow
                    if ($WhatIf) {
                        Write-Host "              [WhatIf] would run fapb_patch.py --revert" -ForegroundColor Yellow
                    } else {
                        $code = Invoke-PythonTool -Tool (Join-Path $scriptRoot 'fapb_patch.py') `
                            -Arguments @('--dll', $fapbDll, '--revert')
                        if ($code -ne 0) { throw "fapb.dll revert failed (exit $code)" }
                    }
                }
                'released' {
                    Write-Host "              released DLL has a broken import table." -ForegroundColor Yellow
                    Write-Host "              Rebuild it: -RebuildFapb (recommended)" -ForegroundColor Yellow
                    Write-Host "              or opt in to the deprecated patch: -LegacyFapbPatch" -ForegroundColor DarkYellow
                    if ($Mode -eq 'fapb') {
                        Write-Host "              !! -Mode fapb lets FAPB manage bots; rebuild first." -ForegroundColor Red
                    }
                }
                'released-legacy-patched' {
                    Write-Host "              legacy patch present; rebuilding is safer (-RebuildFapb)." -ForegroundColor Yellow
                }
                default {
                    Write-Warning "              unknown fapb.dll build"
                }
            }
        }
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
Write-Host "  In game console:  meta list   -> FAPB and ABPB both listed"
Write-Host "  Quota owner     : $Mode"
if ($Mode -eq 'abpb') {
    Write-Host "  Add bots        : abpb add / abpb fill"
    Write-Host "  Note            : ABPB clamps abpb_quota to maxplayers at runtime"
} else {
    Write-Host "  Add bots        : fapb add / fapb fill"
}
if (-not $NoFapbPatch -and -not $RebuildFapb -and -not $LegacyFapbPatch) {
    Write-Host "  fapb.dll        : rebuild recommended if the state above is 'released'" -ForegroundColor DarkGray
}
if (-not $WhatIf) {
    Write-Host "  Restore         : powershell -ExecutionPolicy Bypass -File .\restore.ps1 -BackupDir `"$backupDir`""
    try {
        Write-Host ""
        [void](Invoke-PythonTool -Tool (Join-Path $scriptRoot 'doctor.py') -Arguments @('--game-dir', $GameDir))
    } catch {
        Write-Warning "doctor.py failed: $_"
    }
}
