"""Bounded incremental ASR with sentence context and audio-time ownership."""
from collections import deque
from dataclasses import dataclass
from queue import Queue, Empty
from threading import Thread, Event
from uuid import uuid4
import time
import numpy as np
from .audio import capture, mono16, mono
from .core import Caption, latest_put, drain
from .translation import LocalTranslator


def accept_segment(s):
    return s.no_speech_prob < .55 and s.avg_logprob > -1.0 and s.compression_ratio < 2.4


@dataclass
class RecognitionJob:
    epoch: int
    id: int
    start: float
    end: float
    audio: np.ndarray
    final: bool
    committed_until: float
    revision: int
    commit_through: float = float('inf')
    queued_at: float = 0
    last_voice_end: float = 0


class RecognitionQueue(Queue):
    """Coalesce pending partials; preserve finals preferentially under load."""
    def submit(self, job):
        with self.not_empty:
            self.queue = deque(x for x in self.queue
                               if not (x.epoch == job.epoch and x.id == job.id and not x.final))
            dropped = False
            if len(self.queue) >= self.maxsize:
                partial = next((x for x in self.queue if not x.final), None)
                if partial is not None: self.queue.remove(partial)
                elif not job.final: return True
                else: self.queue.popleft()
                dropped = True
            self.queue.append(job)
            self.not_empty.notify()
            return dropped


def owned_text(segments, window_start, committed_until, commit_through=float('inf')):
    """Deduplicate by audio ownership, never by repeated text."""
    parts = []
    for s in segments:
        if not accept_segment(s): continue
        if getattr(s, 'words', None):
            parts.extend(w.word for w in s.words
                         if committed_until+.015 < window_start+(w.start+w.end)/2 <= commit_through)
        elif window_start+s.start >= committed_until and window_start+s.end <= commit_through:
            parts.append(s.text)
    return ''.join(parts).strip()


