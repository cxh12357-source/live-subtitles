$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
& .venv/Scripts/python.exe -m PyInstaller --noconfirm --windowed --onedir --name LocalCaptions --icon assets/tingjian.ico --collect-all faster_whisper --collect-all ctranslate2 --collect-all tokenizers --collect-all pyaudiowpatch --collect-all onnxruntime --collect-all opencc --collect-all sherpa_onnx --collect-all soxr main.py
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
& .venv/Scripts/python.exe scripts/fix_bundle.py
if ($LASTEXITCODE -ne 0) { throw 'DLL 验证失败' }
& .venv/Scripts/python.exe scripts/collect_licenses.py
