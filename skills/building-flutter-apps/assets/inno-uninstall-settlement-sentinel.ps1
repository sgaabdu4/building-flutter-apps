[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string] $IsccPath,

  [ValidateRange(5, 120)]
  [int] $PhaseTimeoutSeconds = 30,

  [string] $WorkingRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
  throw 'The Inno uninstall settlement sentinel requires Windows.'
}

$resolvedIsccPath = (Resolve-Path -LiteralPath $IsccPath).Path
$invocationId = [Guid]::NewGuid().ToString('N')
$appId = "BuildingFlutterApps.UninstallSettlementSentinel.$invocationId"
$uninstallSubKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\${appId}_is1"
$registryViews = @(
  [Microsoft.Win32.RegistryView]::Registry32,
  [Microsoft.Win32.RegistryView]::Registry64
)

function Invoke-OwnedProcess {
  param(
    [Parameter(Mandatory)]
    [string] $FilePath,

    [Parameter(Mandatory)]
    [string[]] $Arguments,

    [Parameter(Mandatory)]
    [string] $Phase,

    [Parameter(Mandatory)]
    [int] $TimeoutSeconds
  )

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.UseShellExecute = $false
  foreach ($argument in $Arguments) {
    $startInfo.ArgumentList.Add([string] $argument)
  }

  $process = [System.Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  try {
    if (-not $process.Start()) {
      throw "phase=$Phase result=start-failed"
    }
    Write-Host "phase=$Phase result=started pid=$($process.Id) timeout_seconds=$TimeoutSeconds"

    $timeoutMilliseconds = [int64] $TimeoutSeconds * 1000
    if ($timeoutMilliseconds -gt [int]::MaxValue) {
      throw "phase=$Phase result=invalid-timeout"
    }

    if (-not $process.WaitForExit([int] $timeoutMilliseconds)) {
      try {
        $process.Kill($true)
        [void] $process.WaitForExit(5000)
      } catch {
        Write-Warning "phase=$Phase result=cleanup-failed pid=$($process.Id)"
      }
      throw "phase=$Phase result=timeout pid=$($process.Id) timeout_seconds=$TimeoutSeconds"
    }

    $exitCode = $process.ExitCode
    if ($exitCode -ne 0) {
      throw "phase=$Phase result=failed exit_code=$exitCode"
    }
    Write-Host "phase=$Phase result=completed exit_code=$exitCode"
  } finally {
    $process.Dispose()
  }
}

function Get-PresentUninstallRegistryViews {
  param(
    [Parameter(Mandatory)]
    [string] $SubKey
  )

  $presentViews = @()
  foreach ($view in $registryViews) {
    $baseKey = $null
    $key = $null
    try {
      $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        $view
      )
      $key = $baseKey.OpenSubKey($SubKey, $false)
      if ($null -ne $key) {
        $presentViews += $view.ToString()
      }
    } finally {
      if ($null -ne $key) {
        $key.Dispose()
      }
      if ($null -ne $baseKey) {
        $baseKey.Dispose()
      }
    }
  }
  return @($presentViews | Sort-Object -Unique)
}

function Wait-UninstallSettlement {
  param(
    [Parameter(Mandatory)]
    [string] $InstallDirectory,

    [Parameter(Mandatory)]
    [string] $SubKey,

    [Parameter(Mandatory)]
    [int] $TimeoutSeconds
  )

  $startedAt = [DateTimeOffset]::UtcNow
  $deadline = $startedAt.AddSeconds($TimeoutSeconds)
  Write-Host "phase=uninstall-settlement result=started timeout_seconds=$TimeoutSeconds deadline_utc=$($deadline.ToString('o'))"
  do {
    $directoryPresent = Test-Path -LiteralPath $InstallDirectory
    $presentViews = @(Get-PresentUninstallRegistryViews -SubKey $SubKey)
    if (-not $directoryPresent -and $presentViews.Count -eq 0) {
      $elapsedMilliseconds = [int64] (
        ([DateTimeOffset]::UtcNow - $startedAt).TotalMilliseconds
      )
      Write-Host "phase=uninstall-settlement result=completed directory=absent registry=absent elapsed_ms=$elapsedMilliseconds"
      return
    }
    Start-Sleep -Milliseconds 100
  } while ([DateTimeOffset]::UtcNow -lt $deadline)

  $directoryState = if (Test-Path -LiteralPath $InstallDirectory) { 'present' } else { 'absent' }
  $presentViews = @(Get-PresentUninstallRegistryViews -SubKey $SubKey)
  $registryState = if ($presentViews.Count -eq 0) { 'absent' } else { $presentViews -join ',' }
  $elapsedMilliseconds = [int64] (
    ([DateTimeOffset]::UtcNow - $startedAt).TotalMilliseconds
  )
  throw "phase=uninstall-settlement result=timeout directory=$directoryState registry=$registryState elapsed_ms=$elapsedMilliseconds deadline_utc=$($deadline.ToString('o')) original_process=completed cleanup_clone=unknown"
}

