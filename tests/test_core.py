from queue import Queue
import numpy as np
from captioner.core import latest_put, Caption, export, stamp
from captioner.audio import mono16
from captioner.engine import Engine
from captioner.translation import LocalTranslator
import time


def test_queue_discards_oldest_under_load():
    q=Queue(2)
    for i in range(10000): latest_put(q,i)
    assert q.qsize()==2
    assert [q.get(),q.get()]==[9998,9999]


def test_audio_resampling_stereo():
    x=np.sin(np.arange(4800)*2*np.pi*440/48000).astype('float32')
    result=mono16(np.column_stack([x,x]).tobytes(),48000,2)
    assert len(result)==1600
    assert np.isfinite(result).all()
    assert np.sqrt(np.mean(result**2))>.6


def test_export_timestamps_and_real_translation(tmp_path):
    captions=[Caption(1,.25,2.5,'Hello','en','你好')]
    path=tmp_path/'test.srt'
    export(captions,path,'both')
    assert path.read_text(encoding='utf-8-sig')=='1\n00:00:00,250 --> 00:00:02,500\nHello\n你好\n'
    assert stamp(3661.005)=='01:01:01,005'


def test_missing_translation_is_explicit(tmp_path):
    import pytest
    with pytest.raises(RuntimeError,match='缺少本地翻译模型'):
        LocalTranslator(tmp_path).translate('Hello','en','zh')


def test_silence_never_enqueues_recognition():
    engine=Engine('unused','unused')
    engine.launch(engine.segment)
    for i in range(100):
        latest_put(engine.raw,(0,i*.1,np.zeros(4800*2,dtype='float32').tobytes(),48000,2))
        time.sleep(.002)
    time.sleep(.2)
    assert engine.jobs.empty()
    engine.stop()
    for thread in engine.threads: thread.join(2)
    assert engine.jobs.empty()
    assert not engine.alive()


def test_pause_invalidates_pending_jobs():
    engine=Engine('unused','unused')
    engine.jobs.put('old')
    engine.pause(True)
    assert engine.paused.is_set() and engine.jobs.empty() and engine.epoch==1
    engine.pause(False)
    assert not engine.paused.is_set() and engine.epoch==2


def test_missing_model_reports_and_stops(tmp_path):
    engine=Engine(str(tmp_path/'missing'),'unused')
    engine.start()
    for thread in engine.threads: thread.join(20)
    events=[]
    while not engine.events.empty(): events.append(engine.events.get())
    assert any(k=='error' and '模型加载失败' in v for k,v in events)
    assert not engine.alive()


def test_confident_repetition_is_rejected():
    from types import SimpleNamespace
    from captioner.engine import accept_segment
    segment=SimpleNamespace(no_speech_prob=.01,avg_logprob=-.2,
                            compression_ratio=12.0,text='Jell-O, '*70)
    assert not accept_segment(segment)
