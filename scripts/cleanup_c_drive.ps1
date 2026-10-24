param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$capcutApps = 'C:\Users\ADMIN\AppData\Local\CapCut\Apps'
$keepVersion = '8.7.0.3685'
$chromeUserData = 'C:\Users\ADMIN\AppData\Local\Google\Chrome\User Data'
$oldVersions = @('1.5.1.245', '8.2.0.3462', '8.3.0.3497', '8.3.5.3492', '8.7.0.3676', '8.7.0.3684')
$taskTargets = [System.Collections.Generic.List[object]]::new()

function Add-TaskTarget([string]$Category, [string]$TargetPath, [bool]$RemoveRoot = $false, [bool]$OldTempOnly = $false) {
    $fullPath = [System.IO.Path]::GetFullPath($TargetPath).TrimEnd('\')
    if ($fullPath -eq 'C:' -or $fullPath -eq 'C:\Users\ADMIN' -or $fullPath -eq $capcutApps -or $fullPath -eq $chromeUserData) {
        throw "Unsafe cleanup target: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) { return }
    # Check every ancestor too: never follow a junction outside the approved path.
    $ancestor = [System.IO.DirectoryInfo]::new($fullPath)
    while ($null -ne $ancestor) {
        if (($ancestor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point in cleanup target: $fullPath"
        }
        $ancestor = $ancestor.Parent
    }
    $taskTargets.Add([pscustomobject]@{
        Category=$Category; Path=$fullPath; RemoveRoot=$RemoveRoot; OldTempOnly=$OldTempOnly
    })
}

if (-not (Test-Path -LiteralPath (Join-Path $capcutApps "$keepVersion\CapCut.exe") -PathType Leaf)) {
    throw 'The CapCut version to retain was not found; cleanup cancelled.'
}
Add-TaskTarget 'CapCut cache' 'C:\Users\ADMIN\AppData\Local\CapCut\User Data\Cache'
foreach ($version in $oldVersions) {
    $versionPath = [System.IO.Path]::GetFullPath((Join-Path $capcutApps $version))
    if ([System.IO.Path]::GetDirectoryName($versionPath) -ne $capcutApps -or $version -eq $keepVersion) {
        throw 'Unexpected CapCut version path.'
    }
    Add-TaskTarget 'Old CapCut versions' $versionPath $true
}
foreach ($profile in (Get-ChildItem -LiteralPath $chromeUserData -Directory -Force)) {
    if ($profile.Name -notmatch '^(Default|Profile \d+|Guest Profile)$') { continue }
    foreach ($cacheName in @('Cache', 'Code Cache', 'GPUCache')) {
        Add-TaskTarget 'Chrome cache' (Join-Path $profile.FullName $cacheName)
    }
}
Add-TaskTarget 'Temp' 'C:\Users\ADMIN\AppData\Local\Temp' $false $true
Add-TaskTarget 'Temp' 'C:\Windows\Temp' $false $true
Add-TaskTarget 'Temp' 'C:\Temp' $false $true
Add-TaskTarget 'Temp' 'C:\tmp' $false $true
Add-TaskTarget 'CrashDumps' 'C:\Users\ADMIN\AppData\Local\CrashDumps'
Add-TaskTarget 'NVIDIA shader cache' 'C:\Users\ADMIN\AppData\Local\NVIDIA\DXCache'
Add-TaskTarget 'NVIDIA shader cache' 'C:\Users\ADMIN\AppData\Local\NVIDIA\GLCache'
Add-TaskTarget 'NVIDIA update packages' 'C:\ProgramData\NVIDIA Corporation\NVIDIA App\UpdateFramework\ota-artifacts'

if (-not $Execute) {
    $taskTargets | ConvertTo-Json -Depth 3
    exit 0
}

# Refuse to remove an old CapCut installation while its executable is running.
$runningProcesses = @(Get-CimInstance Win32_Process)
foreach ($target in $taskTargets) {
    if ($target.Category -eq 'Old CapCut versions' -and @($runningProcesses | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($target.Path + '\', [System.StringComparison]::OrdinalIgnoreCase)
    }).Count -gt 0) {
        throw "CapCut is using $($target.Path); cleanup cancelled."
    }
}
if (@($runningProcesses | Where-Object {
    $_.Name -match '^(setup|NVIDIAInstaller|NVIDIAInstallHelper)\.exe$' -and $_.ExecutablePath -match '(?i)nvidia'
}).Count -gt 0) {
    throw 'An NVIDIA installation is running; cleanup cancelled.'
}

$freeBefore = ([System.IO.DriveInfo]::new('C')).AvailableFreeSpace
$tempCutoff = (Get-Date).AddDays(-1)
$stats = [System.Collections.Generic.List[object]]::new()
foreach ($target in $taskTargets) {
    $result = [pscustomobject]@{Category=$target.Category; Path=$target.Path; DeletedBytes=[long]0; DeletedFiles=0; SkippedFiles=0; Errors=0}
    $pendingDirs = [System.Collections.Generic.Stack[string]]::new()
    $directories = [System.Collections.Generic.List[string]]::new()
    $pendingDirs.Push($target.Path)
    while ($pendingDirs.Count -gt 0) {
        $directory = $pendingDirs.Pop()
        $directories.Add($directory)
        try { $entries = ([System.IO.DirectoryInfo]::new($directory)).GetFileSystemInfos() }
        catch { $result.Errors++; continue }
        foreach ($entry in $entries) {
            $entryPath = [System.IO.Path]::GetFullPath($entry.FullName)
            if (-not $entryPath.StartsWith($target.Path + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'A discovered file escaped its validated cleanup target.'
            }
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $result.SkippedFiles++; continue
            }
            if (($entry.Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                $pendingDirs.Push($entryPath); continue
            }
            if ($target.OldTempOnly -and $entry.LastWriteTime -gt $tempCutoff) {
                $result.SkippedFiles++; continue
            }
            try {
                $length = $entry.Length
                # Skip files held open by an application, even with delete sharing.
                $stream = [System.IO.File]::Open($entryPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
                $stream.Dispose()
                Remove-Item -LiteralPath $entryPath -Force -ErrorAction Stop
                $result.DeletedBytes += $length
                $result.DeletedFiles++
            } catch { $result.SkippedFiles++ }
        }
    }
    # Remove only empty directories, from the bottom up. Never recurse through
    # an unverified path, and retain the top-level cache directory.
    for ($i = $directories.Count - 1; $i -ge 0; $i--) {
        $directory = $directories[$i]
        if ($directory -eq $target.Path -and -not $target.RemoveRoot) { continue }
        try {
            if (([System.IO.DirectoryInfo]::new($directory)).GetFileSystemInfos().Count -eq 0) {
                Remove-Item -LiteralPath $directory -Force -ErrorAction Stop
            }
        } catch { $result.Errors++ }
    }
    $stats.Add($result)
    Write-Output ("Completed: {0} | {1:N3} GB removed | {2} files skipped" -f $target.Path, ($result.DeletedBytes/1GB), $result.SkippedFiles)
}

$summary = @($stats | Group-Object Category | ForEach-Object {
    [pscustomobject]@{
        Category=$_.Name
        DeletedGB=[math]::Round((($_.Group | Measure-Object DeletedBytes -Sum).Sum/1GB),3)
        DeletedFiles=($_.Group | Measure-Object DeletedFiles -Sum).Sum
        SkippedFiles=($_.Group | Measure-Object SkippedFiles -Sum).Sum
        Errors=($_.Group | Measure-Object Errors -Sum).Sum
    }
})
[pscustomobject]@{
    FreeBeforeGB=[math]::Round($freeBefore/1GB,3)
    FreeAfterGB=[math]::Round(([System.IO.DriveInfo]::new('C')).AvailableFreeSpace/1GB,3)
    KeptCapCut=$keepVersion
    Summary=$summary
} | ConvertTo-Json -Depth 4
