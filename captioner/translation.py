"""Offline Argos/OpenNMT packages, without cloud services or PyTorch."""
from pathlib import Path
import json
import ctranslate2
import sentencepiece as spm
from opencc import OpenCC
from .core import DATA


class LocalTranslator:
    def __init__(self, root=None):
        self.root = Path(root or DATA / 'translation')
        self.cache = {}
        self.simplified = OpenCC('t2s')

    def translate(self, text, source, target):
        if source == target:
            return self.simplified.convert(text) if target == 'zh' else text
        pair = f'{source}_{target}'
        folder = self.root / pair
        if not (folder / 'model' / 'model.bin').exists():
            raise RuntimeError(f'缺少本地翻译模型 {source} → {target}，请下载对应语言包。')
        if pair not in self.cache:
            # Keep only one loaded pair, bounding memory across automatic language changes.
            self.cache.clear()
            self.cache[pair] = (
                ctranslate2.Translator(str(folder / 'model'), device='cpu', compute_type='int8', intra_threads=4),
                spm.SentencePieceProcessor(model_file=str(folder / 'sentencepiece.model')),
            )
        model, tokenizer = self.cache[pair]
        metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
        prefix = metadata.get('target_prefix', '')
        result = model.translate_batch([tokenizer.encode(text, out_type=str)], beam_size=4,
            target_prefix=[[prefix]] if prefix else None, replace_unknowns=True,
            length_penalty=.2, max_decoding_length=256)[0]
        # Argos SentencePiece models can emit the visible space marker as a
        # literal token. Match the upstream decoder's marker cleanup.
        translated = tokenizer.decode(result.hypotheses[0]).replace('▁', ' ').removeprefix(prefix).strip()
        return self.simplified.convert(translated) if target == 'zh' else translated
