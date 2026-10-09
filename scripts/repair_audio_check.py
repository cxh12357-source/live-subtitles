"""Explicit short diagnostic: real playback -> WASAPI -> ASR; no fabricated ASR.
Run with --file a.wav --language zh --output artifacts/check.json.
Only this explicitly invoked script saves the captured 16 kHz audio beside JSON.
"""
import argparse
import json
import time
import winsound
from dataclasses import asdict
from pathlib import Path
import numpy as np
from scipy.io import wavfile
import captioner.engine as module
from captioner.streaming import StreamingEngine
from captioner.audio import default_device, devices
from captioner.core import DATA, load_config
from captioner.presentation import display_text
from datetime import datetime


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--file', type=Path)
    p.add_argument('--language')
    p.add_argument('--seconds', type=int, default=28)
    p.add_argument('--model')
    p.add_argument('--device')
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    config=load_config()
    if args.output is None:
        args.output=Path('artifacts/diagnostics')/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    print('显式诊断录音已启动；将保存选定输出设备上的全部声音。保存位置：'+str(args.output.with_suffix('.wav').resolve()),flush=True)
    chunks = []; formats = set(); records = []
    original = module.mono16
    def observed(data, rate, channels):
        result = original(data, rate, channels)
        chunks.append(result.copy()); formats.add((rate, channels, len(data)//(channels*4)))
        return result
    selected_model=args.model or config.get('model','streaming-zh-en')
    engine_class=StreamingEngine if selected_model=='streaming-zh-en' else module.Engine
    engine = engine_class(str(DATA/'models'/selected_model),
                           args.device or config.get('device') or default_device(),
                           language=args.language or config.get('language'))
    engine.audio_observer = observed
    engine.start(); began = time.monotonic(); played = False; ready = None
    try:
        while time.monotonic()-began < args.seconds:
            now = time.monotonic()-began
            while not engine.events.empty():
                kind, value = engine.events.get()
                if kind == 'capture' and ready is None: ready = now
                if kind in ('partial', 'final'):
                    value = asdict(value)
                    value['simplified_display']=display_text(value['text'],value['language'])
                records.append({'at':round(now,3), 'kind':kind, 'value':value})
            if args.file and ready is not None and now-ready > 2 and not played:
                winsound.PlaySound(str(args.file.resolve()), winsound.SND_FILENAME | winsound.SND_ASYNC)
                played = True
            time.sleep(.02)
    finally:
        if args.file: winsound.PlaySound(None, 0)
        engine.stop()
        for t in engine.threads: t.join(30)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype='float32')
        wavfile.write(args.output.with_suffix('.wav'), 16000, audio)
        report = dict(device=engine.device, devices=devices(), formats=list(formats),
                      captured_seconds=len(audio)/16000, elapsed=time.monotonic()-began,
                      dropped=engine.dropped, released=not engine.alive(), events=records)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('devices','events')}, ensure_ascii=False))
        for row in records:
            if row['kind']=='final': print(row['value']['text'])

if __name__ == '__main__': main()
