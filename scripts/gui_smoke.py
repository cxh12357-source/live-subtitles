"""Instrument the real GUI/engine without changing the user's saved settings.

QtTest mouse events are component tests, not a physical click-through test.
The audio playback, WASAPI capture, ASR and rendered captions are real.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import json
import time
import winsound
from PySide6 import QtCore as C, QtWidgets as W, QtTest
import captioner.ui as ui


app=W.QApplication([])
app.setQuitOnLastWindowClosed(False)
ui.load_config=lambda: {'mode':'both','size':28,'width':900}
ui.save_config=lambda value: None
window=ui.MainWindow()
window.setWindowTitle('听见 · 自动验收实例')
window.show()
records=[]
began=time.monotonic()


def begin():
    window.start()
    assert window.engine is not None
    old_emit=window.engine.emit
    def record(kind,value):
        if kind in ('partial','final','translated','error','translation_error'):
            records.append({'at':time.monotonic()-began,'kind':kind,'text':getattr(value,'text',value)})
        old_emit(kind,value)
    window.engine.emit=record


def check_overlay():
    user=ctypes.WinDLL('user32')
    get_style=user.GetWindowLongW
    get_style.argtypes=[wintypes.HWND,ctypes.c_int]
    get_style.restype=ctypes.c_long
    overlay=window.overlay
    assert get_style(int(overlay.winId()),-20)&0x8  # WS_EX_TOPMOST
    window.through.setChecked(True)
    assert get_style(int(overlay.winId()),-20)&0x20  # WS_EX_TRANSPARENT
    window.unlock()
    assert not get_style(int(overlay.winId()),-20)&0x20
    origin=overlay.pos()
    QtTest.QTest.mousePress(overlay,C.Qt.LeftButton,pos=C.QPoint(80,30))
    QtTest.QTest.mouseMove(overlay,C.QPoint(120,50),delay=10)
    QtTest.QTest.mouseRelease(overlay,C.Qt.LeftButton,pos=C.QPoint(120,50))
    records.append({'qt_drag_moved':overlay.pos()!=origin,'topmost_and_transparent_styles':True})
    window.lock.setChecked(True)
    locked=overlay.pos()
    QtTest.QTest.mousePress(overlay,C.Qt.LeftButton,pos=C.QPoint(80,30))
    QtTest.QTest.mouseMove(overlay,C.QPoint(150,50),delay=10)
    QtTest.QTest.mouseRelease(overlay,C.Qt.LeftButton,pos=C.QPoint(150,50))
    assert overlay.pos()==locked
    window.lock.setChecked(False)


def snapshot():
    window.overlay.grab().save('artifacts/gui-captions.png')
    window.grab().save('artifacts/gui-controls.png')
    from captioner.core import export
    export(list(window.history),'artifacts/gui-session.srt','both')
    records.append({'rendered':window.overlay.label.text()})


def finish():
    winsound.PlaySound(None,0)
    window.stop()
    C.QTimer.singleShot(1500,complete)


def complete():
    records.append({'stopped':window.engine is None})
    Path('artifacts/gui-report.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    window.quit()


C.QTimer.singleShot(200,begin)
C.QTimer.singleShot(1500,check_overlay)
C.QTimer.singleShot(2200,lambda:winsound.PlaySound(str(Path('artifacts/english.wav').resolve()),winsound.SND_FILENAME|winsound.SND_ASYNC))
C.QTimer.singleShot(12000,snapshot)
C.QTimer.singleShot(14000,lambda:window.toggle_pause())
C.QTimer.singleShot(15000,lambda:window.toggle_pause())
C.QTimer.singleShot(17000,finish)
app.exec()
