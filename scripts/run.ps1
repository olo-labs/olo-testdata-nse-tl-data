param(
    [switch]$Refresh,
    [switch]$Recreate,
    [switch]$Incremental,
    [switch]$VerifyOnly,
    [string[]]$Equity,
    [int]$LimitEquities = 0
)

$ErrorActionPreference = "Stop"
$venv = Join-Path $PSScriptRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$privateRuntime = Join-Path $PSScriptRoot ".python"
$privatePython = Join-Path $privateRuntime "python.exe"
$bootstrap = Join-Path $PSScriptRoot "_bootstrap"
$pythonVersion = "3.12.10"

function Find-BootstrapPython {
    $candidates = [System.Collections.Generic.List[string]]::new()
    $candidates.Add($privatePython)
    $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"))

    foreach ($registryPath in @(
        "HKCU:\Software\Python\PythonCore\3.12\InstallPath",
        "HKLM:\Software\Python\PythonCore\3.12\InstallPath",
        "HKLM:\Software\WOW6432Node\Python\PythonCore\3.12\InstallPath"
    )) {
        if (-not (Test-Path -LiteralPath $registryPath)) { continue }
        $key = Get-Item -LiteralPath $registryPath -ErrorAction SilentlyContinue
        if ($key) {
            $executable = $key.GetValue("ExecutablePath")
            if ($executable) { $candidates.Add([string]$executable) }
            $installPath = $key.GetValue("")
            if ($installPath) { $candidates.Add((Join-Path ([string]$installPath) "python.exe")) }
        }
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import sys; assert sys.version_info >= (3, 10)" 2>$null
        if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[BOOTSTRAP] Python virtual environment is missing: $venv"

    $bootstrapPython = Find-BootstrapPython

    if (-not $bootstrapPython) {
        if ([Environment]::Is64BitOperatingSystem -ne $true) {
            throw "This self-contained launcher requires 64-bit Windows."
        }

        $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
        $installerName = "python-$pythonVersion-$architecture.exe"
        $installer = Join-Path $bootstrap $installerName
        $downloadUrl = "https://www.python.org/ftp/python/$pythonVersion/$installerName"

        New-Item -ItemType Directory -Path $bootstrap -Force | Out-Null
        Write-Host "[BOOTSTRAP] No private Python runtime found."
        Write-Host "[BOOTSTRAP] Downloading official Python $pythonVersion ($architecture) ..."
        Write-Host "[BOOTSTRAP] Source: $downloadUrl"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installer -UseBasicParsing

        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
            $signature.SignerCertificate.Subject -notlike "*Python Software Foundation*") {
            Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
            throw "Downloaded Python installer failed its Authenticode signature check."
        }
        Write-Host "[BOOTSTRAP] Python installer signature verified."
        Write-Host "[BOOTSTRAP] Installing private Python runtime into $privateRuntime ..."

        $installArguments = @(
            "/quiet",
            "InstallAllUsers=0",
            "TargetDir=$privateRuntime",
            "PrependPath=0",
            "AppendPath=0",
            "Include_launcher=0",
            "Include_pip=1",
            "Include_tools=1",
            "Include_test=0",
            "Include_doc=0",
            "Include_tcltk=0",
            "Shortcuts=0"
        )
        $process = Start-Process -FilePath $installer -ArgumentList $installArguments -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) {
            throw "Private Python installation failed with exit code $($process.ExitCode)."
        }

        if (-not (Test-Path -LiteralPath $privatePython)) {
            Write-Host "[BOOTSTRAP] Python is registered but its private files are missing; running installer repair ..."
            $repairArguments = @(
                "/repair",
                "/quiet",
                "InstallAllUsers=0",
                "TargetDir=$privateRuntime",
                "PrependPath=0",
                "AppendPath=0",
                "Include_launcher=0",
                "Include_pip=1",
                "Include_tools=1"
            )
            $repair = Start-Process -FilePath $installer -ArgumentList $repairArguments -Wait -PassThru -WindowStyle Hidden
            if ($repair.ExitCode -ne 0) {
                throw "Python installer repair failed with exit code $($repair.ExitCode)."
            }
        }

        # Some Windows Installer configurations return success before file and
        # registry visibility has propagated to this PowerShell process.
        Write-Host "[BOOTSTRAP] Installer returned success; locating python.exe ..."
        for ($attempt = 1; $attempt -le 30 -and -not $bootstrapPython; $attempt++) {
            $bootstrapPython = Find-BootstrapPython
            if (-not $bootstrapPython) { Start-Sleep -Seconds 1 }
        }
        if (-not $bootstrapPython) {
            throw "Python installer returned exit code 0, but python.exe was not found in the private target, per-user installation, or Python registry entries. Re-run after checking antivirus/install policy logs."
        }
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        Write-Host "[BOOTSTRAP] Python $pythonVersion installed successfully: $bootstrapPython"
    } else {
        Write-Host "[BOOTSTRAP] Found usable Python runtime: $bootstrapPython"
    }

    Write-Host "[BOOTSTRAP] Creating virtual environment ..."
    & $bootstrapPython -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
        throw "Could not create the Python virtual environment at $venv"
    }
    Write-Host "[BOOTSTRAP] Installing required Python packages ..."
    & $python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    Write-Host "[BOOTSTRAP] Environment is ready."
}

$arguments = @((Join-Path $PSScriptRoot "export_citus_to_parquet.py"))
if ($Refresh) { $arguments += "--refresh" }
if ($Recreate) { $arguments += "--recreate" }
if ($Incremental) { $arguments += "--incremental" }
if ($VerifyOnly) { $arguments += "--verify-only" }
if ($LimitEquities -gt 0) { $arguments += @("--limit-equities", $LimitEquities) }
foreach ($item in $Equity) { $arguments += @("--equity", $item) }

& $python @arguments
exit $LASTEXITCODE
