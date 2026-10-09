import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from queue import Queue
from types import SimpleNamespace
from threading import Event
import pytest
from PySide6 import QtWidgets as W
from captioner import ui
from captioner.core import Caption


@pytest.fixture
def window(monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    monkeypatch.setattr(ui, 'load_config', lambda: {})
    monkeypatch.setattr(ui, 'save_config', lambda _: None)
    monkeypatch.setattr(ui, 'devices', lambda: [])
    monkeypatch.setattr(ui, 'default_device', lambda: '')
    monkeypatch.setattr(ui.Hotkeys, '__init__', lambda self, w: (super(ui.Hotkeys, self).__init__(), setattr(self, 'ids', []))[-1])
    w = ui.MainWindow()
    w.timer.stop()
    w.engine = SimpleNamespace(events=Queue(), alive=lambda: True, epoch=0,
                               session='test', paused=Event(), stop_event=Event())
    yield w
    w.engine = None
    w.tray.hide(); w.overlay.hide(); w.hide()
    app.removeNativeEventFilter(w.hotkeys)
    w.deleteLater(); app.processEvents()


def deliver(w, kind, ident, text):
    c = Caption(ident, ident * 2, ident * 2 + 1, text, 'zh')
    c.session = 'test'; c.epoch = 0
    w.engine.events.put((kind, c)); w.poll()


def test_late_review_final_updates_history_without_reviving_old_block(window):
    deliver(window,'partial',2,'当前新句')
    deliver(window,'final',1,'旧句已完成复核')
    assert window.overlay.content=='当前新句'
    assert len(window.history)==1 and window.history[0].id==1


def test_revised_final_replaces_history_entry(window):
    deliver(window,'final',1,'第一次确认')
    c=Caption(1,2,3,'声学复核后的确认','zh',session='test',epoch=0,revision=2)
    window.engine.events.put(('final',c));window.poll()
    assert len(window.history)==1
    assert window.history[0].text=='声学复核后的确认'
    assert window.overlay.content=='声学复核后的确认'


def test_partial_is_simplified(window):
    deliver(window, 'partial', 1, '導熱邊界條件與熱阻 ABC 123')
    visible = '\n'.join(x.text() for x in window.overlay.findChildren(W.QLabel))
    assert '导热边界条件与热阻 ABC 123' in visible
    assert '導' not in visible


def test_new_sentence_replaces_previous(window):
    deliver(window, 'final', 1, '第一句。')
    deliver(window, 'final', 2, '第二句。')
    assert window.overlay.label.text() == '第二句。'


def test_partial_does_not_stack_with_final(window):
    deliver(window, 'final', 1, '旧句子。')
    deliver(window, 'partial', 2, '新的临时句子。')
    visible = '\n'.join(x.text() for x in window.overlay.findChildren(W.QLabel))
    assert '旧句子' not in visible
    assert visible.count('新的临时句子') == 1


def test_out_of_order_and_late_translation_do_not_resurrect(window):
    deliver(window,'final',2,'新句子。')
    deliver(window,'final',1,'旧句子。')
    window.engine.events.put(('translated',('test',0,1,0,'错序译文')))
    window.poll()
    assert window.overlay.label.text()=='新句子。'
    window.overlay.advance(window.overlay.activity_at+3.1)
    window.current.expired=True
    window.engine.events.put(('translated',('test',0,2,0,'过期译文')))
    window.poll()
    assert window.overlay.label.text()==''
    deliver(window,'partial',3,'恢复播放。')
    assert window.overlay.label.text()=='恢复播放。'


def test_final_replaces_partial_and_rejects_old_revision(window):
    deliver(window,'partial',1,'臨時字幕')
    deliver(window,'final',1,'確認字幕')
    deliver(window,'partial',1,'臨時字幕')
    assert window.overlay.label.text()=='确认字幕'
    assert len(window.overlay.findChildren(W.QLabel))==1


def test_pause_epoch_and_other_session_are_rejected(window):
    deliver(window,'partial',1,'暂停前')
    window.engine.epoch=1
    deliver(window,'final',3,'过期的确认结果')
    assert not window.overlay.label.text()
    c=Caption(4,8,9,'其他会话','zh',session='old',epoch=1)
    window.engine.events.put(('final',c)); window.poll()
    assert not window.overlay.label.text()


def test_long_caption_pages_preserve_tail_and_two_lines(window):
    text='先确定边界条件，再分别计算每一层材料的热阻。'*12+'最后一句不可丢失。'
    deliver(window,'final',1,text)
    overlay=window.overlay
    assert len(overlay.pages)>1
    assert ''.join(overlay.pages).replace('\n','')==text
    height=overlay.height()
    seen=[overlay.label.text()]
    now=overlay.activity_at
    while overlay.page_index+1<len(overlay.pages):
        now+=3.1; overlay.advance(now); seen.append(overlay.label.text())
        assert overlay.label.text().count('\n')<=1
        assert overlay.height()==height
    assert '最后一句不可丢失。' in seen[-1]
    assert overlay.advance(now+3.1)
    assert not overlay.label.text()


def test_english_formula_and_repeated_speech_preserved(window):
    deliver(window,'final',1,'是的，是的。Q = ΔT / R, 123 ABC')
    assert window.overlay.content=='是的，是的。Q = ΔT / R, 123 ABC'


def test_overlap_only_removes_words_from_owned_audio():
    from captioner.engine import owned_text
    words=[SimpleNamespace(word='是的',start=t,end=t+.3) for t in (.1,1.1,1.6)]
    s=SimpleNamespace(words=words,no_speech_prob=0,avg_logprob=0,compression_ratio=1)
    assert owned_text([s],10,11)=='是的是的'


def test_pending_partials_coalesce_without_evicting_final():
    from captioner.engine import RecognitionQueue,RecognitionJob
    q=RecognitionQueue(2)
    def job(i,rev,final=False): return RecognitionJob(0,i,0,rev,None,final,-1,rev)
    q.submit(job(1,1,True))
    for rev in range(1,100): q.submit(job(2,rev))
    assert q.qsize()==2
    assert q.get().final
    assert q.get().revision==99


def test_antiphase_pcm_keeps_speech_and_duration():
    import numpy as np
    from captioner.audio import mono16
    x=np.sin(np.arange(44100)*2*np.pi*440/44100).astype('float32')
    y=mono16(np.column_stack([x,-x]).tobytes(),44100,2)
    assert len(y)==16000
    assert np.sqrt(np.mean(y*y))>.6


def test_japanese_is_not_converted_to_chinese():
    from captioner.presentation import CurrentCaption
    state=CurrentCaption(); state.reset('s',0)
    state.accept(Caption(1,0,1,'図書館の國語教室','ja',session='s'),True)
    assert state.text('original','zh')=='図書館の國語教室'


def test_bilingual_export_preserves_japanese_and_normalizes_chinese(tmp_path):
    from captioner.core import export
    path=tmp_path/'captions.txt'
    export([Caption(1,0,1,'図書館の國語教室','ja','图书馆的国语教室')],path,'both')
    assert '図書館の國語教室' in path.read_text(encoding='utf-8-sig')
    export([Caption(1,0,1,'熱阻','zh','熱阻')],path,'both')
    text=path.read_text(encoding='utf-8-sig')
    assert text.count('热阻')==1 and '熱' not in text


def test_same_chinese_source_target_never_duplicates(window):
    window.mode.setCurrentIndex(window.mode.findData('both'))
    deliver(window,'partial',1,'熱阻與邊界條件')
    assert window.overlay.label.text()=='热阻与边界条件'
    deliver(window,'final',1,'熱阻與邊界條件')
    assert window.overlay.label.text()=='热阻与边界条件'


def test_final_same_audio_cannot_resurrect_after_timeout(window):
    deliver(window,'partial',1,'旧的临时句')
    assert window.overlay.advance(window.overlay.activity_at+3.1)
    window.current.expired=True
    deliver(window,'final',1,'过期确认句')
    assert not window.overlay.label.text()


def test_new_audio_same_utterance_can_resume_after_display_timeout(window):
    deliver(window,'partial',1,'前半句')
    window.overlay.advance(window.overlay.activity_at+3.1); window.current.expired=True
    c=Caption(1,2,6,'前半句和后半句','zh',session='test',revision=2)
    window.engine.events.put(('partial',c)); window.poll()
    assert window.overlay.label.text()=='前半句和后半句'


def test_bilingual_translation_is_visible_immediately_for_long_source(window):
    window.mode.setCurrentIndex(window.mode.findData('both'))
    text='We are listening to a long explanation about boundary conditions and thermal resistance in multiple layers.'
    c=Caption(1,0,2,text,'en',session='test',revision=1)
    window.engine.events.put(('partial',c));window.poll()
    window.engine.events.put(('translated',('test',0,1,1,'正在讲解多层材料的边界条件和热阻。',text,0)))
    window.poll()
    assert '正在讲解' in window.overlay.label.text()
    assert window.overlay.label.text().count('\n')==1
