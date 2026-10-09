import json,time
from pathlib import Path
import sherpa_onnx
from faster_whisper.audio import decode_audio
from captioner.core import DATA
from scripts.speed_probe import tempo,edits,REFERENCES
p=DATA/'models/sensevoice'
r=sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(p/'model.int8.onnx'),tokens=str(p/'tokens.txt'),num_threads=2,use_itn=False)
rows=[]
for name,lang in [('course','zh'),('english','en'),('human-english','en')]:
    original=decode_audio('artifacts/speed/human-english.flac' if name=='human-english' else 'artifacts/'+name+'.wav')
    reference=REFERENCES.get(name,'MISTER QUILTER IS THE APOSTLE OF THE MIDDLE CLASSES AND WE ARE GLAD TO WELCOME HIS GOSPEL')
    for speed in (1,1.25,1.5,2,2.5,3):
        x=tempo(original,speed)
        for stretch in (1,.8):
            began=time.perf_counter();y=tempo(x,stretch);s=r.create_stream();s.accept_waveform(16000,y);r.decode_stream(s)
            text=s.result.text
            row=dict(name=name,speed=speed,stretch=stretch,text=text,seconds=time.perf_counter()-began,**edits(reference,text,lang));rows.append(row)
        print(json.dumps(rows[-2:],ensure_ascii=False),flush=True)
        Path('artifacts/sense-speed-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
