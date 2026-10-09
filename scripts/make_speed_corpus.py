"""Generate pitch-preserving playback variants, never alter the WAV sample rate."""
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from faster_whisper.audio import decode_audio
from scripts.speed_probe import tempo,REFERENCES
folder=Path('artifacts/speed');folder.mkdir(exist_ok=True)
manifest=[]
for name,language in [('course','zh'),('english','en'),('human-english','en')]:
    original=decode_audio(str(folder/'human-english.flac') if name=='human-english' else f'artifacts/{name}.wav')
    reference=REFERENCES.get(name,'MISTER QUILTER IS THE APOSTLE OF THE MIDDLE CLASSES AND WE ARE GLAD TO WELCOME HIS GOSPEL')
    for speed in (1,1.25,1.5,2,2.5,3):
        x=tempo(original,speed);path=folder/f'{name}-{speed}.wav';wavfile.write(path,16000,x)
        manifest.append(dict(name=name,language=language,reference=reference,speed=speed,path=str(path),source='SAPI synthetic' if name!='human-english' else 'LibriSpeech 1272-128104-0000'))
    # Switching within a single utterance, not just between isolated phrases.
    parts=np.array_split(original,4);rates=(1.,2.,1.25,2.5)
    x=np.concatenate([tempo(part,rate) for part,rate in zip(parts,rates)])
    path=folder/f'{name}-switch.wav';wavfile.write(path,16000,x)
    manifest.append(dict(name=name,language=language,reference=reference,speed='switch 1-2-1.25-2.5',path=str(path),source='SAPI synthetic' if name!='human-english' else 'LibriSpeech 1272-128104-0000'))
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(folder/'pilot.json').write_text(json.dumps([manifest[3],manifest[10],manifest[17]],ensure_ascii=False,indent=2),encoding='utf-8')
print('One pass seconds:',1+sum(len(decode_audio(e['path']))/16000+2 for e in manifest))
