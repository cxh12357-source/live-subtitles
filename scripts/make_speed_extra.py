"""Stress fixture: reduced pauses and repeated complete phrases (synthetic)."""
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from faster_whisper.audio import decode_audio
from scripts.speed_probe import REFERENCES
p=Path('artifacts/speed');x=decode_audio('artifacts/course.wav');blocks=[];quiet=[]
for i in range(0,len(x),160):
    b=x[i:i+160]
    if np.sqrt(np.mean(b*b))<.003:quiet.append(b)
    else:
        if quiet:
            blocks.extend(quiet if len(quiet)<30 else quiet[:6]+quiet[-6:]);quiet=[]
        blocks.append(b)
blocks.extend(quiet[:12]);joined=np.concatenate(blocks)
long=np.concatenate([joined,np.zeros(1600,dtype='float32'),joined])
wavfile.write(p/'course-continuous.wav',16000,long)
entry=dict(name='course-continuous',language='zh',reference=REFERENCES['course']*2,speed='continuous',path=str(p/'course-continuous.wav'),source='SAPI, quiet spans >=300ms shortened to120ms')
(p/'long.json').write_text(json.dumps([entry],ensure_ascii=False),encoding='utf-8')
manifest=json.loads((p/'manifest.json').read_text(encoding='utf-8'))
(p/'terms.json').write_text(json.dumps([r for r in manifest if r['name']=='course' and r['speed'] in (1.5,2)],ensure_ascii=False),encoding='utf-8')
print('Continuous speech seconds:',len(long)/16000)
