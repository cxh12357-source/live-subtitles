"""Actual speaker playback -> WASAPI -> Whisper. Does NOT feed files into ASR.

Run from repository root: python -m scripts.loopback_check --seconds 90
Generated Windows TTS fixtures are synthetic speech, but the audio path is real.
"""
import argparse
import json
import time
import winsound
from pathlib import Path
from dataclasses import asdict
import psutil
from captioner.audio import default_device
from captioner.engine import Engine
from captioner.core import DATA


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=90)
    parser.add_argument('--manual',action='store_true',help='Capture browser/player playback instead of winsound')
    parser.add_argument('--language',default=None)
    parser.add_argument('--output',default='artifacts/loopback-report.json')
    args=parser.parse_args()
    engine=Engine(str(DATA/'models'/'base'),default_device(),language=args.language,translate=True)
    engine.start()
    process=psutil.Process()
    records=[]; memory=[]; started=None; played=0; paused=False; resumed=False
    began=time.monotonic()
    try:
        while time.monotonic()-began<args.seconds:
            now=time.monotonic()-began
            while not engine.events.empty():
                kind,value=engine.events.get()
                if kind in ('partial','final'): value=asdict(value)
                records.append(dict(at=round(now,3),kind=kind,value=value))
                print(json.dumps(records[-1],ensure_ascii=False),flush=True)
                if kind=='capture' and started is None: started=now
            if started is not None and not args.manual:
                elapsed=now-started
                # First 8 seconds deliberately silent; pause/resume between fixtures.
                if played==0 and elapsed>8:
                    winsound.PlaySound(str(Path('artifacts/english.wav').resolve()),winsound.SND_FILENAME|winsound.SND_ASYNC); played=1
                if not paused and elapsed>27: engine.pause(True); paused=True
                if not resumed and elapsed>30: engine.pause(False); resumed=True
                if played==1 and elapsed>32:
                    winsound.PlaySound(str(Path('artifacts/chinese.wav').resolve()),winsound.SND_FILENAME|winsound.SND_ASYNC); played=2
                if played>=2 and elapsed>55+(played-2)*20:
                    file='english.wav' if played%2==0 else 'chinese.wav'
                    winsound.PlaySound(str(Path('artifacts')/file),winsound.SND_FILENAME|winsound.SND_ASYNC); played+=1
            memory.append(process.memory_info().rss)
            time.sleep(.1)
    finally:
        winsound.PlaySound(None,0)
        engine.stop()
        for thread in engine.threads: thread.join(30)
        report=dict(device=engine.device,events=records,alive_after_stop=engine.alive(),
                    rss_start=memory[0],rss_end=memory[-1],rss_max=max(memory),
                    rss_samples=memory[::100],dropped=engine.dropped,
                    queues={k:getattr(engine,k).qsize() for k in ['raw','jobs','translations','events']})
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': main()
