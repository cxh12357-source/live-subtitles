"""Create synthetic-speech MP4 fixtures for browser/local-player loopback tests."""
from pathlib import Path
import wave
import av
import numpy as np


def make(name):
    source=Path('artifacts')/f'{name}.wav'
    with wave.open(str(source)) as wav:
        duration=wav.getnframes()/wav.getframerate()
    with av.open(str(Path('artifacts')/f'{name}.mp4'),'w') as out:
        video=out.add_stream('libx264',rate=10)
        video.width=960; video.height=540; video.pix_fmt='yuv420p'
        audio=out.add_stream('aac',rate=44100)
        resampler=av.AudioResampler(format='fltp',layout='stereo',rate=44100)
        with av.open(str(source)) as inp:
            for frame in inp.decode(audio=0):
                for converted in resampler.resample(frame):
                    for packet in audio.encode(converted): out.mux(packet)
        for converted in resampler.resample(None):
            for packet in audio.encode(converted): out.mux(packet)
        for packet in audio.encode(None): out.mux(packet)
        for i in range(int(duration*10)+1):
            pixels=np.full((540,960,3),(20,32,45),dtype=np.uint8)
            pixels[250:290,40:40+int(880*i/(duration*10))]=(90,210,240)
            frame=av.VideoFrame.from_ndarray(pixels,format='rgb24'); frame.pts=i
            for packet in video.encode(frame): out.mux(packet)
        for packet in video.encode(None): out.mux(packet)
    print(f'{name}: {duration:.2f}s')


if __name__=='__main__':
    for name in ['english','chinese']: make(name)
    Path('artifacts/player.html').write_text('''<!doctype html><html lang="zh"><meta charset="utf-8">
<title>实时字幕 · 浏览器视频验收</title><style>body{background:#14202d;color:#ecf5ff;font:24px system-ui;padding:40px}video{width:80vw;max-height:70vh}button{font:22px system-ui;padding:12px;margin:12px}</style>
<h1>系统音频回环 · 浏览器视频测试</h1><p>测试素材是 Windows 本地合成语音；字幕工具仅通过扬声器回环获取音频。</p>
<video id="v" src="english.mp4" controls></video><br>
<button onclick="v.src='english.mp4';v.play()">播放英文</button><button onclick="v.src='chinese.mp4';v.play()">播放中文</button><button onclick="document.documentElement.requestFullscreen()">无边框全屏</button>
</html>''',encoding='utf-8')
