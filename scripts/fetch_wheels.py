"""Development-only download recovery; hashes verified against PyPI metadata."""
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename
from scripts.range_download import download

PACKAGES = ['PySide6-Essentials==6.11.2','shiboken6==6.11.2','faster-whisper==1.2.1',
'PyAudioWPatch==0.2.12.8','scipy','sentencepiece','requests','pytest','pyinstaller','psutil',
'ctranslate2','huggingface-hub','tokenizers','onnxruntime','av','tqdm','numpy','charset-normalizer',
'idna','urllib3','certifi','colorama','iniconfig','packaging','pluggy','pygments','altgraph',
'pefile','pyinstaller-hooks-contrib','pywin32-ctypes','setuptools','pyyaml','click','filelock',
'fsspec','hf-xet','httpx','typing-extensions','flatbuffers','protobuf','anyio','httpcore','h11']


def fetch(spec):
    parts=spec.split('==')
    data=json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{parts[0]}/'+(parts[1]+'/' if len(parts)>1 else '')+'json',timeout=30))
    tags=set(sys_tags())
    candidates=[f for f in data['urls'] if f['filename'].endswith('.whl') and parse_wheel_filename(f['filename'])[3]&tags]
    if not candidates: raise RuntimeError(f'No wheel: {spec}')
    f=candidates[0]
    path=Path('artifacts/wheels')/f['filename']
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==f['digests']['sha256']: return
    download(f['url'],path,f['size'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=f['digests']['sha256']: raise RuntimeError(f'Hash mismatch: {spec}')
    print('VERIFIED '+f['filename'],flush=True)


if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(fetch,PACKAGES))
