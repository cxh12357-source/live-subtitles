import json,time
from pathlib import Path
import numpy as np
import sherpa_onnx
from faster_whisper.audio import decode_audio
from captioner.core import DATA
from scripts.speed_probe import tempo,edits,REFERENCES
p=DATA/'models/streaming-zh-en'
r=sherpa_onnx.OnlineRecognizer.from_paraformer(tokens=str(p/'tokens.txt'),encoder=str(p/'encoder.int8.onnx'),decoder=str(p/'decoder.int8.onnx'),num_threads=2)
rows=[]
for name,lang in [('course','zh'),('english','en')]:
    original=decode_audio('artifacts/'+name+'.wav')
    for speed in (1,1.25,1.5,2,2.5,3):
        x=tempo(original,speed)
        for stretch in (1,.8,.67,1/speed):
            began=time.perf_counter();y=tempo(x,stretch);s=r.create_stream()
            s.accept_waveform(16000,np.concatenate([y,np.zeros(16000,dtype='float32')]))
            s.set_option('is_final','1');s.input_finished()
            while r.is_ready(s):r.decode_stream(s)
            text=r.get_result(s)
            row=dict(name=name,speed=speed,stretch=stretch,text=text,seconds=time.perf_counter()-began,**edits(REFERENCES[name],text,lang))
            rows.append(row)
        print(json.dumps(rows[-4:],ensure_ascii=False),flush=True)
        Path('artifacts/speed-stretch-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
