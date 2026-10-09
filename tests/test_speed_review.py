"""Ordering and bounded-context regressions, not ASR quality measurements."""
from captioner.review import PrefixCorrection, review_times

def test_large_chinese_disagreement_does_not_rewrite_stable_speech():
    from captioner.review import conservative_review
    assert conservative_review('边界条件和热组','边界条件和热阻','zh')
    assert not conservative_review('今天讨论多层平壁的稳态导热','今天他们多层紧力的温开调热','zh')
    assert conservative_review('hello cap','hello captions','en')

def test_correction_preserves_real_repetition_and_native_suffix():
    p=PrefixCorrection('s',0,1,'we we go','we we go')
    assert p.apply('s',0,1,'we we go now')=='we we go now'
    assert p.apply('s',0,2,'we we go now') is None
    assert p.apply('s',1,1,'we we go now') is None
    assert p.apply('s',0,1,'they go now') is None

def test_correction_does_not_guess_a_changed_prefix():
    p=PrefixCorrection('s',0,1,'heat resistant','heat resistance')
    assert p.apply('s',0,1,'heat resistant increases')=='heat resistance increases'
    assert p.apply('s',0,1,'heat resistance increases') is None

def test_manual_speed_is_continuous_budget_hint_not_sample_rate():
    assert review_times(0)==(4.,8.)
    assert review_times(1.73)[0]>0
    assert review_times(3.4)[1]<=8

def test_incomplete_latin_word_is_not_spliced_twice():
    p=PrefixCorrection('s',0,1,'the compu','the computer')
    assert p.apply('s',0,1,'the computer is running') is None

def test_review_ahead_of_stream_cannot_duplicate_future_chinese_or_words():
    chinese=PrefixCorrection('s',0,1,'温差除以热','温差除以热阻')
    assert chinese.apply('s',0,1,'温差除以热阻得到热流') is None
    english=PrefixCorrection('s',0,1,'very','very very')
    assert english.apply('s',0,1,'very very good') is None

def test_final_review_can_recover_omissions_but_cannot_own_later_audio():
    p=PrefixCorrection('s',0,1,'very','very very',complete=True)
    assert p.apply('s',0,1,'very')=='very very'
    assert p.apply('s',0,1,'very good') is None

def test_glossary_is_acoustically_supported_and_cannot_rewrite_other_words():
    from captioner.review import term_scoped_review
    original='多层屏蔽的温度差除以热组'
    decoded='多层平壁的温补差除以热阻'
    assert term_scoped_review(original,decoded,'平壁，热阻')=='多层平壁的温度差除以热阻'
    assert term_scoped_review(original,original,'平壁，热阻')==original
    assert term_scoped_review('热组热组','热阻','热阻').count('热')==2

def test_rate_changes_cannot_create_unbounded_reviews():
    import numpy as np
    from captioner.review import ReviewedEngine
    from captioner.core import Caption
    e=ReviewedEngine('unused','unused');e.review_enabled=True
    for i in range(400):
        end=(i+1)*.04;e.observe_resampled(0,end,np.ones(640,dtype='float32')*.1)
        if i%10==0:
            e.set_speed(1+(i%23)/10)
            e.emit('partial',Caption(1,0,end,'测试重复重复','zh',session=e.session,revision=i+1))
    assert e.review_count<=2
    assert e.review_queue.qsize()<=1
    assert sum(len(x[2]) for x in e.audio_ring)<=int(13.1*16000)

def test_audio_gap_refuses_review_instead_of_stitching_missing_words():
    import numpy as np
    from captioner.review import ReviewedEngine
    from captioner.core import Caption
    e=ReviewedEngine('unused','unused')
    e.observe_resampled(0,.04,np.ones(640,dtype='float32'))
    e.observe_resampled(0,1.04,np.ones(640,dtype='float32'))
    assert e.window(Caption(1,0,1.04,'测试','zh',session=e.session)) is None