function Remove-OwnedRegistryState {
  param(
    [Parameter(Mandatory)]
    [string] $SubKey
  )

  foreach ($view in $registryViews) {
    $baseKey = $null
    try {
      $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        $view
      )
      $baseKey.DeleteSubKeyTree($SubKey, $false)
    } finally {
      if ($null -ne $baseKey) {
        $baseKey.Dispose()
      }
    }
  }
}

$sentinelRoot = if ([string]::IsNullOrWhiteSpace($WorkingRoot)) {
  Join-Path ([IO.Path]::GetTempPath()) "bfa-inno-settlement-$([Guid]::NewGuid().ToString('N'))"
} else {
  [IO.Path]::GetFullPath($WorkingRoot)
}

if (Test-Path -LiteralPath $sentinelRoot) {
  throw "Sentinel root must not already exist: $sentinelRoot"
}

$installDirectory = Join-Path $sentinelRoot 'installed'
$sourceDirectory = Join-Path $sentinelRoot 'source'
$outputDirectory = Join-Path $sourceDirectory 'out'
$ownerMarker = Join-Path $sentinelRoot '.building-flutter-apps-sentinel'
$issPath = Join-Path $sourceDirectory 'sentinel.iss'
$payloadPath = Join-Path $sourceDirectory 'payload.txt'
$previousInstallDirectory = [Environment]::GetEnvironmentVariable(
  'BFA_SENTINEL_INSTALL_DIR',
  [EnvironmentVariableTarget]::Process
)
$previousAppId = [Environment]::GetEnvironmentVariable(
  'BFA_SENTINEL_APP_ID',
  [EnvironmentVariableTarget]::Process
)
$uninstallProcessCompleted = $false
$settlementCompleted = $false

