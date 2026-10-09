"""Stateful local streaming ASR. Each PCM sample enters the model exactly once."""
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
import re
import time
import numpy as np
import soxr
from .audio import capture, mono
from .core import Caption, latest_put, drain
from .engine import Engine
from .translation import LocalTranslator


class StablePrefix:
    """Freeze agreed complete words; leave the newest suffix revisable."""
    def __init__(self): self.previous=''; self.stable=''

    def update(self, text, final=False):
        if final:
            self.previous=text; self.stable=text
            return text,text
        n=0
        for a,b in zip(self.previous,text):
            if a!=b:break
            n+=1
        prefix=text[:n]
        # Do not stabilize a partial Latin word such as 'compu'.
        prefix=re.sub(r'[A-Za-z]+$','',prefix)
        if prefix.startswith(self.stable):self.stable=prefix
        elif not text.startswith(self.stable):
            # Retain only actual acoustic agreement; don't invent a text splice.
            self.stable=prefix
        self.previous=text
        return text,self.stable


@dataclass
class AudioChunk:
    epoch: int
    end: float
    samples: np.ndarray
    queued_at: float
    captured_at: float
    reset: bool = False


class PhraseGate:
    """Coalesce stable phrases: never send a translation for every character."""
    def __init__(self): self.text='';self.at=-100.

    def ready(self, stable, now, final=False):
        stable=stable.strip()
        if not stable or stable==self.text:return False
        delta=len(stable)-len(self.text)
        enough=(delta>=8 or len(stable.split())-len(self.text.split())>=3)
        boundary=bool(re.search(r'[.!?。！？；;]$',stable))
        if not final and (now-self.at<.8 or not (enough or boundary)):
            return False
        self.text,self.at=stable,now
        return True


def text_language(text):
    """Translation routing for a bilingual decoder, not an ASR language detector."""
    han=len(re.findall(r'[\u3400-\u9fff]',text))
    latin=len(re.findall(r'[A-Za-z]',text))
    return 'zh' if han and not (han<3 and latin>han*4) else 'en'


