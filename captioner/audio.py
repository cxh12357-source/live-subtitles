"""Only WASAPI loopback endpoints are exposed; never default to microphone."""
import time
import math
import numpy as np
import pyaudiowpatch as pa
from scipy.signal import resample_poly
from .core import latest_put


def devices():
    with pa.PyAudio() as p:
        return [dict(d) for d in p.get_loopback_device_info_generator()]


def default_device():
    with pa.PyAudio() as p:
        return p.get_default_wasapi_loopback()['name']


def capture(engine):
    try:
        with pa.PyAudio() as p:
            candidates = list(p.get_loopback_device_info_generator())
            d = next((d for d in candidates if d['name'] == engine.device), None)
            if d is None:
                raise RuntimeError('所选输出设备不可用，请刷新设备并重新选择。')
            rate, channels = int(d['defaultSampleRate']), int(d['maxInputChannels'])
            sample_count = 0
            stream_origin = time.monotonic() - engine.origin
            def callback(data, count, timing, status):
                nonlocal sample_count
                sample_count += count
                if engine.stop_event.is_set():
                    return (None, pa.paComplete)
                if not engine.paused.is_set():
                    if status:
                        engine.dropped += 1
                    # Derive time from PCM frame count, not callback scheduling jitter.
                    end = stream_origin + sample_count / rate
                    captured_at=time.monotonic()
                    if hasattr(engine,'trace'):
                        engine.trace('capture',audio_end=end,block_ms=count/rate*1000,
                                     portaudio_age_ms=max(0,timing.get('current_time',0)-timing.get('input_buffer_adc_time',0))*1000)
                    if latest_put(engine.raw, (engine.epoch, end, data, rate, channels, bool(status),{'captured_at':captured_at})):
                        engine.dropped += 1
                return (None, pa.paContinue)
            with p.open(format=pa.paFloat32, channels=channels, rate=rate,
                        input=True, input_device_index=d['index'],
                        frames_per_buffer=round(rate*getattr(engine,'block_seconds',.1)), stream_callback=callback) as stream:
                engine.emit('capture', f"回环捕获中 · {d['name']} · {rate} Hz / {channels} 声道 / Float32")
                if hasattr(engine,'trace'): engine.trace('device',input_latency_ms=stream.get_input_latency()*1000,rate=rate,channels=channels)
                while not engine.stop_event.wait(.1):
                    if not stream.is_active():
                        raise RuntimeError('音频设备已断开或回环流停止；请停止并刷新设备。')
    except Exception as e:
        engine.emit('error', f'音频捕获失败：{e}')
        engine.stop_event.set()


def mono(data, channels):
    frames = np.nan_to_num(np.frombuffer(data, dtype='<f4').reshape(-1, channels))
    samples = frames.mean(axis=1)
    # Anti-phase stereo must not cancel speech. Normal stereo still uses the mean.
    energy = np.mean(frames * frames, axis=0)
    if channels > 1 and np.mean(samples*samples) < .05 * max(energy):
        samples = frames[:, int(np.argmax(energy))]
    return samples


def mono16(data, rate, channels):
    samples = mono(data, channels)
    divisor = math.gcd(rate, 16000)
    return resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32)
