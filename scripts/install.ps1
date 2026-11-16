<#
.SYNOPSIS
    Fix the CS 1.6 / FAPB "kick bot -> crash" bug.

.DESCRIPTION
    1. Backs up plugins.ini and fapb.dll.
    2. Rewrites cstrike/addons/metamod/plugins.ini so FAPB is active and the
       other bot cores (YAPB / SYPB / PODBot / EBot / CSBot Enabler) are
       commented out.  ABPB lines are left untouched.
    3. Inspects fapb.dll:
         rebuilt        -> OK, leave it alone (recommended)
         rebuilt+patch  -> automatically revert the harmful 5-byte patch
         released       -> warn; rebuild with -RebuildDll (recommended) or
                           opt in to the deprecated patch with -LegacyPatch

    The 5-byte 0x1811D patch is deprecated.  It hides the kick crash on the
    released DLL, but makes the rebuilt DLL crash.  The real fix is the
    rebuilt import table from scripts/fapb_rebuild.py.

    Close the game first.

.PARAMETER GameDir
    CS 1.6 root folder (the one that contains hl.exe).
    Defaults to $env:FAPB_GAME_DIR, then the registry.

.PARAMETER RebuildDll
    Run scripts/fapb_rebuild.py --download --install.  This downloads the
    pinned upstream artifacts (or uses -ArtifactsDir), verifies the output
    hash and replaces fapb.dll.  Requires internet on first run.

.PARAMETER ArtifactsDir
    Local folder containing yapb.dll / yapb_b1.bin / yapb_b2.bin, used with
    -RebuildDll.  Defaults to tools\artifacts.

.PARAMETER LegacyPatch
    Apply the deprecated 5-byte patch to a released DLL.  Refused on rebuilt
    DLLs.  Use this only if you cannot rebuild for some reason.

.PARAMETER NoDllPatch
    Do not inspect or touch fapb.dll at all (legacy flag).

.PARAMETER WhatIf
    Report what would change; write nothing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -RebuildDll
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -GameDir "D:\Counter Strike 8684(澶欱OT鐗?" -RebuildDll
#>
[CmdletBinding()]
param(
    [string]$GameDir = "",
    [switch]$RebuildDll,
    [string]$ArtifactsDir = "",
    [switch]$LegacyPatch,
    [switch]$NoDllPatch,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-GameDir {
    param([string]$Hint)
    $cands = @()
    if ($Hint) { $cands += $Hint }
    if ($env:FAPB_GAME_DIR) { $cands += $env:FAPB_GAME_DIR }
    $keys = @(
        'HKLM:\SOFTWARE\WOW6432Node\Valve\CounterStrike',
        'HKLM:\SOFTWARE\Valve\CounterStrike',
        'HKCU:\SOFTWARE\Valve\CounterStrike'
    )
    foreach ($k in $keys) {
        try {
            $v = (Get-ItemProperty -Path $k -Name InstallPath -ErrorAction Stop).InstallPath
            if ($v) { $cands += $v }
        } catch { }
    }
    foreach ($d in $cands) {
        if (-not $d) { continue }
        if (Test-Path -LiteralPath (Join-Path $d 'hl.exe')) {
            return (Resolve-Path -LiteralPath $d).Path
        }
        # Common repack layout: <root>\<same name>\hl.exe
        if (Test-Path -LiteralPath $d) {
            $hit = Get-ChildItem -LiteralPath $d -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'hl.exe') } |
                Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
    }
    return ""
}

