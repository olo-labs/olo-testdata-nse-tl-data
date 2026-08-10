[CmdletBinding()]
param(
    [string]$OutputDirectory = "release-assets",
    [long]$MaximumArchiveBytes = 2040109465,
    [long]$TargetSourceBytes = 1800000000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseDirectory = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $repositoryRoot $OutputDirectory
}

if ($MaximumArchiveBytes -le 0 -or $TargetSourceBytes -le 0) {
    throw "Archive size limits must be greater than zero."
}
if ($TargetSourceBytes -ge $MaximumArchiveBytes) {
    throw "TargetSourceBytes must be lower than MaximumArchiveBytes."
}

$sevenZip = @("7z", "7z.exe", "C:\Program Files\7-Zip\7z.exe") |
    ForEach-Object { Get-Command $_ -ErrorAction SilentlyContinue } |
    Select-Object -First 1
if (-not $sevenZip) {
    throw "7-Zip was not found. Install it or add 7z.exe to PATH."
}

if (Test-Path -LiteralPath $releaseDirectory) {
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
}
New-Item -Path $releaseDirectory -ItemType Directory -Force | Out-Null

$sourceFiles = @(Get-ChildItem -LiteralPath (Join-Path $repositoryRoot "database") `
    -Filter "*.parquet" -File -Recurse | Sort-Object FullName)
if ($sourceFiles.Count -eq 0) {
    throw "No database Parquet files were found."
}

$groups = [Collections.Generic.List[object]]::new()
$current = [Collections.Generic.List[IO.FileInfo]]::new()
[long]$currentBytes = 0
foreach ($file in $sourceFiles) {
    if ($file.Length -ge $TargetSourceBytes) {
        throw "A single source file exceeds the part target: $($file.FullName)"
    }
    if ($current.Count -gt 0 -and ($currentBytes + $file.Length) -gt $TargetSourceBytes) {
        $groups.Add($current.ToArray())
        $current = [Collections.Generic.List[IO.FileInfo]]::new()
        $currentBytes = 0
    }
    $current.Add($file)
    $currentBytes += $file.Length
}
if ($current.Count -gt 0) { $groups.Add($current.ToArray()) }

$assets = [Collections.Generic.List[object]]::new()
$checksums = [Collections.Generic.List[string]]::new()
Push-Location $repositoryRoot
try {
    for ($index = 0; $index -lt $groups.Count; $index++) {
        $part = $index + 1
        $archiveName = "NSE-TL-Parquet-part-{0:D3}.zip" -f $part
        $archivePath = Join-Path $releaseDirectory $archiveName
        $listPath = Join-Path $releaseDirectory ("part-{0:D3}.txt" -f $part)
        $relativePaths = @($groups[$index] | ForEach-Object {
            [IO.Path]::GetRelativePath($repositoryRoot, $_.FullName).Replace("\", "/")
        })
        $relativePaths | Set-Content -LiteralPath $listPath -Encoding utf8

        & $sevenZip.Source a -tzip -mx=7 -mmt=on $archivePath "@$listPath" -y -bso0 -bsp0
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed while creating $archiveName." }
        & $sevenZip.Source t $archivePath -bso0 -bsp0
        if ($LASTEXITCODE -ne 0) { throw "Archive integrity check failed: $archiveName" }

        $archive = Get-Item -LiteralPath $archivePath
        if ($archive.Length -le 0 -or $archive.Length -ge $MaximumArchiveBytes) {
            throw "$archiveName is empty or exceeds the configured release limit."
        }
        $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $sourceBytes = [long](($groups[$index] | Measure-Object Length -Sum).Sum)
        $assets.Add([ordered]@{
            dataset = "NSE-TL-Parquet"; part = $part; file = $archiveName
            bytes = $archive.Length; sourceBytes = $sourceBytes; sha256 = $hash
            sourceFileCount = $groups[$index].Count
            firstSourcePath = $relativePaths[0]; lastSourcePath = $relativePaths[-1]
        })
        $checksums.Add("$hash  $archiveName")
        Remove-Item -LiteralPath $listPath -Force
    }
} finally {
    Pop-Location
}

$manifest = [ordered]@{
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    maximumArchiveBytes = $MaximumArchiveBytes
    targetSourceBytes = $TargetSourceBytes
    source = "database/*/*/tl.parquet"
    sourceFileCount = $sourceFiles.Count
    sourceBytes = [long](($sourceFiles | Measure-Object Length -Sum).Sum)
    assets = $assets.ToArray()
}
$manifestPath = Join-Path $releaseDirectory "RELEASE_MANIFEST.json"
$checksumPath = Join-Path $releaseDirectory "SHA256SUMS.txt"
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8
$checksums | Set-Content -LiteralPath $checksumPath -Encoding ascii

if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
    "RELEASE_ASSET_DIRECTORY=$releaseDirectory" >> $env:GITHUB_ENV
    "RELEASE_MANIFEST=$manifestPath" >> $env:GITHUB_ENV
    "RELEASE_CHECKSUMS=$checksumPath" >> $env:GITHUB_ENV
    "RELEASE_DATA_ASSET_COUNT=$($assets.Count)" >> $env:GITHUB_ENV
    "RELEASE_SOURCE_FILE_COUNT=$($sourceFiles.Count)" >> $env:GITHUB_ENV
}
Write-Host "Built $($assets.Count) archive part(s) from $($sourceFiles.Count) Parquet files."
