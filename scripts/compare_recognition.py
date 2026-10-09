"""Real ASR on clean WAV fixtures. This is NOT a WASAPI end-to-end test."""
import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from queue import Empty
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
from captioner.core import DATA
from captioner.engine import Engine, owned_text, accept_segment
from captioner.presentation import display_text

REFERENCES = {
    'course':'今天讨论多层平壁的稳态导热。首先确定两侧的边界条件，再计算每一层材料的热阻。总热阻等于各层热阻与两侧对流热阻之和。温度差除以总热阻，就得到通过平壁的热流量。',
    'english':'Hello everyone. This is a test of real time captions. The weather is beautiful today. We are listening to audio from the computer.',
}


def character_error(reference, hypothesis):
    norm=lambda s:re.sub(r'[^\w]','',display_text(s).lower())
    a,b=norm(reference),norm(hypothesis)
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1): new.append(min(new[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]/max(1,len(a))


def windows(engine_type,audio):
    engine=engine_type('unused','unused')
    engine.launch(engine.segment)
    audio=np.concatenate([np.zeros(3200,dtype='float32'),audio,np.zeros(24000,dtype='float32')])
    jobs=[]
    for start in range(0,len(audio),1600):
        block=audio[start:start+1600].astype('float32')
        engine.raw.put((0,(start+len(block))/16000,block.tobytes(),16000,1))
        time.sleep(.002)
        while True:
            try: jobs.append(engine.jobs.get_nowait())
            except Empty: break
    time.sleep(.15)
    while not engine.jobs.empty(): jobs.append(engine.jobs.get_nowait())
    engine.stop()
    for t in engine.threads:t.join(2)
    return jobs


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',default='base'); p.add_argument('--baseline',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hotwords',default='')
    args=p.parse_args()
    model=WhisperModel(str(DATA/'models'/args.model),device='cpu',compute_type='int8',cpu_threads=6,local_files_only=True)
    variants=[('context12_beam5',Engine,5)]
    if args.baseline:
        spec=importlib.util.spec_from_file_location('captioner.baseline',Path('artifacts/engine-before.py'))
        old=importlib.util.module_from_spec(spec); sys.modules[spec.name]=old; spec.loader.exec_module(old)
        variants=[('old6_beam1',old.Engine,1),('context12_beam1',Engine,1)]+variants
    report=[]
    for name in ('course','english'):
        audio=decode_audio(f'artifacts/{name}.wav',sampling_rate=16000)
        for variant,engine_type,beam in variants:
            records=[]
            for job in windows(engine_type,audio):
                old=isinstance(job,tuple)
                final=job[-1] if old else job.final
                if not final:continue
                waveform=job[4] if old else job.audio
                began=time.monotonic()
                segments,info=model.transcribe(waveform,language='zh' if name=='course' else 'en',
                    beam_size=beam,vad_filter=True,word_timestamps=True,condition_on_previous_text=False,
                    vad_parameters={'min_silence_duration_ms':300 if old else 500,'min_speech_duration_ms':200 if old else 250},
                    temperature=0,no_speech_threshold=.55,compression_ratio_threshold=2.4,
                    max_new_tokens=128 if old else 256,hotwords=args.hotwords or None)
                segments=list(segments)
                raw=''.join(s.text for s in segments if accept_segment(s)).strip() if old else owned_text(segments,job.start,job.committed_until,job.commit_through)
                records.append(dict(raw=raw,display=display_text(raw),seconds=time.monotonic()-began,
                                    audio_seconds=len(waveform)/16000))
            text=''.join(r['display'] for r in records)
            row=dict(model=args.model,fixture=name,variant=variant,records=records,
                     hotwords=args.hotwords,reference=REFERENCES[name],cer=character_error(REFERENCES[name],text))
            report.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
