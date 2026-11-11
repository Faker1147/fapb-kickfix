<#
.SYNOPSIS
    Make FAPB and ABPB coexist on one CS 1.6 server.

.DESCRIPTION
    ABPB (AiBo 4.3.3 fork) and FAPB (YaPB 2.55b fork) may be *installed*
    side by side, but only ONE of them may manage bots.  This script:

      1. enables both Metamod plugins and disables the other bot cores
         (YAPB / SYPB / PODBot / EBot / CSBot Enabler) that are known to
         crash FAPB;
      2. forces the "yielding" side to quota 0 / autovacate 0;
      3. in -Mode fapb also patches ABPB.dll so its own compat guard can
         finally see FAPB (ABPB looks for "fapb_quota", FAPB uses
         "fb_quota").

    Close the game first.  Everything is backed up and reversible.

.PARAMETER Mode
    abpb : ABPB manages the bots, FAPB stays loaded but idle.  (recommended)
    fapb : FAPB manages the bots, ABPB yields automatically.

.PARAMETER NoGuardPatch
    Do not patch ABPB.dll.  -Mode abpb does not need the patch at all.

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
    [switch]$NoGuardPatch,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-GameDir {
    param([string]$Hint)
    $cands = @()
    if ($Hint) { $cands += $Hint }
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
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'hl.exe'))) {
            return (Resolve-Path -LiteralPath $d).Path
        }
    }
    return ""
}

function Set-CvarLine {
    param([string]$Path, [string]$Name, [string]$Value, [System.Collections.Generic.List[string]]$Log)
    if (-not (Test-Path -LiteralPath $Path)) {
        $Log.Add("skip (missing): $Path")
        return $false
    }
    $lines = @(Get-Content -LiteralPath $Path)
    $re = '^\s*' + [regex]::Escape($Name) + '\s'
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
    if (-not $WhatIf) {
        Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
    }
    $Log.Add(("{0} = {1}   [{2}]" -f $Name, $Value, (Split-Path -Parent $Path)))
    return $true
}

$GameDir = Find-GameDir -Hint $GameDir
if (-not $GameDir) {
    Write-Host "Cannot locate CS 1.6." -ForegroundColor Yellow
    $GameDir = (Read-Host "Enter the game root folder (contains hl.exe)").Trim().Trim('"')
}
if (-not (Test-Path -LiteralPath (Join-Path $GameDir 'hl.exe'))) { throw "hl.exe not found: $GameDir" }

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
    Write-Warning "ABPB.cfg not found: $abpbCfg (cvars will be appended where possible)"
}

Write-Host "Game folder : $GameDir" -ForegroundColor Cyan
Write-Host "Mode        : $Mode  (bot manager)" -ForegroundColor Cyan

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $cstrike "addons\fapb\backup\abpb-$stamp"
if (-not $WhatIf) {
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $plugins -Destination (Join-Path $backupDir 'plugins.ini') -Force
    Copy-Item -LiteralPath $fapbDll -Destination (Join-Path $backupDir 'fapb.dll') -Force
    Copy-Item -LiteralPath $abpbDll -Destination (Join-Path $backupDir 'ABPB.dll') -Force
    if (Test-Path -LiteralPath $fapbCfg) { Copy-Item -LiteralPath $fapbCfg -Destination (Join-Path $backupDir 'fapb.cfg') -Force }
    if (Test-Path -LiteralPath $abpbCfg) { Copy-Item -LiteralPath $abpbCfg -Destination (Join-Path $backupDir 'ABPB.cfg') -Force }
    Write-Host "Backup      : $backupDir" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- plugins ---
$botCoreRe = '^\s*win32\s+addons[\\/](yapb|sypb|podbot|ebot|csbot_enabler)[\\/]'
$lines = @(Get-Content -LiteralPath $plugins)
$out = New-Object System.Collections.Generic.List[string]
$disabled = 0
$haveFapb = $false
$haveAbpb = $false

foreach ($line in $lines) {
    if ($line -match 'fapb-abpb-setup') { continue }
    if ($line -match $botCoreRe) {
        if ($line.TrimStart().StartsWith(';')) { $out.Add($line) }
        else { $out.Add('; ' + $line.Trim()); $disabled++ }
        continue
    }
    if ($line -match 'addons[\\/]fapb[\\/]dlls[\\/]fapb\.dll') { $haveFapb = $true; continue }
    if ($line -match 'addons[\\/]ABPB[\\/]bin[\\/]ABPB\.dll') { $haveAbpb = $true; continue }
    $out.Add($line)
}
if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne '') { $out.Add('') }
$out.Add(';; --- FAPB + ABPB (managed by fapb-abpb-setup) ---')
$out.Add('win32 addons/fapb/dlls/fapb.dll')
$out.Add('win32 addons/ABPB/bin/ABPB.dll')

if ($WhatIf) {
    Write-Host "[WhatIf] plugins.ini: comment $disabled core(s), enable fapb + ABPB" -ForegroundColor Yellow
} else {
    Set-Content -LiteralPath $plugins -Value $out -Encoding ASCII
    Write-Host "plugins.ini : comment $disabled core(s); fapb + ABPB enabled" -ForegroundColor Green
}

# ------------------------------------------------------------------- cvars --
$log = New-Object System.Collections.Generic.List[string]
if ($Mode -eq 'abpb') {
    # ABPB owns the bots; FAPB must not fill or vacate.
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_quota' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_autovacate' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_compat_auto' -Value '0' -Log $log)  # never auto-yield to FAPB
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_autovacate' -Value '1' -Log $log)
} else {
    # FAPB owns the bots; ABPB must not fill.
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_quota' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_autovacate' -Value '0' -Log $log)
    [void](Set-CvarLine -Path $abpbCfg -Name 'abpb_compat_auto' -Value '1' -Log $log)
    [void](Set-CvarLine -Path $fapbCfg -Name 'fb_autovacate' -Value '0' -Log $log)
}
Write-Host "cvars       :" -ForegroundColor Green
foreach ($l in $log) { Write-Host "   $l" }

# --------------------------------------------------------------- guard patch -
if ($Mode -eq 'fapb' -and -not $NoGuardPatch) {
    $py = $null
    foreach ($c in @('python', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source; break }
    }
    if (-not $py) {
        Write-Warning "python not found - ABPB guard patch skipped."
        Write-Warning "Run: python scripts\abpb_compat.py --dll `"$abpbDll`" --apply"
    } else {
        $args2 = @((Join-Path $scriptRoot 'abpb_compat.py'), '--dll', $abpbDll)
        if ($WhatIf) { $args2 += '--dry-run' } else { $args2 += '--apply' }
        & $py @args2
        if ($LASTEXITCODE -ne 0) { throw "ABPB guard patch failed (exit $LASTEXITCODE)" }
    }
} elseif ($Mode -eq 'abpb') {
    Write-Host "guard patch : not needed in -Mode abpb (compat_auto=0)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
Write-Host "  In game console:  meta list   -> FAPB and ABPB both listed"
Write-Host "  Quota owner     : $Mode"
if (-not $WhatIf) {
    Write-Host "  Restore: powershell -ExecutionPolicy Bypass -File .\restore.ps1 -BackupDir `"$backupDir`""
}
