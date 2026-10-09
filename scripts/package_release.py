"""Archive the verified onedir build and sources; never ship diagnostic captures."""
from pathlib import Path
import hashlib
import zipfile

root=Path(__file__).resolve().parents[1]
dist=root/'dist'
sources=[p for p in root.iterdir() if p.is_file() and p.suffix in ('.py','.md','.txt','.ps1','.cmd')]
sources += [p for d in ('captioner','tests','scripts','assets') for p in (root/d).rglob('*')
            if p.is_file() and '__pycache__' not in p.parts]
# These are explicitly generated speech fixtures and their clean replay reports.
# Actual mixed system recordings and the user's live-caption logs are excluded.
evidence=['engine-before.py','course.wav','english.wav','chinese.wav',
          'repair-clean-base.json','repair-clean-small.json','repair-clean-small-terms.json',
          'repair-long-audio.json','repair-auto-language.json','repair-silence-asr.json',
          'repair-gui-replay.json']
evidence += ['latency-baseline-engine.py','latency-before-loopback.json','latency-before-loopback-summary.json',
             'latency-stream-10min.json','latency-stream-10min-summary.json',
             'latency-stream-final.json','latency-stream-final-summary.json',
             'latency-translation-only.json','latency-translation-only-summary.json',
             'packaged-stream.json','stream-flush-ablation.json','zipformer-model-probe.json']
sources += [root/'artifacts'/name for name in evidence if (root/'artifacts'/name).exists()]
speed_evidence=['speed-baseline-streaming.py','speed-probe.json','speed-stretch-probe.json','sense-speed-probe.json',
                'speed-final.json','speed-final-summary.json',
                'speed-before.json','speed-before-summary.json','speed-after.json','speed-after-summary.json',
                'speed-terms-unrestricted.json','speed-terms-unrestricted-summary.json','speed-terms.json','speed-terms-summary.json','speed-long.json','speed-long-summary.json',
                'speed-long-before.json','speed-long-before-summary.json','speed-after-ungated.json','speed-after-ungated-summary.json','packaged-speed.json']
sources += [root/'artifacts'/name for name in speed_evidence if (root/'artifacts'/name).exists()]
# This directory contains only the explicitly generated fixtures and the attributed
# public LibriSpeech sample, not user audio recordings.
sources += [p for p in (root/'artifacts/speed').glob('*') if p.suffix in ('.wav','.flac','.json') and p.name!='human-chinese.wav']
checks=[]
for name,files,base in [
    ('LocalCaptions-Windows-x64.zip',list((dist/'LocalCaptions').rglob('*')),dist),
    ('LocalCaptions-source.zip',sources,root),
]:
    temp=dist/(name+'.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:
            if p.is_file(): z.write(p,p.relative_to(base))
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
    temp.replace(dist/name)
    digest=hashlib.sha256((dist/name).read_bytes()).hexdigest()
    checks.append(digest+'  '+name)
    print(name,(dist/name).stat().st_size,digest)
(dist/'SHA256SUMS.txt').write_text('\n'.join(checks)+'\n',encoding='utf-8')
