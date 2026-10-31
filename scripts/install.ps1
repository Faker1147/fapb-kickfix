<#
.SYNOPSIS
    Fix the CS 1.6 / FAPB "kick bot -> crash" bug (fapb.dll+0x18173).

.DESCRIPTION
    1. Backs up plugins.ini and fapb.dll.
    2. Rewrites cstrike/addons/metamod/plugins.ini so exactly ONE bot core
       (FAPB) is active.  YAPB / SYPB / PODBot / EBot / CSBot Enabler are
       commented out but kept on disk.
    3. Applies the 5-byte crash patch to fapb.dll (see docs/diagnosis.md).

    Close the game first.

.PARAMETER GameDir
    CS 1.6 root folder (the one that contains hl.exe).
    Defaults to $env:FAPB_GAME_DIR, then the registry.

.PARAMETER NoDllPatch
    Only fix plugins.ini and leave fapb.dll untouched.

.PARAMETER WhatIf
    Report what would change; write nothing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -GameDir "D:\Counter Strike 8684(多BOT版)"
#>
[CmdletBinding()]
param(
    [string]$GameDir = "",
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
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'hl.exe'))) {
            return (Resolve-Path -LiteralPath $d).Path
        }
    }
    return ""
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
$out.Add(';; --- FAPB: the only active bot core (managed by fapb-kickfix) ---')
$out.Add('win32 addons/fapb/dlls/fapb.dll')

if ($WhatIf) {
    Write-Host "[WhatIf] would comment $disabled conflicting line(s) in $plugins" -ForegroundColor Yellow
} else {
    Set-Content -LiteralPath $plugins -Value $out -Encoding ASCII
    Write-Host "plugins.ini updated: commented $disabled line(s), FAPB only" -ForegroundColor Green
}

# --------------------------------------------------------------- dll patch -
if ($NoDllPatch) {
    Write-Host "Skipping DLL patch (-NoDllPatch)" -ForegroundColor DarkGray
} else {
    $py = $null
    foreach ($c in @('python', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source; break }
    }
    if (-not $py) {
        Write-Warning "python not found - DLL patch skipped. Run: python scripts\fapb_patch.py --apply"
    } else {
        $patchArgs = @((Join-Path $scriptRoot 'fapb_patch.py'), '--dll', $dll)
        if ($WhatIf) { $patchArgs += '--dry-run' } else { $patchArgs += '--apply' }
        & $py @patchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "DLL patch failed (exit $LASTEXITCODE)"
        }
    }
}

# ------------------------------------------------------------------ report --
Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
Write-Host "  1) Make sure no other bot core (YAPB/SYPB/PODBot/EBot) is enabled."
Write-Host "  2) In game console:  meta list   -> only FAPB should be listed"
Write-Host "  3) Press V -> 1 -> 4/5 to test kicking bots."
if (-not $WhatIf) {
    Write-Host "  Restore: powershell -ExecutionPolicy Bypass -File .\restore.ps1 -BackupDir `"$backupDir`""
}