class Engine:
    def __init__(self, model, device, language=None, target='zh', translate=False, backend='cpu', hotwords=''):
        self.model_path, self.device, self.language = model, device, language
        self.target, self.translate, self.backend = target, translate, backend
        self.hotwords = hotwords.strip() or None
        self.raw, self.jobs, self.translations, self.events = Queue(20), RecognitionQueue(4), Queue(4), Queue(128)
        self.stop_event, self.paused = Event(), Event()
        self.session = uuid4().hex
        self.epoch = 0
        self.origin = time.monotonic()
        self.dropped = 0
        self.threads = []
        self.audio_observer = None  # Explicit diagnostic script only.
        self.trace_sink = None
        self.translation_ready = False

    def trace(self, stage, **values):
        if self.trace_sink is not None:
            self.trace_sink(dict(stage=stage,at=time.monotonic(),session=self.session,epoch=self.epoch,**values))

    def emit(self, kind, value): latest_put(self.events, (kind, value))

    def start(self):
        self.origin = time.monotonic()
        self.launch(self.recognize); self.launch(self.translate_loop)

    def launch(self, function):
        thread = Thread(target=function, daemon=False)
        self.threads.append(thread); thread.start()

    def pause(self, paused):
        self.paused.set() if paused else self.paused.clear()
        self.epoch += 1
        for q in (self.raw, self.jobs, self.translations, self.events): drain(q)
        self.emit('clear_partial', None)
        self.emit('capture', '已暂停（音频丢弃）' if paused else '回环捕获中')

    def stop(self):
        self.stop_event.set(); self.epoch += 1
        for q in (self.raw, self.jobs, self.translations, self.events): drain(q)

    def alive(self): return any(t.is_alive() for t in self.threads)

    def segment(self):
        chunks, pre_roll = [], deque(maxlen=3)
        start = last_end = silent = length = meter_at = 0
        next_partial = 2.4
        last_voice_end = 0
        epoch, uid, revision, committed_until = self.epoch, 0, 0, -1
        while not self.stop_event.is_set():
            try: item = self.raw.get(timeout=.1)
            except Empty: continue
            item_epoch, end, data, rate, channels = item[:5]
            overflow = item[5] if len(item)>5 else False
            if item_epoch != self.epoch or self.paused.is_set(): continue
            duration = len(data)/(4*channels*rate)
            arrived = item[6].get('captured_at',time.monotonic()) if len(item)>6 else time.monotonic()
            self.trace('audio',audio_end=end,block_ms=duration*1000,queue_ms=(time.monotonic()-arrived)*1000)
            gap = last_end and abs(end-last_end-duration)>.025
            if epoch != item_epoch or gap or overflow:
                if gap or overflow:
                    self.emit('recognition', '检测到音频缺口，已重置句子上下文；请检查输出设备或处理负载。')
                chunks, pre_roll = [], deque(maxlen=3)
                silent = length = 0; next_partial = 2.4
                uid += 1; epoch = item_epoch; committed_until = -1
            last_end = end
            if self.audio_observer is not None: self.audio_observer(data, rate, channels)
            x = mono(data, channels)
            rms = float(np.sqrt(np.mean(x*x)))
            if end-meter_at >= .5:
                self.emit('level', f'输入电平 {20*np.log10(max(rms,1e-6)):.0f} dBFS')
                meter_at = end
            voiced = rms > .003
            if voiced: last_voice_end=end
            if not chunks:
                if not voiced:
                    pre_roll.append(data); continue
                chunks = list(pre_roll); pre_roll.clear()
                length = sum(len(c) for c in chunks)/(4*channels*rate)
                start = max(0,end-duration-length)
            chunks.append(data); length += duration
            silent = 0 if voiced else silent+duration
            hard_boundary = length >= 12
            final = silent >= .8 or hard_boundary
            if final or length >= next_partial:
                # One resampling pass over a contiguous window preserves filter context.
                audio = mono16(b''.join(chunks),rate,channels)
                revision += 1
                through = end-.5 if hard_boundary else end
                job = RecognitionJob(epoch,uid,start,end,audio,final,committed_until,revision,through)
                job.queued_at=time.monotonic(); job.last_voice_end=last_voice_end
                self.trace('scheduled',id=uid,revision=revision,final=final,audio_end=end,
                           context_ms=length*1000,endpoint_wait_ms=(end-last_voice_end)*1000)
                if self.jobs.submit(job):
                    self.dropped += 1
                    self.emit('recognition','识别负载过高，已跳过旧任务以限制延迟。')
                next_partial = length+2.4
            if final:
                uid += 1; silent = 0; next_partial = 2.4
                committed_until = through
                if hard_boundary:
                    tail = b''.join(chunks)[-rate*channels*4:]
                    chunks = [tail]; length = len(tail)/(rate*channels*4); start = end-length
                else:
                    chunks = []; length = 0

    def recognize(self):
        try:
            from faster_whisper import WhisperModel
            self.emit('model','正在加载本地识别模型…')
            model = WhisperModel(self.model_path,device=self.backend,
                compute_type='int8' if self.backend=='cpu' else 'float16',
                cpu_threads=6,local_files_only=True)
            self.emit('model','正在预热 Whisper（兼容模式，非原生流式）…')
            list(model.transcribe(np.zeros(16000,dtype='float32'),language=self.language or 'en',
                                 beam_size=1,vad_filter=False,max_new_tokens=1)[0])
            if self.translate:
                while not self.translation_ready and not self.stop_event.wait(.05):pass
            self.emit('model','Whisper 已加载并预热 · 兼容模式')
            if self.stop_event.is_set(): return
            self.origin = time.monotonic()
            self.launch(lambda:capture(self)); self.launch(self.segment)
            while not self.stop_event.is_set():
                try: job = self.jobs.get(timeout=.1)
                except Empty: continue
                if job.epoch != self.epoch or self.paused.is_set(): continue
                if time.monotonic()-self.origin-job.end > 5:
                    self.dropped += 1
                    self.emit('recognition','已丢弃超过 5 秒的待识别音频；请降低模型负载。')
                    continue
                began = time.monotonic()
                try:
                    segments,info = model.transcribe(job.audio,language=self.language,beam_size=5,
                        vad_filter=True,vad_parameters={'min_silence_duration_ms':500,
                        'min_speech_duration_ms':250,'speech_pad_ms':300},
                        condition_on_previous_text=False,word_timestamps=True,
                        temperature=0,no_speech_threshold=.55,compression_ratio_threshold=2.4,
                        max_new_tokens=256,hotwords=self.hotwords)
                    text = owned_text(list(segments),job.start,job.committed_until,job.commit_through)
                    produced=time.monotonic()
                    self.trace('asr',id=job.id,revision=job.revision,final=job.final,audio_end=job.end,
                               queue_ms=(began-job.queued_at)*1000,inference_ms=(produced-began)*1000,
                               endpoint_wait_ms=(job.end-job.last_voice_end)*1000,text=text)
                    if job.epoch != self.epoch or self.stop_event.is_set() or self.paused.is_set(): continue
                    self.emit('recognition',f'{info.language} · 推理 {time.monotonic()-began:.2f}s · 丢弃 {self.dropped} 段')
                    if text:
                        c = Caption(job.id,max(job.start,job.committed_until),job.end,text,info.language,
                            latency=time.monotonic()-self.origin-job.start,session=self.session,
                            epoch=job.epoch,revision=job.revision)
                        c.timing={'produced_at':produced,'audio_end':job.end,'last_voice_end':job.last_voice_end}
                        if c.language == self.target: c.translation = c.text
                        self.emit('final' if job.final else 'partial',c)
                        if job.final and self.translate and c.language != self.target:
                            if latest_put(self.translations,(job.epoch,c)):
                                self.emit('translation_error','翻译处理较慢，已跳过最旧译文。')
                    elif job.final:
                        self.emit('empty_final',(self.session,job.epoch,job.id))
                except Exception as e:
                    if job.epoch == self.epoch and not self.stop_event.is_set():
                        self.emit('error',f'识别失败：{type(e).__name__}: {e}')
        except Exception as e:
            self.emit('error',f'模型加载失败：{e}。请先下载完整模型；CUDA 失败时选择 CPU。')
            self.stop_event.set()

    def translate_loop(self):
        translator = LocalTranslator()
        try:
            if self.translate and self.language!=self.target:
                source=self.language or 'en'
                translator.translate('你好' if source=='zh' else 'Hello everyone',source,self.target)
        except Exception as e:self.emit('translation_error',str(e))
        finally:self.translation_ready=True
        while not self.stop_event.is_set():
            try: epoch,caption = self.translations.get(timeout=.1)
            except Empty: continue
            if epoch != self.epoch or self.paused.is_set(): continue
            try:
                began=time.monotonic()
                text = translator.translate(caption.text,caption.language,self.target)
                self.trace('translation',id=caption.id,revision=caption.revision,inference_ms=(time.monotonic()-began)*1000,
                           queue_ms=(began-caption.timing.get('produced_at',began))*1000,text=text)
                if epoch == self.epoch and not self.stop_event.is_set() and not self.paused.is_set():
                    self.emit('translated',(self.session,epoch,caption.id,caption.revision,text))
            except Exception as e:
                if epoch == self.epoch and not self.stop_event.is_set() and not self.paused.is_set():
                    self.emit('translation_error',str(e))
