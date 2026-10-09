"""Bounded, session-relative data contracts shared by UI and workers."""
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
import json
import os
from pathlib import Path

DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LocalCaptions'


def latest_put(queue: Queue, item):
    """Drop oldest work instead of building unbounded latency."""
    dropped = False
    while True:
        try:
            queue.put_nowait(item)
            return dropped
        except Full:
            try:
                queue.get_nowait()
                dropped = True
            except Empty:
                pass


def drain(queue):
    while True:
        try:
            queue.get_nowait()
        except Empty:
            return


@dataclass
class Caption:
    id: int
    start: float
    end: float
    text: str
    language: str
    translation: str = ''
    latency: float = 0
    session: str = ''
    epoch: int = 0
    revision: int = 0
    stable_text: str = ''
    timing: dict = field(default_factory=dict)


def stamp(seconds):
    ms = max(0, round(seconds * 1000))
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def export(captions, path, mode):
    from .presentation import display_text
    blocks = []
    for c in captions:
        original = display_text(c.text,c.language)
        # MT already normalizes a Chinese target. Do not run Japanese target or
        # Japanese source through a Chinese converter when exporting both.
        translated = original if c.translation == c.text else c.translation
        text = original if mode == 'original' else (translated or '[译文不可用]')
        if mode == 'both':
            text = original if translated == original else original + '\n' + (translated or '[译文不可用]')
        if Path(path).suffix.lower() == '.srt':
            blocks.append(f'{len(blocks)+1}\n{stamp(c.start)} --> {stamp(c.end)}\n{text}\n')
        else:
            blocks.append(f'[{stamp(c.start)}] {text}')
    Path(path).write_text('\n'.join(blocks), encoding='utf-8-sig')


def load_config():
    try:
        value = json.loads((DATA / 'config.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(value):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = DATA / 'config.tmp'
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(DATA / 'config.json')
