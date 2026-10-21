param(
    [switch]$WithAI
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  Vocal Extractor - Environment Setup" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

function Find-WorkingPython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $exe = & $pyLauncher.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path -LiteralPath $exe.Trim())) {
                return $exe.Trim()
            }
        } catch {}
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        try {
            $exe = & $pythonCmd.Source -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path -LiteralPath $exe.Trim())) {
                return $exe.Trim()
            }
        } catch {}
    }

    $searchPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:USERPROFILE\.local\bin\python.exe"
    )
    foreach ($pattern in $searchPaths) {
        $found = Get-Item $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }

    return $null
}

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[1/3] Creating Python virtual environment (.venv)..." -ForegroundColor Yellow
    $SysPython = Find-WorkingPython
    if (-not $SysPython) {
        Write-Host "[ERROR] Python 3.10+ was not found on this system." -ForegroundColor Red
        exit 1
    }
    Write-Host "Using Python: $SysPython" -ForegroundColor Gray
    & $SysPython -m venv .venv
}

Write-Host "[2/3] Upgrading pip..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip

if ($WithAI) {
    Write-Host "[3/3] Installing Demucs AI & SoundFile packages..." -ForegroundColor Green
    & $VenvPython -m pip install -r requirements-ai.txt

    # Check if NVIDIA GPU is present on Windows (e.g. RTX 5060 Ti requires CUDA 12.8 cu128 build)
    $NvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $NvidiaSmi -and (Test-Path "C:\Windows\System32\nvidia-smi.exe")) {
        $NvidiaSmi = "C:\Windows\System32\nvidia-smi.exe"
    }

    if ($NvidiaSmi) {
        $CudaReady = & $VenvPython -c "import torch; print(torch.cuda.is_available())" 2>$null
        if ($CudaReady -notmatch "True") {
            Write-Host "NVIDIA GPU detected! Installing CUDA 12.8 (cu128) PyTorch for RTX 50/40/30 series acceleration..." -ForegroundColor Cyan
            & $VenvPython -m pip install --upgrade --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu128
        }
    }

    Write-Host "[OK] Demucs AI environment (with GPU check) is ready!" -ForegroundColor Green
}
else {
    Write-Host "[3/3] Installing base packages (requirements.txt)..." -ForegroundColor Yellow
    & $VenvPython -m pip install -r requirements.txt
    Write-Host "[OK] Base environment is ready!" -ForegroundColor Green
}
