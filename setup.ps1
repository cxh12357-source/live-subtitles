$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '请安装 Python 3.12 x64 并加入 PATH。' }
}
& .venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络。' }
& .venv/Scripts/python.exe -m captioner.download --model streaming-zh-en
if ($LASTEXITCODE -ne 0) { throw '模型下载失败，可稍后在界面重试。' }
& .venv/Scripts/python.exe -m captioner.download --model sensevoice
if ($LASTEXITCODE -ne 0) { throw '增强模型下载失败，可在界面重试或关闭增强复核使用。' }
