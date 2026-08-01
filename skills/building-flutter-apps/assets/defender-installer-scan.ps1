[CmdletBinding(DefaultParameterSetName = 'Scan')]
param(
  [Parameter(Mandatory, ParameterSetName = 'Scan')]
  [string] $MpCmdRunPath,

  [Parameter(Mandatory, ParameterSetName = 'Scan')]
  [string] $TargetPath,

  [Parameter(ParameterSetName = 'Scan')]
  [ValidateRange(5, 600)]
  [int] $TimeoutSeconds = 120,

  [Parameter(ParameterSetName = 'Scan')]
  [ValidateRange(0, 1)]
  [int] $SharingViolationRetries = 1,

  [Parameter(ParameterSetName = 'Scan')]
  [ValidateRange(0, 5)]
  [int] $RetryDelaySeconds = 2,

  [Parameter(Mandatory, ParameterSetName = 'SelfTest')]
  [switch] $SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-HResultHex {
  param(
    [Parameter(Mandatory)]
    [int] $ExitCode
  )

  $bytes = [BitConverter]::GetBytes([int32] $ExitCode)
  $unsigned = [BitConverter]::ToUInt32($bytes, 0)
  return '0x{0:X8}' -f $unsigned
}

function ConvertTo-SignedExitCode {
  param(
    [Parameter(Mandatory)]
    [ValidatePattern('^0x[0-9A-Fa-f]{8}$')]
    [string] $HResult
  )

  $unsigned = [uint32]::Parse(
    $HResult.Substring(2),
    [Globalization.NumberStyles]::HexNumber,
    [Globalization.CultureInfo]::InvariantCulture
  )
  return [BitConverter]::ToInt32([BitConverter]::GetBytes($unsigned), 0)
}

function Get-TextSha256 {
  param(
    [AllowEmptyString()]
    [string] $Text
  )

  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    return [Convert]::ToHexString($algorithm.ComputeHash($bytes)).ToLowerInvariant()
  } finally {
    $algorithm.Dispose()
  }
}

function Get-RedactedDiagnostic {
  param(
    [AllowEmptyString()]
    [string] $Text,

    [Parameter(Mandatory)]
    [string] $ScanTarget
  )

  $redacted = $Text.Replace($ScanTarget, '<scan-target>', [StringComparison]::OrdinalIgnoreCase)
  foreach ($root in @($env:RUNNER_TEMP, $env:TEMP, $env:TMP)) {
    if (-not [string]::IsNullOrWhiteSpace($root)) {
      $redacted = $redacted.Replace($root, '<temp>', [StringComparison]::OrdinalIgnoreCase)
    }
  }
  $redacted = [regex]::Replace(
    $redacted,
    '(?i)(?<![A-Z0-9_])[A-Z]:\\[^\r\n"]+',
    '<path>'
  )

  $safeLines = @(
    $redacted -split '\r?\n' |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
      Select-Object -First 8 |
      ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -gt 240) {
          $line.Substring(0, 240)
        } else {
          $line
        }
      }
  )
  $bounded = $safeLines -join ' | '
  if ($bounded.Length -gt 1600) {
    return $bounded.Substring(0, 1600)
  }
  return $bounded
}

function Invoke-MpCmdRunProcess {
  param(
    [Parameter(Mandatory)]
    [string] $ExecutablePath,

    [Parameter(Mandatory)]
    [string] $ScanTarget,

    [Parameter(Mandatory)]
    [int] $ProcessTimeoutSeconds
  )

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $ExecutablePath
  $startInfo.UseShellExecute = $false
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  foreach ($argument in @(
    '-Scan',
    '-ScanType',
    '3',
    '-File',
    $ScanTarget,
    '-DisableRemediation',
    '-ReturnHR'
  )) {
    $startInfo.ArgumentList.Add([string] $argument)
  }

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  $standardOutput = ''
  $standardError = ''
  $exitCode = 1
  $timedOut = $false
  try {
    if (-not $process.Start()) {
      throw 'phase=defender-scan result=start-failed'
    }
    $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
    $standardErrorTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($ProcessTimeoutSeconds * 1000)) {
      $timedOut = $true
      $process.Kill($true)
      [void] $process.WaitForExit(5000)
    }
    if (-not [Threading.Tasks.Task]::WaitAll(
      [Threading.Tasks.Task[]] @($standardOutputTask, $standardErrorTask),
      5000
    )) {
      throw 'phase=defender-scan result=diagnostic-timeout'
    }
    $standardOutput = $standardOutputTask.Result
    $standardError = $standardErrorTask.Result
    if (-not $timedOut) {
      $exitCode = $process.ExitCode
    }
  } finally {
    $process.Dispose()
  }

  return [pscustomobject] @{
    ExitCode = $exitCode
    StdOut = $standardOutput
    StdErr = $standardError
    TimedOut = $timedOut
  }
}

