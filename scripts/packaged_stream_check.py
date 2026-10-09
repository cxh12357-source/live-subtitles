"""Explicit EXE smoke test: synthetic speech played through a real WASAPI device.

Temporarily selects a non-default output and restores the original configuration
byte-for-byte. Run with all other LocalCaptions instances closed. Records text
events only, not system audio. Does not change the Windows default output.
"""
import json
from pathlib import Path
import subprocess
import time
import numpy as np
import pyaudiowpatch as pa
import soxr
from faster_whisper.audio import decode_audio
from captioner.core import DATA

root=Path(__file__).resolve().parents[1]
config=DATA/'config.json';backup=config.read_bytes() if config.exists() else None
report=root/'artifacts/packaged-speed.json'
proc=None
try:
    with pa.PyAudio() as audio:
        default=audio.get_default_wasapi_loopback()['name']
        device=next(d for d in audio.get_loopback_device_info_generator() if d['name']!=default)
        host=audio.get_host_api_info_by_type(pa.paWASAPI)['index']
        output=next(audio.get_device_info_by_index(i) for i in range(audio.get_device_count())
                    if audio.get_device_info_by_index(i)['hostApi']==host
                    and audio.get_device_info_by_index(i)['name']==device['name'].replace(' [Loopback]',''))
        config.write_text(json.dumps(dict(schema=3,model='streaming-zh-en',language=None,mode='both',
                                         target='zh',device=device['name'],width=1000,size=30)),encoding='utf-8')
        proc=subprocess.Popen([str(root/'dist/LocalCaptions/LocalCaptions.exe'),'--start','--quit-after','48',
                               '--diagnostics',str(report)],cwd=root)
        time.sleep(8)
        assert proc.poll() is None,'Packaged process failed during startup'
        rate=int(output['defaultSampleRate']);channels=int(output['maxOutputChannels'])
        with audio.open(format=pa.paFloat32,channels=channels,rate=rate,output=True,
                        output_device_index=output['index'],frames_per_buffer=round(rate*.04)) as stream:
            resampler=soxr.ResampleStream(16000,rate,1,dtype='float32',quality='LQ')
            for name in ('course','english'):
                speech=decode_audio(str(root/'artifacts'/f'{name}.wav'))
                speech=np.concatenate([speech,np.zeros(16000*2,dtype='float32')])
                for i in range(0,len(speech),640):
                    block=resampler.resample_chunk(speech[i:i+640])
                    stream.write(np.repeat(block[:,None],channels,axis=1).tobytes(),exception_on_underflow=True)
        assert proc.wait(timeout=30)==0
    data=json.loads(report.read_text(encoding='utf-8'))
    errors=[e for e in data['events'] if e['kind'] in ('error','translation_error')]
    partials=[e for e in data['events'] if e['kind']=='partial']
    finals=[e for e in data['events'] if e['kind']=='final']
    translated=[e for e in data['events'] if e['kind']=='translated']
    displays=[e for e in data['events'] if e['kind']=='display']
    assert data['released'] and partials and finals and translated and not errors,(data['released'],errors)
    assert data['captions']==len({(e['value']['session'],e['value']['epoch'],e['value']['id']) for e in finals})
    assert all(len(e['value']['text'].splitlines())<=2 for e in displays)
    from captioner.presentation import display_text
    assert all(e['value']['text']==display_text(e['value']['text'],'zh') for e in displays)
    assert any(e['at']<finals[0]['at'] for e in partials)
    print(json.dumps(dict(exit_code=proc.returncode,released=data['released'],partials=len(partials),
                          finals=len(finals),translations=len(translated),displays=len(displays),errors=errors)))
finally:
    if proc and proc.poll() is None:
        proc.terminate();proc.wait(timeout=10)
    if backup is not None:config.write_bytes(backup)
    elif config.exists():config.unlink()
