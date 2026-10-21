$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "First launch detected. Running setup.ps1..." -ForegroundColor Yellow
    & (Join-Path $ProjectDir "setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

# Ensure streamlit is installed in .venv
& $VenvPython -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing required packages into .venv..." -ForegroundColor Yellow
    & (Join-Path $ProjectDir "setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

# Bypass Streamlit first-run interactive email prompt so it never blocks browser launch
$StreamlitUserDir = Join-Path $env:USERPROFILE ".streamlit"
$CredentialsFile = Join-Path $StreamlitUserDir "credentials.toml"
if (-not (Test-Path -LiteralPath $CredentialsFile)) {
    New-Item -ItemType Directory -Path $StreamlitUserDir -Force | Out-Null
    Set-Content -LiteralPath $CredentialsFile -Value "[general]`r`nemail = `"`"`r`n" -Encoding UTF8
}

$Port = 8500
$AppUrl = "http://127.0.0.1:$Port"

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  Starting Vocal Extractor on $AppUrl" -ForegroundColor Cyan
Write-Host "  (Keep this window open while using the app)" -ForegroundColor Yellow
Write-Host "====================================================" -ForegroundColor Cyan

# Start background watcher to open browser automatically once port 8501 is ready
Start-Job -ScriptBlock {
    param($url, $port)
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $connect = $client.BeginConnect("127.0.0.1", $port, $null, $null)
            $wait = $connect.AsyncWaitHandle.WaitOne(300, $false)
            if ($wait -and $client.Connected) {
                $client.Close()
                Start-Process $url
                break
            }
            $client.Close()
        } catch {}
    }
} -ArgumentList $AppUrl, $Port | Out-Null

& $VenvPython -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
