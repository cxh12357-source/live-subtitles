"""Scheduling/ordering regressions; these are not speech-accuracy tests."""
import time
import numpy as np
from captioner.streaming import StreamingEngine,StablePrefix,PhraseGate,text_language
from captioner.core import Caption
from captioner.presentation import CurrentCaption


def test_audio_is_ready_for_first_decode_before_one_second():
    e=StreamingEngine('unused','unused'); e.launch(e.segment)
    block=(.1*np.sin(np.arange(1600)*2*np.pi*440/16000)).astype('float32').tobytes()
    try:
        for i in range(9):
            e.raw.put((0,(i+1)*.1,block,16000,1)); time.sleep(.003)
        time.sleep(.1)
        assert not e.jobs.empty(), 'No decode work until the old 2.4-second window fills'
    finally:
        e.stop()
        for t in e.threads:t.join(2)


def test_translation_can_update_a_current_partial():
    state=CurrentCaption();state.reset('s',0)
    c=Caption(1,0,1,'Hello everyone','en',session='s',revision=1)
    state.accept(c,False)
    assert state.translate('s',0,1,1,'大家好')
    assert state.text('translation','zh')=='大家好'


def test_older_translation_for_valid_prefix_survives_new_suffix():
    state=CurrentCaption();state.reset('s',0)
    state.accept(Caption(1,0,1,'we are listening','en',session='s',revision=1),False)
    state.accept(Caption(1,0,2,'we are listening to music','en',session='s',revision=2),False)
    assert state.translate('s',0,1,1,'我们正在听','we are listening',5)
    state.accept(Caption(1,0,3,'we are listening to music now','en',session='s',revision=3),False)
    assert state.text('translation','zh')=='我们正在听'
    assert not state.translate('s',0,1,2,'错误译文','a changed phrase',6)
    state.accept(Caption(2,4,5,'next sentence','en',session='s',revision=4),False)
    assert not state.translate('s',0,1,3,'旧句译文','we are listening',7)


def test_phrase_gate_does_not_translate_every_character():
    gate=PhraseGate(); requests=[]
    for i in range(1,50):
        if gate.ready('a'*i,i*.1):requests.append(i)
    assert 1<=len(requests)<=6
    assert all(b-a>=8 for a,b in zip(requests,requests[1:]))


def test_stable_prefix_retains_complete_words_only():
    stable=StablePrefix()
    stable.update('we are list')
    text,prefix=stable.update('we are listening')
    assert text=='we are listening' and prefix=='we are '
    _,prefix=stable.update('we are listening now')
    assert prefix=='we are '
    assert text_language('这 is a test of real time captions')=='en'