function Invoke-DefenderScanContract {
  param(
    [Parameter(Mandatory)]
    [string] $ScanTarget,

    [Parameter(Mandatory)]
    [scriptblock] $Runner,

    [ValidateRange(0, 1)]
    [int] $AllowedSharingViolationRetries = 1,

    [ValidateRange(0, 5)]
    [int] $DelaySeconds = 0
  )

  $actionRequiredHResults = @(
    '0x80508021',
    '0x80508022',
    '0x80508023',
    '0x80508024',
    '0x80508025',
    '0x80508026',
    '0x80508027',
    '0x80508029',
    '0x80508030'
  )
  $maximumAttempts = 1 + $AllowedSharingViolationRetries
  for ($attempt = 1; $attempt -le $maximumAttempts; $attempt += 1) {
    $result = & $Runner $attempt $ScanTarget
    if ($result.TimedOut) {
      throw "phase=defender-scan result=timeout attempt=$attempt"
    }

    $hResult = ConvertTo-HResultHex -ExitCode ([int] $result.ExitCode)
    $stdoutHash = Get-TextSha256 -Text ([string] $result.StdOut)
    $stderrHash = Get-TextSha256 -Text ([string] $result.StdErr)
    $safeOutput = Get-RedactedDiagnostic `
      -Text "$($result.StdOut)`n$($result.StdErr)" `
      -ScanTarget $ScanTarget

    if ($hResult -eq '0x00000000') {
      Write-Host "phase=defender-scan result=completed attempt=$attempt hresult=$hResult stdout_sha256=$stdoutHash stderr_sha256=$stderrHash"
      return [pscustomobject] @{
        AttemptCount = $attempt
        HResult = $hResult
        Result = 'completed'
      }
    }

    if (
      $hResult -eq '0x80070020' -and
      $attempt -le $AllowedSharingViolationRetries
    ) {
      Write-Warning "phase=defender-scan result=retryable-sharing-violation attempt=$attempt hresult=$hResult stdout_sha256=$stdoutHash stderr_sha256=$stderrHash diagnostic=$safeOutput"
      if ($DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
      }
      continue
    }

    $classification = if ($hResult -in $actionRequiredHResults) {
      'detection-or-action-required'
    } elseif ($hResult -eq '0x80070020') {
      'sharing-violation-exhausted'
    } else {
      'unknown-hresult'
    }
    throw "phase=defender-scan result=failed classification=$classification attempt=$attempt hresult=$hResult stdout_sha256=$stdoutHash stderr_sha256=$stderrHash diagnostic=$safeOutput"
  }

  throw 'phase=defender-scan result=internal-attempt-bound-violated'
}

