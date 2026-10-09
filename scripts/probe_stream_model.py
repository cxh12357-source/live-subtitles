"""Unpaced real WAV inference: availability in audio-time, not end-to-end latency."""
import json
import time
from pathlib import Path
import numpy as np
import sherpa_onnx
import argparse
from faster_whisper.audio import decode_audio
from captioner.core import DATA
from scripts.compare_recognition import character_error, REFERENCES

parser=argparse.ArgumentParser();parser.add_argument('--zipformer',action='store_true');args=parser.parse_args()
p=DATA/'models'/('streaming-zipformer' if args.zipformer else 'streaming-zh-en')
if args.zipformer:
    r=sherpa_onnx.OnlineRecognizer.from_transducer(tokens=str(p/'tokens.txt'),
        encoder=str(p/'encoder-epoch-99-avg-1.int8.onnx'),decoder=str(p/'decoder-epoch-99-avg-1.onnx'),
        joiner=str(p/'joiner-epoch-99-avg-1.int8.onnx'),num_threads=2,provider='cpu',
        decoding_method='modified_beam_search',max_active_paths=4)
else:
    r=sherpa_onnx.OnlineRecognizer.from_paraformer(tokens=str(p/'tokens.txt'),encoder=str(p/'encoder.int8.onnx'),
        decoder=str(p/'decoder.int8.onnx'),num_threads=2,provider='cpu')
report=[]
for name in ('course','english'):
    s=r.create_stream();a=decode_audio(f'artifacts/{name}.wav')
    a=np.concatenate([a,np.zeros(16000,dtype='float32')]);last='';changes=[];costs=[]
    for i in range(0,len(a),640):
        s.accept_waveform(16000,a[i:i+640]);began=time.perf_counter()
        while r.is_ready(s):r.decode_stream(s)
        costs.append(time.perf_counter()-began)
        text=r.get_result(s)
        if text!=last:changes.append(dict(audio_end=(i+640)/16000,text=text));last=text
    s.input_finished()
    while r.is_ready(s):r.decode_stream(s)
    text=r.get_result(s)
    row=dict(name=name,changes=changes,text=text,cer=character_error(REFERENCES[name],text),
             infer_total=sum(costs),decode_max=max(costs))
    report.append(row);print(json.dumps({k:v for k,v in row.items() if k!='changes'},ensure_ascii=False))
Path('artifacts/'+('zipformer' if args.zipformer else 'stream')+'-model-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
