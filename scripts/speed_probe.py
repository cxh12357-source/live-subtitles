"""Offline diagnostic only: real WAV ASR, no claims of real-time/UI latency."""
import json,time,re
from pathlib import Path
from fractions import Fraction
import av
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
import sherpa_onnx
from captioner.core import DATA
from scripts.compare_recognition import REFERENCES,character_error

def tempo(audio,factor):
    if factor==1:return audio.copy()
    graph=av.filter.Graph()
    source=graph.add_abuffer(sample_rate=16000,format='fltp',layout='mono',time_base=Fraction(1,16000))
    tail=source
    # Chain moderate factors; atempo >2 may skip samples per FFmpeg docs.
    factors=[]
    while factor>2:factors.append(2.);factor/=2
    while factor<.5:factors.append(.5);factor/=.5
    factors.append(factor)
    for f in factors:
        node=graph.add('atempo',str(f));tail.link_to(node);tail=node
    sink=graph.add('abuffersink');tail.link_to(sink);graph.configure();out=[]
    for i in range(0,len(audio),4096):
        frame=av.AudioFrame.from_ndarray(audio[None,i:i+4096].astype('float32'),format='fltp',layout='mono')
        frame.sample_rate=16000;frame.pts=i;frame.time_base=Fraction(1,16000);source.push(frame)
        while True:
            try:out.append(sink.pull().to_ndarray().ravel())
            except (av.error.BlockingIOError,av.error.EOFError):break
    source.push(None)
    while True:
        try:out.append(sink.pull().to_ndarray().ravel())
        except (av.error.BlockingIOError,av.error.EOFError):break
    return np.concatenate(out)

def edits(reference,hypothesis,language):
    norm=lambda s:re.sub(r'[^\w\s]',' ',s.lower()).split() if language=='en' else list(re.sub(r'[^\w]','',s))
    from captioner.presentation import display_text
    a,b=norm(display_text(reference)),norm(display_text(hypothesis))
    rows=[[(j,0,j,0) for j in range(len(b)+1)]]
    for i,x in enumerate(a,1):
        row=[(i,i,0,0)]
        for j,y in enumerate(b,1):
            d=rows[-1][j];ins=row[-1];sub=rows[-1][j-1]
            row.append(min((d[0]+1,d[1]+1,d[2],d[3]),(ins[0]+1,ins[1],ins[2]+1,ins[3]),
                           (sub[0]+(x!=y),sub[1],sub[2],sub[3]+(x!=y)),key=lambda z:z[0]))
        rows.append(row)
    e,d,i,s=rows[-1][-1]
    return dict(rate=e/max(1,len(a)),deletions=d,insertions=i,substitutions=s,reference_units=len(a))

def main():
    folder=DATA/'models/streaming-zh-en'
    online=sherpa_onnx.OnlineRecognizer.from_paraformer(tokens=str(folder/'tokens.txt'),encoder=str(folder/'encoder.int8.onnx'),decoder=str(folder/'decoder.int8.onnx'),num_threads=2)
    models={n:WhisperModel(str(DATA/'models'/n),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True) for n in ('base','small')}
    rows=[]
    for name,lang in [('course','zh'),('english','en')]:
        for speed in (1,1.25,1.5,2,2.5,3):
            x=tempo(decode_audio('artifacts/'+name+'.wav'),speed)
            stream=online.create_stream();began=time.perf_counter()
            for i in range(0,len(x),640):
                stream.accept_waveform(16000,x[i:i+640])
                while online.is_ready(stream):online.decode_stream(stream)
            stream.accept_waveform(16000,np.zeros(16000,dtype='float32'));stream.set_option('is_final','1');stream.input_finished()
            while online.is_ready(stream):online.decode_stream(stream)
            text=online.get_result(stream)
            rows.append(dict(name=name,speed=speed,model='paraformer',text=text,seconds=time.perf_counter()-began,**edits(REFERENCES[name],text,lang)))
            for model in models:
                for beam in (1,3):
                    began=time.perf_counter()
                    segments,_=models[model].transcribe(x,language=lang,beam_size=beam,vad_filter=False,temperature=0,condition_on_previous_text=False)
                    text=''.join(s.text for s in segments)
                    rows.append(dict(name=name,speed=speed,model=model,beam=beam,text=text,seconds=time.perf_counter()-began,**edits(REFERENCES[name],text,lang)))
            print(json.dumps(rows[-5:],ensure_ascii=False),flush=True)
            Path('artifacts/speed-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