class StreamingEngine(Engine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.raw=Queue(25); self.jobs=Queue(25); self.translations=Queue(2)
        self.block_seconds=.04
        self.latest_translation_key=None
        self.live_id=-1
        self.translation_ready=False

    def overload(self, reason):
        self.dropped+=1
        self.emit('error',reason+'。已重置流状态，避免旧字幕追赶；请关闭其它推理任务或使用 CPU 实时中英配置。')

    def segment(self):
        resampler=None;fmt=None;epoch=-1;last_end=None;reset=False;meter_at=0
        while not self.stop_event.is_set():
            try:item=self.raw.get(timeout=.1)
            except Empty:continue
            item_epoch,end,data,rate,channels=item[:5]
            if item_epoch!=self.epoch or self.paused.is_set():continue
            now=time.monotonic()
            captured=item[6].get('captured_at',now) if len(item)>6 else now
            duration=len(data)/(4*rate*channels)
            gap=last_end is not None and abs(end-last_end-duration)>.025
            if item_epoch!=epoch or fmt!=(rate,channels) or gap or (len(item)>5 and item[5]):
                resampler=soxr.ResampleStream(rate,16000,1,dtype='float32',quality='LQ') if rate!=16000 else None
                reset=True;fmt=(rate,channels);epoch=item_epoch
                if gap or (len(item)>5 and item[5]):self.overload('检测到采集音频缺口')
            last_end=end
            if self.audio_observer is not None:self.audio_observer(data,rate,channels)
            began=time.monotonic();x=mono(data,channels)
            rms=float(np.sqrt(np.mean(x*x)))
            if end-meter_at>=.5:
                self.emit('level',f'输入电平 {20*np.log10(max(rms,1e-6)):.0f} dBFS');meter_at=end
            y=resampler.resample_chunk(x) if resampler else x
            self.trace('audio',audio_end=end,block_ms=duration*1000,queue_ms=(began-captured)*1000,
                       preprocess_ms=(time.monotonic()-began)*1000,
                       resampler_delay_ms=resampler.delay()/16 if resampler else 0)
            if len(y):
                if hasattr(self,'observe_resampled'):self.observe_resampled(epoch,end,y)
                chunk=AudioChunk(epoch,end,y,time.monotonic(),captured,reset)
                if self.jobs.full():
                    drain(self.jobs);chunk.reset=True;self.overload('识别队列超过约 1 秒')
                latest_put(self.jobs,chunk);reset=False

    def recognize(self):
        try:
            import sherpa_onnx
            folder=Path(self.model_path)
            self.emit('model','正在加载并预热中英流式模型（CPU INT8）…')
            began=time.monotonic()
            recognizer=sherpa_onnx.OnlineRecognizer.from_paraformer(
                tokens=str(folder/'tokens.txt'),encoder=str(folder/'encoder.int8.onnx'),
                decoder=str(folder/'decoder.int8.onnx'),num_threads=2,provider='cpu')
            warm=recognizer.create_stream();warm.accept_waveform(16000,np.zeros(16000,dtype='float32'))
            warm.set_option('is_final','1');warm.input_finished()
            while recognizer.is_ready(warm):recognizer.decode_stream(warm)
            del warm
            self.trace('warmup',ms=(time.monotonic()-began)*1000)
            if self.translate:
                self.emit('model','识别已预热；正在预热本地翻译…')
                while not self.translation_ready and not self.stop_event.wait(.05):pass
            if self.stop_event.is_set():return
            self.emit('model','中英流式模型已就绪 · CPU INT8 · 已预热')
            if self.language not in (None,'zh','en'):
                raise RuntimeError('实时模型仅支持中文和英文；其他源语言请选择 Whisper 兼容模型')
            if self.hotwords and not hasattr(self,'review_ready'):self.emit('recognition','实时模型不使用术语提示；此输入仅用于 Whisper 兼容模型')
            if hasattr(self,'review_ready'):
                if not self.review_ready:self.emit('model','流式模型已预热；等待增强声学复核预热…')
                while not self.review_ready and not self.stop_event.wait(.05):pass
                self.emit('model','流式与增强复核预热已结束；正在打开回环设备')
            if self.stop_event.is_set():return
            self.origin=time.monotonic()
            self.launch(lambda:capture(self));self.launch(self.segment)
            stream=None;epoch=-1;uid=0;revision=0;start=last_voice=0.;active=False
            last='';stable=StablePrefix();gate=PhraseGate();slow=0;stream_start=0
            while not self.stop_event.is_set():
                try:chunk=self.jobs.get(timeout=.1)
                except Empty:continue
                if chunk.epoch!=self.epoch or self.paused.is_set():continue
                began=time.monotonic();lag=began-chunk.queued_at
                if lag>1:
                    self.overload('识别处理落后超过 1 秒');drain(self.jobs);stream=None;continue
                if stream is None or epoch!=chunk.epoch or chunk.reset:
                    stream=recognizer.create_stream();epoch=chunk.epoch
                    last='';stable=StablePrefix();gate=PhraseGate();active=False
                    start=stream_start=chunk.end-len(chunk.samples)/16000;last_voice=start
                rms=float(np.sqrt(np.mean(chunk.samples**2)))
                if rms>.003:
                    if not active:
                        start=chunk.end-len(chunk.samples)/16000;uid+=1
                        self.live_id=uid;self.latest_translation_key=None
                    active=True;last_voice=chunk.end
                stream.accept_waveform(16000,chunk.samples)
                # Silence endpoints only finalize; they never gate partial decoding.
                # Preserve context through short gaps. Beyond 12 seconds, prefer
                # a brief acoustic boundary over the old unconditional 30s cut.
                quiet=chunk.end-last_voice;duration=chunk.end-start
                hard_boundary=duration>=45
                final=active and (quiet>=.6 or (duration>=12 and quiet>=.12) or hard_boundary)
                if active and hard_boundary and quiet<.12:
                    self.emit('error','连续语音超过 45 秒且无可靠停顿，已限制上下文；此处词边界可能不准确。')
                if final:
                    stream.set_option('is_final','1');stream.input_finished()
                decoded=False
                while recognizer.is_ready(stream):
                    recognizer.decode_stream(stream);decoded=True
                produced=time.monotonic();cost=produced-began
                if decoded:
                    self.trace('decode',audio_end=chunk.end,queue_ms=lag*1000,inference_ms=cost*1000,
                               endpoint_wait_ms=(chunk.end-last_voice)*1000 if final else 0)
                    slow=slow+1 if cost>.5 else max(0,slow-1)
                    if slow>=3:
                        self.emit('error','流式推理连续超过 500 ms，当前负载可能跟不上；请关闭其它推理任务。')
                    self.emit('recognition',f'流式 · 推理 {cost*1000:.0f} ms · 排队 {lag*1000:.0f} ms · 音频缺口 {self.dropped}')
                text=recognizer.get_result(stream) if decoded or final else last
                if epoch!=self.epoch or self.paused.is_set() or self.stop_event.is_set():continue
                if active and text and (text!=last or final):
                    text,stable_text=stable.update(text,final)
                    revision+=1;last=text
                    language=self.language or text_language(text)
                    c=Caption(uid,start,chunk.end,text,language,session=self.session,epoch=epoch,revision=revision,
                              stable_text=stable_text,latency=produced-self.origin-start,
                              timing={'produced_at':produced,'audio_end':chunk.end,'last_voice_end':last_voice})
                    if language==self.target:c.translation=c.text
                    self.trace('asr',id=uid,revision=revision,final=final,audio_end=chunk.end,
                               queue_ms=lag*1000,inference_ms=cost*1000,
                               endpoint_wait_ms=(chunk.end-last_voice)*1000 if final else 0,text=text)
                    self.emit('final' if final else 'partial',c)
                    if self.translate and language!=self.target and gate.ready(stable_text,produced,final):
                        from dataclasses import replace
                        request=replace(c,text=stable_text,timing=dict(c.timing))
                        self.latest_translation_key=(epoch,uid,revision)
                        # One pending phrase per live utterance: coalesce, never queue all prefixes.
                        drain(self.translations);latest_put(self.translations,(epoch,request))
                if final:
                    self.trace('endpoint',id=uid,audio_end=chunk.end,last_voice_end=last_voice)
                    stream=None
                elif not active and chunk.end-stream_start>3:
                    # Reclaim extractor buffers during long silence without emitting captions.
                    stream=None
        except Exception as e:
            self.emit('error',f'流式识别失败：{e}。请检查实时模型是否完整。')
            self.stop_event.set()

    def translate_loop(self):
        translator=LocalTranslator()
        try:
            if self.translate and self.language!=self.target:
                source=self.language or 'en'
                translator.translate('你好' if source=='zh' else 'Hello everyone',source,self.target)
        except Exception as e:self.emit('translation_error',str(e))
        finally:self.translation_ready=True
        while not self.stop_event.is_set():
            try:epoch,c=self.translations.get(timeout=.1)
            except Empty:continue
            if epoch!=self.epoch or self.paused.is_set():continue
            began=time.monotonic()
            try:
                text=translator.translate(c.text,c.language,self.target)
                produced=time.monotonic()
                self.trace('translation',id=c.id,revision=c.revision,audio_end=c.end,
                           inference_ms=(produced-began)*1000,queue_ms=(began-c.timing['produced_at'])*1000,
                           text=text,source=c.text)
                if (epoch==self.epoch and not self.paused.is_set() and not self.stop_event.is_set()
                    and self.latest_translation_key==(epoch,c.id,c.revision)):
                    self.emit('translated',(self.session,epoch,c.id,c.revision,text,c.text,produced))
            except Exception as e:
                if epoch==self.epoch and not self.stop_event.is_set():self.emit('translation_error',str(e))
