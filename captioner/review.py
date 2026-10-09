"""Bounded acoustic review beside, never in front of, native streaming ASR."""
from collections import deque
from dataclasses import dataclass,replace
from pathlib import Path
from queue import Queue,Empty
from threading import RLock
import time,re
from difflib import SequenceMatcher
import numpy as np
from .streaming import StreamingEngine,text_language
from .core import DATA,latest_put
from .presentation import display_text


def term_scoped_review(original,decoded,glossary):
    """Only equal-length edits inside a term actually decoded from this audio.

    This is not a replacement dictionary: a requested term absent from the
    acoustic hypothesis changes nothing. Preserve all other native text,
    insertions/deletions and true repetitions rather than guessing ownership.
    """
    original,decoded=display_text(original),display_text(decoded)
    terms=[t.strip() for t in re.split(r'[,，;；\n]+',display_text(glossary)) if t.strip()]
    if len(terms)==1 and re.search(r'[\u3400-\u9fff]',terms[0]):terms=terms[0].split()
    spans=[m.span() for term in terms for m in re.finditer(re.escape(term),decoded)]
    chars=list(original)
    for tag,a,b,c,d in SequenceMatcher(None,original,decoded,autojunk=False).get_opcodes():
        if tag=='replace' and b-a==d-c and any(start<=c and d<=end for start,end in spans):
            chars[a:b]=decoded[c:d]
    return ''.join(chars)