try {
  [void] (New-Item -ItemType Directory -Path $sourceDirectory)
  Set-Content -LiteralPath $ownerMarker -Value $appId -NoNewline
  Set-Content -LiteralPath $payloadPath -Value 'sentinel' -NoNewline
  Set-Content -LiteralPath $issPath -Value @'
#define SentinelInstallDir GetEnv("BFA_SENTINEL_INSTALL_DIR")
#define SentinelAppId GetEnv("BFA_SENTINEL_APP_ID")
#if SentinelInstallDir == ""
  #error BFA_SENTINEL_INSTALL_DIR is required
#endif
#if SentinelAppId == ""
  #error BFA_SENTINEL_APP_ID is required
#endif

[Setup]
AppId={#SentinelAppId}
AppName=Building Flutter Apps Uninstall Settlement Sentinel
AppVersion=1.0.0
DefaultDirName={#SentinelInstallDir}
DisableProgramGroupPage=yes
OutputDir={#SourcePath}\out
OutputBaseFilename=sentinel-installer
PrivilegesRequired=lowest
Uninstallable=yes

[Files]
Source: "payload.txt"; DestDir: "{app}"; Flags: ignoreversion
'@

  [Environment]::SetEnvironmentVariable(
    'BFA_SENTINEL_INSTALL_DIR',
    $installDirectory,
    [EnvironmentVariableTarget]::Process
  )
  [Environment]::SetEnvironmentVariable(
    'BFA_SENTINEL_APP_ID',
    $appId,
    [EnvironmentVariableTarget]::Process
  )

  Invoke-OwnedProcess `
    -FilePath $resolvedIsccPath `
    -Arguments @($issPath) `
    -Phase 'sentinel-compile' `
    -TimeoutSeconds $PhaseTimeoutSeconds

  $installerPath = Join-Path $outputDirectory 'sentinel-installer.exe'
  if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw 'Sentinel installer was not produced.'
  }

  Invoke-OwnedProcess `
    -FilePath $installerPath `
    -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-') `
    -Phase 'sentinel-install' `
    -TimeoutSeconds $PhaseTimeoutSeconds

  $installedRegistryViews = @(Get-PresentUninstallRegistryViews -SubKey $uninstallSubKey)
  if ($installedRegistryViews.Count -eq 0) {
    throw 'Sentinel AppId uninstall registry key was not created.'
  }
  if (-not (Test-Path -LiteralPath (Join-Path $installDirectory 'payload.txt') -PathType Leaf)) {
    throw 'Sentinel payload was not installed.'
  }

  $uninstallers = @(Get-ChildItem -LiteralPath $installDirectory -Filter 'unins*.exe' -File)
  if ($uninstallers.Count -ne 1) {
    throw "Expected exactly one owned uninstaller; found $($uninstallers.Count)."
  }

  Invoke-OwnedProcess `
    -FilePath ([string] $uninstallers[0].FullName) `
    -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') `
    -Phase 'sentinel-uninstall-process' `
    -TimeoutSeconds $PhaseTimeoutSeconds
  $uninstallProcessCompleted = $true

  Wait-UninstallSettlement `
    -InstallDirectory $installDirectory `
    -SubKey $uninstallSubKey `
    -TimeoutSeconds $PhaseTimeoutSeconds
  $settlementCompleted = $true

  Write-Host 'INNO_UNINSTALL_SETTLEMENT_OK'
} finally {
  [Environment]::SetEnvironmentVariable(
    'BFA_SENTINEL_INSTALL_DIR',
    $previousInstallDirectory,
    [EnvironmentVariableTarget]::Process
  )
  [Environment]::SetEnvironmentVariable(
    'BFA_SENTINEL_APP_ID',
    $previousAppId,
    [EnvironmentVariableTarget]::Process
  )

  $knownProcessState = if ($uninstallProcessCompleted) {
    'original_process=completed cleanup_clone=unknown'
  } else {
    'original_process=not-completed cleanup_clone=unknown'
  }
  if (-not $settlementCompleted) {
    Write-Warning "phase=sentinel-owned-cleanup result=started $knownProcessState app_id=$appId"
  }

  $presentOwnedViews = @(Get-PresentUninstallRegistryViews -SubKey $uninstallSubKey)
  if ($presentOwnedViews.Count -gt 0) {
    Remove-OwnedRegistryState -SubKey $uninstallSubKey
    $remainingOwnedViews = @(Get-PresentUninstallRegistryViews -SubKey $uninstallSubKey)
    if ($remainingOwnedViews.Count -eq 0) {
      Write-Host 'phase=sentinel-owned-cleanup registry=absent'
    } else {
      Write-Warning "phase=sentinel-owned-cleanup registry=$($remainingOwnedViews -join ',')"
    }
  }

  $rootOwned = $false
  if (Test-Path -LiteralPath $ownerMarker -PathType Leaf) {
    $rootOwned = (Get-Content -LiteralPath $ownerMarker -Raw) -eq $appId
  }
  if ($rootOwned -and (Test-Path -LiteralPath $sentinelRoot)) {
    Remove-Item -LiteralPath $sentinelRoot -Recurse -Force -ErrorAction Continue
    $rootState = if (Test-Path -LiteralPath $sentinelRoot) { 'present' } else { 'absent' }
    Write-Host "phase=sentinel-owned-cleanup root=$rootState"
  } elseif (Test-Path -LiteralPath $sentinelRoot) {
    Write-Warning 'phase=sentinel-owned-cleanup root=retained reason=owner-marker-mismatch'
  }
}
