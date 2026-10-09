"""Real endpoint open/close/switch and unavailable-device checks."""
import json
import time
from pathlib import Path
from captioner.audio import devices
from captioner.engine import Engine
from captioner.core import DATA

results=[]
for name in [d['name'] for d in devices()]+['__unavailable_test_endpoint__']:
    engine=Engine(str(DATA/'models/base'),name)
    engine.start()
    time.sleep(3)
    events=[]
    while not engine.events.empty(): events.append(engine.events.get())
    engine.pause(True)
    time.sleep(.2)
    engine.pause(False)
    engine.stop()
    for thread in engine.threads: thread.join(10)
    results.append({'device':name,'status':[v for k,v in events if k in ('error','capture','model')],
                    'released':not engine.alive()})
Path('artifacts/device-report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