def conservative_review(original,candidate,language):
    """Disagreement budget, NOT an estimate of correctness or speech speed.

    Automatic Chinese review is conservative: avoid rewriting many already
    visible characters when the two acoustic models disagree. Glossary-driven
    Whisper review is a separate explicit user option.
    """
    if language!='zh':return True
    clean=lambda t:re.sub(r'[^\w]','',display_text(t).lower())
    a,b=clean(original),clean(candidate)
    if max(len(a),len(b))>400:return False
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1):new.append(min(new[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]<=max(2,int(len(a)*.10))


def review_times(speed):
    # Explicit user hint controls how much speech is accumulated for review.
    # Zero means unknown; no attempt to infer a player's rate from speech.
    scale=max(1.,float(speed or 1))
    return max(2.,4./scale),max(4.,8./scale)


@dataclass
class PrefixCorrection:
    session:str
    epoch:int
    id:int
    original:str
    corrected:str
    complete:bool=False

    def apply(self,session,epoch,ident,text):
        if (session,epoch,ident)!=(self.session,self.epoch,self.id) or not text.startswith(self.original):return None
        if self.complete:
            # The endpoint owns exactly this audio interval, not a later suffix.
            return self.corrected if text==self.original else None
        units=lambda t:re.findall(r'[\u3400-\u9fff]|[A-Za-z0-9]+(?:[\u2019\x27][A-Za-z0-9]+)*',t)
        if len(units(self.original))!=len(units(self.corrected)):
            # The offline pass can hear ahead of the streaming decoder. Without
            # reliable matching word timestamps we cannot assign extra/deleted
            # units to its prefix. Keep the native text; an endpoint can recover
            # omissions later. Never trim a repeated word to guess the join.
            return None
        suffix=text[len(self.original):]
        # A still-growing Latin token has no safe merge boundary. Do not guess.
        if suffix and self.original and self.original[-1].isascii() and self.original[-1].isalpha() and suffix[0].isascii() and suffix[0].isalpha():return None
        return self.corrected+suffix


class ReviewedEngine(StreamingEngine):
    """Two prefix reviews (4/8s) + endpoint <=12s, one active/one pending job.

    Audio remains on its real capture clock. No resampling-rate trick, no
    full-session replay, no text-only language-model rewriting.
    """
    def __init__(self,*args,speed_hint=0.,**kwargs):
        super().__init__(*args,**kwargs)
        self.speed_hint=float(speed_hint);self.review_ready=False
        self.review_enabled=False;self.review_queue=Queue(1);self.guard=RLock()
        self.audio_ring=deque();self.latest_native=None;self.latest_final=False
        self.patch=None;self.reviewed=set();self.review_identity=None
        self.review_count=0

    def start(self):
        self.launch(self.review_loop)
        super().start()

    def set_speed(self,value):
        self.speed_hint=max(0.,min(4.,float(value)))
        self.emit('recognition','倍速提示已更新；采样率和捕获时间轴保持不变')

    def observe_resampled(self,epoch,end,samples):
        with self.guard:
            if self.audio_ring and (self.audio_ring[-1][0]!=epoch or abs(end-self.audio_ring[-1][1]-len(samples)/16000)>.08):
                self.audio_ring.clear()
            self.audio_ring.append((epoch,end,samples.copy()))
            while self.audio_ring and end-self.audio_ring[0][1]>13:self.audio_ring.popleft()

    def window(self,c):
        start=max(0,c.start-.20)
        if c.end-start>12.4:return None
        pieces=[];expected=None
        for epoch,end,samples in self.audio_ring:
            if epoch!=c.epoch:continue
            begin=end-len(samples)/16000
            a=max(start,begin);b=min(c.end,end)
            if b<=a:continue
            if expected is not None and a-expected>.06:return None
            pieces.append(samples[round((a-begin)*16000):round((b-begin)*16000)])
            expected=b
        if not pieces or expected<c.end-.08:return None
        audio=np.concatenate(pieces)
        if len(audio)<(c.end-start-.10)*16000:return None
        return audio

    def published(self,c,final,patch=True):
        text=c.text
        if patch and self.patch:
            text=self.patch.apply(c.session,c.epoch,c.id,text) or text
        out=replace(c,text=text,revision=c.revision*10+(2 if final else 0),timing=dict(c.timing))
        if text!=c.text:
            out.language=self.language or text_language(text)
            out.translation=text if out.language==self.target else ''
            out.timing['reviewed']=True
        self.trace('resolved',id=c.id,revision=out.revision,final=final,audio_end=c.end,text=out.text)
        super().emit('final' if final else 'partial',out)

    def emit(self,kind,value):
        if kind not in ('partial','final'):return super().emit(kind,value)
        c=value
        with self.guard:
            identity=(c.session,c.epoch,c.id)
            if identity!=self.review_identity:
                self.review_identity=identity;self.reviewed=set();self.patch=None;self.review_count=0
            self.latest_native=c;self.latest_final=kind=='final'
            duration=c.end-c.start
            milestones=review_times(self.speed_hint)
            marker='final' if kind=='final' else next((t for t in reversed(milestones) if duration>=t and t not in self.reviewed),None)
            if kind!='final' and self.review_count>=2:marker=None
            audio=self.window(c) if self.review_enabled and marker is not None else None
            pending=audio is not None
            if marker is not None:
                self.reviewed.add(marker)
                if marker!='final':self.reviewed.update(t for t in milestones if t<=marker)
            self.published(c,kind=='final' and not pending)
            if pending:
                if kind!='final':self.review_count+=1
                dropped=False
                if self.review_queue.full():
                    try:
                        old=self.review_queue.get_nowait();dropped=True
                        if old[2]:self.published(old[0],True,patch=False)
                    except Empty:pass
                latest_put(self.review_queue,(c,audio,kind=='final',time.monotonic(),self.speed_hint))
                if dropped:super().emit('recognition','声学复核负载较高：已合并待复核任务；流式字幕继续更新')
            elif kind=='final' and self.review_enabled and duration>12:
                super().emit('recognition','长句保留流式结果：复核限制为当前前 12 秒，不追溯整段音频')

    def review_loop(self):
        reviewer=None;term_model=None
        try:
            import sherpa_onnx
            p=DATA/'models/sensevoice'
            reviewer=sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(p/'model.int8.onnx'),tokens=str(p/'tokens.txt'),
                                                                  num_threads=2,language=self.language or 'auto',use_itn=False)
            warm=reviewer.create_stream();warm.accept_waveform(16000,np.zeros(16000,dtype='float32'));reviewer.decode_stream(warm)
            if self.hotwords:
                try:
                    from faster_whisper import WhisperModel
                    term_model=WhisperModel(str(DATA/'models/small'),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
                    list(term_model.transcribe(np.zeros(16000,dtype='float32'),language=self.language or 'zh',max_new_tokens=1)[0])
                except Exception as e:
                    term_model=None
                    super().emit('error',f'课程术语复核不可用：{e}。请下载 small；当前继续普通声学复核。')
            self.review_enabled=True
        except Exception as e:
            super().emit('error',f'增强复核不可用：{e}。保留流式字幕；请下载增强复核模型。')
        finally:self.review_ready=True
        while not self.stop_event.is_set():
            try:c,audio,final,queued,speed=self.review_queue.get(timeout=.1)
            except Empty:continue
            if c.epoch!=self.epoch or self.paused.is_set():continue
            began=time.monotonic();text='';error=None;terms_used=False
            try:
                if began-queued>1.2:raise RuntimeError('复核排队超过 1.2 秒，跳过过期复核')
                if term_model is not None and (final or len(audio)>=7*16000):
                    terms_used=True
                    segments,_=term_model.transcribe(audio,language=self.language,hotwords=self.hotwords,beam_size=3,
                                                     vad_filter=False,condition_on_previous_text=False,temperature=0,max_new_tokens=256)
                    text=''.join(s.text for s in segments if s.no_speech_prob<.55 and s.avg_logprob>-1.0)
                    text=term_scoped_review(c.text,text,self.hotwords)
                else:
                    s=reviewer.create_stream();s.accept_waveform(16000,audio);reviewer.decode_stream(s);text=s.result.text
                text=re.sub(r'<\|[^|]*\|>','',text).strip()
                if time.monotonic()-queued>2.:raise RuntimeError('复核超过 2 秒时限，保留实时结果；可关闭增强复核')
            except Exception as e:error=str(e);text=''
            produced=time.monotonic()
            if c.epoch!=self.epoch or self.paused.is_set() or self.stop_event.is_set():continue
            with self.guard:
                latest=self.latest_native
                same=latest is not None and (latest.session,latest.epoch,latest.id)==(c.session,c.epoch,c.id)
                candidate=PrefixCorrection(c.session,c.epoch,c.id,c.text,text,complete=final)
                agreement=terms_used or conservative_review(c.text,text,self.language or text_language(text))
                corrected=candidate.apply(latest.session,latest.epoch,latest.id,latest.text) if same and text and agreement else None
                accepted=bool(corrected)
                self.trace('review',id=c.id,revision=c.revision,audio_end=c.end,final=final,accepted=accepted,
                           text=text,original=c.text,inference_ms=(produced-began)*1000,queue_ms=(began-queued)*1000,
                           audio_seconds=len(audio)/16000,speed_hint=speed,error=error,agreement=agreement,terms_used=terms_used,
                           prefix_policy='equal_units_or_endpoint')
                super().emit('review_status',f'声学复核 {(produced-began)*1000:.0f} ms · '+('已采用' if accepted else '覆盖范围/前缀不一致、差异较大或复核失败，保留实时稿'))
                if error:super().emit('error',error)
                if accepted:
                    self.patch=candidate
                    is_final=final and self.latest_final
                    out=replace(latest,text=corrected,translation=corrected if latest.language==self.target else '',
                                revision=latest.revision*10+(2 if is_final else 1),timing=dict(latest.timing))
                    out.language=self.language or text_language(corrected)
                    out.translation=corrected if out.language==self.target else ''
                    out.timing.update(produced_at=produced,reviewed=True)
                    self.trace('resolved',id=out.id,revision=out.revision,final=is_final,audio_end=out.end,text=out.text)
                    super().emit('final' if is_final else 'partial',out)
                    if self.translate and out.language!=self.target:
                        self.latest_translation_key=(out.epoch,out.id,out.revision)
                        latest_put(self.translations,(out.epoch,out))
                elif final:
                    # Still record an old completed utterance; the UI rejects old IDs for display.
                    self.published(c,True,patch=same)

    def pause(self,paused):
        super().pause(paused)
        with self.guard:
            self.audio_ring.clear();self.patch=None
            from .core import drain
            drain(self.review_queue)

    def stop(self):
        super().stop()
        with self.guard:
            self.audio_ring.clear();self.patch=None
            from .core import drain
            drain(self.review_queue)
