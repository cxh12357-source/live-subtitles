"""Timed real speech -> actual ASR/MT -> Qt display. No fake transcript events.

replay = paced WAV transport, NOT WASAPI; loopback = actual speaker playback and
WASAPI. Logs timestamps/text only, never records live PCM. Models load before the
test clock. Keep other audio quiet for loopback measurements.
"""
import argparse
import hashlib
from collections import deque
import importlib.util
import json
from pathlib import Path
import sys
import time
import winsound
from threading import Thread, Event
import numpy as np
import psutil
from scipy.io import wavfile
from faster_whisper.audio import decode_audio
from PySide6 import QtCore as C, QtWidgets as W
from captioner.core import DATA
import captioner.ui as ui
import captioner.engine as legacy


def corpus(seconds):
    blocks=[np.zeros(16000,dtype='float32')]; schedule=[]; end=1.
    while end < seconds:
        for name,lang in [('course','zh'),('english','en')]:
            x=decode_audio('artifacts/'+name+'.wav',sampling_rate=16000)
            active=[i for i in range(0,len(x),160) if np.sqrt(np.mean(x[i:i+160]**2))>.003]
            if end+len(x)/16000+3>seconds: return np.concatenate(blocks),schedule
            schedule.append(dict(index=len(schedule),fixture=name,language=lang,start=end,
                                 speech_start=end+active[0]/16000,speech_end=end+(active[-1]+160)/16000,
                                 end=end+len(x)/16000))
            blocks.extend([x,np.zeros(16000*3,dtype='float32')]); end+=len(x)/16000+3
    return np.concatenate(blocks),schedule