function Get-Python {
    foreach ($c in @('python', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

$GameDir = Find-GameDir -Hint $GameDir
if (-not $GameDir) {
    Write-Host "Cannot locate CS 1.6 automatically." -ForegroundColor Yellow
    $GameDir = Read-Host "Enter the game root folder (contains hl.exe)"
    $GameDir = $GameDir.Trim().Trim('"')
}
if (-not (Test-Path -LiteralPath (Join-Path $GameDir 'hl.exe'))) {
    throw "hl.exe not found under: $GameDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $GameDir 'cstrike'))) {
    throw "cstrike folder not found under: $GameDir"
}
if ($RebuildDll -and $LegacyPatch) {
    throw "-RebuildDll and -LegacyPatch are mutually exclusive"
}

Write-Host "Game folder: $GameDir" -ForegroundColor Cyan

$plugins = Join-Path $GameDir 'cstrike\addons\metamod\plugins.ini'
if (-not (Test-Path -LiteralPath $plugins)) {
    throw "Metamod plugins.ini not found: $plugins"
}
$dll = Join-Path $GameDir 'cstrike\addons\fapb\dlls\fapb.dll'
if (-not (Test-Path -LiteralPath $dll)) {
    throw "FAPB core not found: $dll"
}

# ---------------------------------------------------------------- backup ----
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $GameDir ("cstrike\addons\fapb\backup\" + $stamp)
if (-not $WhatIf) {
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $plugins -Destination (Join-Path $backupDir 'plugins.ini') -Force
    Copy-Item -LiteralPath $dll -Destination (Join-Path $backupDir 'fapb.dll') -Force
    Write-Host "Backup: $backupDir" -ForegroundColor DarkGray
}

# ------------------------------------------------------------ plugins.ini ---
$botCoreRe = '^\s*win32\s+addons[\\/](yapb|sypb|podbot|ebot|csbot_enabler|fapb)[\\/]'
$fapbRe = 'addons[\\/]fapb[\\/]dlls[\\/]fapb\.dll'
$amxxBlRe = '^\s*win32\s+addons[\\/]amxmodx[\\/]dlls[\\/]amxmodx_bl_mm\.dll'
$amxxMainRe = '^\s*win32\s+addons[\\/]amxmodx[\\/]dlls[\\/]amxmodx_mm\.dll'

$lines = @(Get-Content -LiteralPath $plugins)
$hasAmxxMain = $false
foreach ($l in $lines) {
    if ($l -match $amxxMainRe) { $hasAmxxMain = $true }
}

$out = New-Object System.Collections.Generic.List[string]
$disabled = 0

foreach ($line in $lines) {
    if ($line -match 'fapb-kickfix') { continue }

    if ($line -match $botCoreRe) {
        if ($line -match $fapbRe) { continue }
        if ($line.TrimStart().StartsWith(';')) {
            $out.Add($line)
        } else {
            $out.Add('; ' + $line.Trim())
            $disabled++
        }
        continue
    }

    if ($hasAmxxMain -and ($line -match $amxxBlRe) -and (-not $line.TrimStart().StartsWith(';'))) {
        $out.Add('; ' + $line.Trim())
        $disabled++
        continue
    }

    $out.Add($line)
}

if (($out.Count -gt 0) -and ($out[$out.Count - 1].Trim() -ne '')) { $out.Add('') }
$out.Add(';; --- FAPB active (managed by fapb-kickfix; ABPB lines are untouched) ---')
$out.Add('win32 addons/fapb/dlls/fapb.dll')

if ($WhatIf) {
    Write-Host "[WhatIf] would comment $disabled conflicting line(s) in $plugins" -ForegroundColor Yellow
} else {
    Set-Content -LiteralPath $plugins -Value $out -Encoding ASCII
    Write-Host "plugins.ini updated: commented $disabled line(s), FAPB enabled" -ForegroundColor Green
}

# ------------------------------------------------------------------- dll ----
$py = Get-Python
if ($NoDllPatch) {
    Write-Host "Skipping fapb.dll completely (-NoDllPatch)" -ForegroundColor DarkGray
} elseif (-not $py) {
    Write-Warning "python not found - cannot inspect/rebuild fapb.dll."
    Write-Warning "Install Python, then run: python scripts\fapb_rebuild.py --download --install"
} elseif ($RebuildDll) {
    $pyArgs = @((Join-Path $scriptRoot 'fapb_rebuild.py'), '--download', '--game-dir', $GameDir)
    if ($ArtifactsDir) { $pyArgs += @('--artifacts', $ArtifactsDir) }
    if ($WhatIf) {
        Write-Host "[WhatIf] would run: $py $($pyArgs -join ' ') --install" -ForegroundColor Yellow
    } else {
        $pyArgs += '--install'
        & $py @pyArgs
        if ($LASTEXITCODE -ne 0) { throw "fapb.dll rebuild failed (exit $LASTEXITCODE)" }
    }
} else {
    $pyArgs = @((Join-Path $scriptRoot 'fapb_patch.py'), '--dll', $dll, '--json')
    $raw = & $py @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "fapb_patch.py failed (exit $LASTEXITCODE)" }
    $st = $raw | ConvertFrom-Json
    Write-Host "fapb.dll state: $($st.state)  ($($st.sha256))" -ForegroundColor Cyan

    switch ($st.state) {
        'rebuilt' {
            Write-Host "  OK: rebuilt DLL, unpatched. Nothing to do." -ForegroundColor Green
        }
        'rebuilt-legacy-patched' {
            Write-Host "  harmful 5-byte patch detected on the rebuilt DLL; reverting..." -ForegroundColor Yellow
            if ($WhatIf) {
                Write-Host "[WhatIf] would run: python fapb_patch.py --revert" -ForegroundColor Yellow
            } else {
                & $py (Join-Path $scriptRoot 'fapb_patch.py') --dll $dll --revert
                if ($LASTEXITCODE -ne 0) { throw "patch revert failed (exit $LASTEXITCODE)" }
            }
        }
        'released' {
            if ($LegacyPatch) {
                if ($WhatIf) {
                    Write-Host "[WhatIf] would apply the deprecated 5-byte patch" -ForegroundColor Yellow
                } else {
                    & $py (Join-Path $scriptRoot 'fapb_patch.py') --dll $dll --apply
                    if ($LASTEXITCODE -ne 0) { throw "legacy patch failed (exit $LASTEXITCODE)" }
                }
            } else {
                Write-Host "  released upstream DLL is broken (missing import table)." -ForegroundColor Yellow
                Write-Host "  Rebuild it (recommended):" -ForegroundColor Yellow
                Write-Host "    powershell -ExecutionPolicy Bypass -File .\install.ps1 -RebuildDll" -ForegroundColor Yellow
                Write-Host "  or, if you cannot rebuild, opt in to the deprecated patch:" -ForegroundColor DarkYellow
                Write-Host "    powershell -ExecutionPolicy Bypass -File .\install.ps1 -LegacyPatch" -ForegroundColor DarkYellow
            }
        }
        'released-legacy-patched' {
            Write-Host "  legacy patch present on the released DLL; rebuilding is safer." -ForegroundColor Yellow
            Write-Host "    powershell -ExecutionPolicy Bypass -File .\install.ps1 -RebuildDll" -ForegroundColor Yellow
        }
        default {
            Write-Warning "  unknown fapb.dll build; inspect it with scripts\doctor.py"
        }
    }
}

# ------------------------------------------------------------------ report --
Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
Write-Host "  1) Make sure no other conflicting bot core is enabled (ABPB coexistence: fapb_abpb_setup.ps1)."
Write-Host "  2) In game console:  meta list"
Write-Host "  3) Press V -> 1 -> 4/5 to test kicking bots; check doctor.py afterwards."
if (-not $WhatIf) {
    Write-Host "  Restore: powershell -ExecutionPolicy Bypass -File .\restore.ps1 -BackupDir `"$backupDir`""
}
