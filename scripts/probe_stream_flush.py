"""Real model ablation for endpoint padding; unpaced, not a latency benchmark."""
import json
from pathlib import Path
import numpy as np
import sherpa_onnx
from faster_whisper.audio import decode_audio
from captioner.core import DATA
from scripts.compare_recognition import REFERENCES,character_error

p=DATA/'models/streaming-zh-en'
r=sherpa_onnx.OnlineRecognizer.from_paraformer(tokens=str(p/'tokens.txt'),encoder=str(p/'encoder.int8.onnx'),
    decoder=str(p/'decoder.int8.onnx'),num_threads=2,provider='cpu')
speech=decode_audio('artifacts/english.wav')
rows=[]
for padding in (0,.32,.64):
    for shift in (0,.12,.24,.36,.48):
        audio=np.concatenate([np.zeros(round(shift*16000)),speech,np.zeros(32000)]).astype('float32')
        s=r.create_stream();last_voice=0;active=False;texts=[]
        for i in range(0,len(audio),640):
            chunk=audio[i:i+640];end=(i+len(chunk))/16000
            if np.sqrt(np.mean(chunk*chunk))>.003:active=True;last_voice=end
            s.accept_waveform(16000,chunk)
            final=active and end-last_voice>=.6
            if final:
                if padding:s.accept_waveform(16000,np.zeros(round(padding*16000),dtype='float32'))
                s.set_option('is_final','1');s.input_finished()
            while r.is_ready(s):r.decode_stream(s)
            if final:
                texts.append(r.get_result(s));s=r.create_stream();active=False
        row=dict(padding=padding,shift=shift,text=''.join(texts),cer=character_error(REFERENCES['english'],''.join(texts)))
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
Path('artifacts/stream-flush-ablation.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