def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['baseline','speed-baseline','stream','reviewed'],default='stream')
    p.add_argument('--corpus',type=Path,help='Explicit local test manifest with audio, language and reference')
    p.add_argument('--speed-hint',type=float,default=0)
    p.add_argument('--hotwords',default='')
    p.add_argument('--language',default=None)
    p.add_argument('--transport',choices=['replay','loopback'],default='replay')
    p.add_argument('--seconds',type=int,default=120);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['original','both','translation'],default='both')
    p.add_argument('--isolated-device',action='store_true',help='Play/capture the non-default WASAPI output endpoint')
    args=p.parse_args(); audio,schedule=corpus(args.seconds)
    source_hashes={f:hashlib.sha256(Path('captioner',f).read_bytes()).hexdigest() for f in ('streaming.py','review.py','audio.py','ui.py')}
    print('Preparing corpus',flush=True)
    if args.corpus:
        entries=json.loads(args.corpus.read_text(encoding='utf-8'));blocks=[np.zeros(16000,dtype='float32')];schedule=[];end=1.
        while end<args.seconds:
            added=False
            for entry in entries:
                x=decode_audio(entry['path'],sampling_rate=16000)
                if end+len(x)/16000+2>args.seconds:break
                active=[i for i in range(0,len(x),160) if np.sqrt(np.mean(x[i:i+160]**2))>.003]
                schedule.append(dict(entry,index=len(schedule),fixture=entry['name'],start=end,
                                     speech_start=end+active[0]/16000,speech_end=end+(active[-1]+160)/16000,end=end+len(x)/16000))
                blocks.extend([x,np.zeros(32000,dtype='float32')]);end+=len(x)/16000+2;added=True
            if not added:break
        audio=np.concatenate(blocks)
    print('Corpus ready: '+str(len(schedule))+' clips',flush=True)
    # Pad to the requested duration, including a final true-silence check.
    audio=np.pad(audio,(0,max(0,args.seconds*16000-len(audio))))
    if args.variant=='baseline':
        spec=importlib.util.spec_from_file_location('captioner.latency_baseline',Path('artifacts/latency-baseline-engine.py'))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        cls=module.Engine; model='small'
    elif args.variant=='speed-baseline':
        spec=importlib.util.spec_from_file_location('captioner.speed_baseline',Path('artifacts/speed-baseline-streaming.py'))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        cls=module.StreamingEngine;model='streaming-zh-en'
    else:
        import captioner.streaming as module
        cls=module.StreamingEngine;model='streaming-zh-en'
        if args.variant=='reviewed':
            from captioner.review import ReviewedEngine
            cls=ReviewedEngine
    events=[]; memory=[]; begun=None; engine_ref=None; done=False;last_progress=0
    playback_stop=Event();playback_thread=None;captured=[];capture_samples=0;calibration=None
    device=None;output_device=None
    if args.isolated_device:
        import pyaudiowpatch as pa
        with pa.PyAudio() as audio_api:
            default=audio_api.get_default_wasapi_loopback()['name']
            device=next(d['name'] for d in audio_api.get_loopback_device_info_generator() if d['name']!=default)
            host=audio_api.get_host_api_info_by_type(pa.paWASAPI)['index']
            output_device=next(audio_api.get_device_info_by_index(i) for i in range(audio_api.get_device_count())
                               if audio_api.get_device_info_by_index(i)['hostApi']==host
                               and audio_api.get_device_info_by_index(i)['name']==device.replace(' [Loopback]',''))
    output=args.output;output.parent.mkdir(parents=True,exist_ok=True)
    playback=output.with_suffix('.playback.wav')
    if args.transport=='loopback' and not args.isolated_device:
        wavfile.write(playback,16000,(np.clip(audio,-1,1)*32767).astype('int16'))
    def trace(row):
        row['t']=row['at']-engine_ref.origin
        events.append(row)
    def replay(engine):
        engine.emit('capture','验收：真实语音 WAV 按时钟送入（非系统回环）')
        block_size=1600 if args.variant=='baseline' else 640
        for i in range(0,len(audio),block_size):
            if engine.stop_event.is_set():return
            end=min(i+block_size,len(audio))/16000
            if engine.stop_event.wait(max(0,engine.origin+end-time.monotonic())):return
            if not engine.paused.is_set():
                engine.raw.put((engine.epoch,end,audio[i:i+block_size].astype('float32').tobytes(),16000,1,False,
                                {'captured_at':time.monotonic()}))
                engine.trace('capture',audio_end=end,block_ms=block_size/16,portaudio_age_ms=None)
        while not engine.stop_event.wait(.04): pass
    if args.transport=='replay': module.capture=replay
    def observe_audio(data,rate,channels):
        nonlocal capture_samples
        if capture_samples<16000*34:
            from captioner.audio import mono16
            x=mono16(data,rate,channels);captured.append(x);capture_samples+=len(x)
    def isolated_playback():
        import pyaudiowpatch as pa
        import soxr
        with pa.PyAudio() as audio_api:
            rate=int(output_device['defaultSampleRate']);channels=int(output_device['maxOutputChannels'])
            resampler=soxr.ResampleStream(16000,rate,1,dtype='float32',quality='LQ')
            with audio_api.open(format=pa.paFloat32,channels=channels,rate=rate,output=True,
                                output_device_index=output_device['index'],frames_per_buffer=round(rate*.04)) as out:
                offset=time.monotonic()-engine_ref.origin+out.get_output_latency()
                for s in schedule:
                    for key in ('start','speech_start','speech_end','end'):s[key]+=offset
                trace(dict(stage='playback',at=time.monotonic(),output_latency_ms=out.get_output_latency()*1000,
                           output_device=output_device['name'],rate=rate))
                for i in range(0,len(audio),640):
                    if playback_stop.is_set():break
                    x=resampler.resample_chunk(audio[i:i+640]);x=np.repeat(x[:,None],channels,axis=1)
                    try:out.write(x.tobytes(),exception_on_underflow=True)
                    except OSError as e:trace(dict(stage='playback_error',at=time.monotonic(),error=str(e)))
    ui.load_config=lambda:{'schema':3,'model':model,'language':args.language,'mode':args.mode,'width':1000,'size':30}
    ui.save_config=lambda _:None
    app=W.QApplication([]);app.setQuitOnLastWindowClosed(False)
    def factory(*a,**kw):
        nonlocal engine_ref
        extra={'speed_hint':args.speed_hint} if args.variant=='reviewed' else {}
        engine_ref=cls(str(DATA/'models'/model),device or a[1],language=args.language,target='zh',translate=args.mode!='original',hotwords=args.hotwords,**extra)
        engine_ref.trace_sink=trace
        original_emit=engine_ref.emit
        def checked_emit(kind,value):
            if kind in ('error','translation_error'):engine_ref.trace('error',kind=kind,message=value)
            original_emit(kind,value)
        engine_ref.emit=checked_emit
        if args.transport=='loopback':engine_ref.audio_observer=observe_audio
        return engine_ref
    ui.Engine=factory
    w=ui.MainWindow();w.setWindowTitle('听见 · 延迟测量');w.show()
    print('UI ready',flush=True)
    process=psutil.Process(); start_wall=time.monotonic(); last_memory=0
    def poll():
        nonlocal begun,done,last_memory,playback_thread,calibration,last_progress
        now=time.monotonic()
        if engine_ref and begun is None and 'capture' in w.statuses:
            begun=engine_ref.origin
            if args.transport=='loopback':
                # Align schedule with actual PlaySound invocation, preserving engine audio clock.
                if args.isolated_device:
                    playback_thread=Thread(target=isolated_playback);playback_thread.start()
                else:
                    offset=now-engine_ref.origin
                    for s in schedule:
                        for key in ('start','speech_start','speech_end','end'):s[key]+=offset
                    winsound.PlaySound(str(playback.resolve()),winsound.SND_FILENAME|winsound.SND_ASYNC)
                begun=now
        if now-last_memory>=2:
            memory.append(dict(t=now-(begun or start_wall),rss=process.memory_info().rss,
                               raw=engine_ref.raw.qsize() if engine_ref else 0,
                               jobs=engine_ref.jobs.qsize() if engine_ref else 0))
            last_memory=now
        if not done and begun and now-begun>args.seconds+3:
            done=True;w.stop()
        if begun and now-begun-last_progress>=30:
            last_progress=now-begun
            print(json.dumps({'seconds':round(last_progress),'rss_mib':round(process.memory_info().rss/1048576,1),
                              'audio_drops':engine_ref.dropped,'raw_queue':engine_ref.raw.qsize(),
                              'asr_queue':engine_ref.jobs.qsize()},ensure_ascii=False),flush=True)
        if begun and calibration is None and now-begun>36 and args.transport=='loopback':
            from scipy.signal import correlate
            x=np.concatenate(captured);reference=audio[:16000*22]
            offset=int(np.argmax(correlate(x,reference,mode='valid',method='fft')))
            correlation=float(np.corrcoef(x[offset:offset+len(reference)],reference)[0,1])
            calibration={'captured_offset_seconds':offset/16000,'correlation':correlation}
            first_capture=next(e for e in events if e['stage']=='capture')
            calibration['engine_offset_seconds']=offset/16000+first_capture['audio_end']-first_capture['block_ms']/1000
            print('Loopback calibration: '+json.dumps(calibration),flush=True)
            captured.clear()
            if not np.isfinite(correlation) or correlation<.65:
                events.append(dict(stage='validation_error',at=now,t=now-engine_ref.origin,
                                   error='Loopback did not sufficiently match the known playback'))
                done=True;w.stop()
        if begun is None and now-start_wall>30 and not done:
            print('Startup failed: '+json.dumps(dict(statuses=w.statuses,error=w.error.text()),ensure_ascii=False),flush=True)
            done=True;w.stop()
        if now-start_wall>args.seconds+90 and not done:
            done=True;w.stop()
        if done and w.engine is None:
            playback_stop.set()
            if playback_thread:playback_thread.join(3)
            if args.transport=='loopback':winsound.PlaySound(None,0)
            report=dict(variant=args.variant,transport=args.transport,requested_seconds=args.seconds,
                        source_hashes=source_hashes,
                        model=model,mode=args.mode,schedule=schedule,events=events,memory=memory,
                        released=not engine_ref.alive() if engine_ref else True,dropped=engine_ref.dropped if engine_ref else 0,device=engine_ref.device if engine_ref else device,
                        calibration=calibration)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Saved '+str(output),flush=True);timer.stop();w.quit()
    timer=C.QTimer();timer.timeout.connect(poll);timer.start(20)
    C.QTimer.singleShot(200,w.start)
    app.exec()

if __name__=='__main__':main()
