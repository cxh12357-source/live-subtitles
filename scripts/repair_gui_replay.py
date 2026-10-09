"""Actual small-model inference -> real Qt rendering on clean recorded speech.

Transport is WAV replay in real time, NOT a system-loopback test. Includes actual
silence, stop/restart with another source language and clean English translation.
"""
import json
import time
from pathlib import Path
from collections import deque
import numpy as np
from faster_whisper.audio import decode_audio
from PySide6 import QtCore as C, QtWidgets as W
import captioner.engine as backend
import captioner.ui as ui

app=W.QApplication([]); app.setQuitOnLastWindowClosed(False)
ui.load_config=lambda:{'schema':2,'model':'small','language':'zh','mode':'both',
                       'width':900,'size':30,'color':'#ffffff'}
ui.save_config=lambda _:None
window=ui.MainWindow(); window.setWindowTitle('听见 · 修复版语音验收'); window.show()
window.diagnostics=deque(maxlen=10000)
audio=decode_audio('artifacts/course.wav',sampling_rate=16000)
audio=np.concatenate([np.zeros(16000),audio,np.zeros(16000*7)]).astype('float32')
observations=[]; stage='zh'; source_ready=None


def replay(engine):
    global source_ready
    source_ready=time.monotonic()
    engine.emit('capture','验收：真实 WAV 语音实时送入识别器（不是回环）')
    for i in range(0,len(audio),1600):
        if engine.stop_event.is_set():return
        block=audio[i:i+1600]
        if not engine.paused.is_set():
            engine.raw.put((engine.epoch,(i+len(block))/16000,block.tobytes(),16000,1))
        if engine.stop_event.wait(max(0,source_ready+(i+len(block))/16000-time.monotonic())):return
    # Remain silent without inventing text.
    while not engine.stop_event.wait(.1):pass


backend.capture=replay
last_text=None
def observe():
    global last_text,stage,audio,source_ready
    text=window.overlay.label.text()
    if text!=last_text:
        observations.append({'stage':stage,'at':time.monotonic(),'text':text,
                             'height':window.overlay.height(),'labels':len(window.overlay.findChildren(W.QLabel))})
        assert text.count('\n')<=1
        assert len(window.overlay.findChildren(W.QLabel))==1
        last_text=text
    if source_ready and time.monotonic()-source_ready>len(audio)/16000+1:
        assert not text,'Caption should clear during actual zero audio'
        if stage=='zh':
            window.overlay.grab().save('artifacts/repair-silence.png')
            window.stop(); stage='switch'
        elif stage=='en':
            window.stop(); stage='finish'
    if stage=='switch' and window.engine is None:
        window.language.setCurrentIndex(window.language.findData('en'))
        audio=np.concatenate([np.zeros(16000),decode_audio('artifacts/english.wav',sampling_rate=16000),np.zeros(16000*9)]).astype('float32')
        source_ready=None; stage='en'; window.start()
    if stage=='finish' and window.engine is None:
        Path('artifacts/repair-gui-replay.json').write_text(json.dumps(
            {'transport':'clean WAV replay, not WASAPI','events':list(window.diagnostics),
             'observations':observations,'released':True},ensure_ascii=False,indent=2),encoding='utf-8')
        timer.stop(); window.quit()

timer=C.QTimer(); timer.timeout.connect(observe); timer.start(50)
C.QTimer.singleShot(200,window.start)
C.QTimer.singleShot(18000,lambda:window.overlay.grab().save('artifacts/repair-caption.png'))
C.QTimer.singleShot(90000,window.quit)
app.exec()