function Assert-FixtureThrows {
  param(
    [Parameter(Mandatory)]
    [scriptblock] $Action,

    [Parameter(Mandatory)]
    [string[]] $ExpectedFragments,

    [Parameter(Mandatory)]
    [string] $ForbiddenText
  )

  try {
    & $Action
  } catch {
    $message = $_.Exception.Message
    foreach ($fragment in $ExpectedFragments) {
      if (-not $message.Contains($fragment, [StringComparison]::Ordinal)) {
        throw "Fixture failure missing expected fragment: $fragment"
      }
    }
    if ($message.Contains($ForbiddenText, [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Fixture failure leaked the scan target.'
    }
    return
  }
  throw 'Fixture expected a fail-closed result.'
}

function Invoke-DefenderScanFixtures {
  $fixtureTarget = 'C:\private\candidate.exe'

  $cleanRunner = {
    param($Attempt, $ScanTarget)
    return [pscustomobject] @{
      ExitCode = 0
      StdOut = "clean $ScanTarget"
      StdErr = ''
      TimedOut = $false
    }
  }
  $clean = Invoke-DefenderScanContract `
    -ScanTarget $fixtureTarget `
    -Runner $cleanRunner `
    -AllowedSharingViolationRetries 1
  if ($clean.AttemptCount -ne 1 -or $clean.HResult -ne '0x00000000') {
    throw 'Clean fixture did not complete on its first attempt.'
  }

  $detectionRunner = {
    param($Attempt, $ScanTarget)
    return [pscustomobject] @{
      ExitCode = ConvertTo-SignedExitCode -HResult '0x80508025'
      StdOut = "Threat requires manual action: $ScanTarget"
      StdErr = ''
      TimedOut = $false
    }
  }
  Assert-FixtureThrows `
    -Action {
      Invoke-DefenderScanContract `
        -ScanTarget $fixtureTarget `
        -Runner $detectionRunner `
        -AllowedSharingViolationRetries 1
    } `
    -ExpectedFragments @(
      'classification=detection-or-action-required',
      'attempt=1',
      'hresult=0x80508025'
    ) `
    -ForbiddenText $fixtureTarget

  $unknownRunner = {
    param($Attempt, $ScanTarget)
    return [pscustomobject] @{
      ExitCode = ConvertTo-SignedExitCode -HResult '0x81234567'
      StdOut = ''
      StdErr = "Unexpected scanner failure for $ScanTarget"
      TimedOut = $false
    }
  }
  Assert-FixtureThrows `
    -Action {
      Invoke-DefenderScanContract `
        -ScanTarget $fixtureTarget `
        -Runner $unknownRunner `
        -AllowedSharingViolationRetries 1
    } `
    -ExpectedFragments @(
      'classification=unknown-hresult',
      'attempt=1',
      'hresult=0x81234567'
    ) `
    -ForbiddenText $fixtureTarget

  $sharingState = [pscustomobject] @{ CallCount = 0 }
  $sharingRunner = {
    param($Attempt, $ScanTarget)
    $sharingState.CallCount += 1
    $exitCode = if ($sharingState.CallCount -eq 1) {
      ConvertTo-SignedExitCode -HResult '0x80070020'
    } else {
      0
    }
    return [pscustomobject] @{
      ExitCode = $exitCode
      StdOut = ''
      StdErr = "Transient sharing state for $ScanTarget"
      TimedOut = $false
    }
  }.GetNewClosure()
  $sharing = Invoke-DefenderScanContract `
    -ScanTarget $fixtureTarget `
    -Runner $sharingRunner `
    -AllowedSharingViolationRetries 1
  if ($sharing.AttemptCount -ne 2 -or $sharingState.CallCount -ne 2) {
    throw 'Sharing-violation fixture did not retry exactly once.'
  }

  Write-Host 'DEFENDER_SCAN_FIXTURES_OK clean=green detection=red unknown=red sharing_violation_retry=green'
}

if ($SelfTest) {
  Invoke-DefenderScanFixtures
  return
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
  throw 'The Defender installer scanner requires Windows.'
}
if (-not (Test-Path -LiteralPath $MpCmdRunPath -PathType Leaf)) {
  throw 'MpCmdRunPath must resolve to one existing executable.'
}
if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
  throw 'TargetPath must resolve to one existing installer.'
}

$resolvedScanner = [IO.Path]::GetFullPath($MpCmdRunPath)
$resolvedTarget = [IO.Path]::GetFullPath($TargetPath)
$processRunner = {
  param($Attempt, $ScanTarget)
  return Invoke-MpCmdRunProcess `
    -ExecutablePath $resolvedScanner `
    -ScanTarget $ScanTarget `
    -ProcessTimeoutSeconds $TimeoutSeconds
}.GetNewClosure()

Invoke-DefenderScanContract `
  -ScanTarget $resolvedTarget `
  -Runner $processRunner `
  -AllowedSharingViolationRetries $SharingViolationRetries `
  -DelaySeconds $RetryDelaySeconds
