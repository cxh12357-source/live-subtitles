"""Explicit user-triggered downloads; never upload audio/text."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
import requests
from .core import DATA


def download_model(name='base'):
    from huggingface_hub import snapshot_download
    folder = DATA / 'models' / name
    if name=='sensevoice':
        snapshot_download('csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17',local_dir=str(folder),
                          allow_patterns=['model.int8.onnx','tokens.txt','README.md'])
        import hashlib
        if hashlib.sha256((folder/'model.int8.onnx').read_bytes()).hexdigest()!='c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51':
            raise RuntimeError('增强复核模型校验失败，请重新下载。')
        return folder
    if name=='streaming-zh-en':
        snapshot_download('csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en',local_dir=str(folder),
                          allow_patterns=['encoder.int8.onnx','decoder.int8.onnx','tokens.txt','README.md'])
        import hashlib
        expected={'encoder.int8.onnx':'81a70226a8934e6ed92aa1d4fc486b428b5398e2f2619ed4897b7294cab90e9a',
                  'decoder.int8.onnx':'f3cca9f77bb9d93c8fcbfb63ae617b6b1ee96818df3aa3b151c40658fe38594f'}
        for filename,digest in expected.items():
            if hashlib.sha256((folder/filename).read_bytes()).hexdigest()!=digest:
                raise RuntimeError(f'流式模型校验失败：{filename}，请重新下载。')
        return folder
    snapshot_download(f'Systran/faster-whisper-{name}', local_dir=str(folder),
                      allow_patterns=['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.*'])
    return folder


def download_translation(source='en', target='zh'):
    r = requests.get('https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json', timeout=30)
    r.raise_for_status()
    options = [p for p in r.json() if p['from_code'] == source and p['to_code'] == target]
    if not options:
        raise RuntimeError(f'Argos 没有 {source} → {target} 的直接语言包。')
    package = options[-1]
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        with requests.get(package['links'][0], stream=True, timeout=(20, 60),
                          headers={'User-Agent': 'LocalCaptions/0.1 (model download)'}) as response:
            response.raise_for_status()
            with (temp / 'package.zip').open('wb') as out:
                for chunk in response.iter_content(1024*1024):
                    out.write(chunk)
        with zipfile.ZipFile(temp / 'package.zip') as z:
            root = (temp / 'unpacked').resolve()
            for name in z.namelist():
                if not (root / name).resolve().is_relative_to(root):
                    raise RuntimeError('语言包包含非法路径。')
            z.extractall(root)
        metadata = next(root.rglob('metadata.json'))
        folder = metadata.parent
        if not (folder / 'sentencepiece.model').exists():
            raise RuntimeError('此语言包的分词器暂不受支持。')
        destination = DATA / 'translation' / f'{source}_{target}'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, destination, dirs_exist_ok=True)
        return destination


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['sensevoice','streaming-zh-en','tiny', 'base', 'small'])
    parser.add_argument('--translation', nargs=2, metavar=('SOURCE', 'TARGET'))
    args = parser.parse_args()
    print(download_translation(*args.translation) if args.translation else download_model(args.model or 'base'))
