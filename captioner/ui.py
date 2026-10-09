import ctypes
from ctypes import wintypes
from collections import deque
from queue import Queue, Empty
from threading import Thread
from pathlib import Path
import time
import argparse
import json
import re
from dataclasses import asdict
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from faster_whisper.tokenizer import _LANGUAGE_CODES
from .core import DATA, load_config, save_config, export
from .audio import devices, default_device
from .engine import Engine as WhisperEngine
from .streaming import StreamingEngine
from .review import ReviewedEngine
from .download import download_model, download_translation
from .presentation import CurrentCaption, display_text


def Engine(model,*args,**kwargs):
    enhanced=kwargs.pop('enhanced',True);speed=kwargs.pop('speed_hint',0.)
    if Path(model).name=='streaming-zh-en':
        return ReviewedEngine(model,*args,speed_hint=speed,**kwargs) if enhanced else StreamingEngine(model,*args,**kwargs)
    return WhisperEngine(model,*args,**kwargs)


def subtitle_pages(text, metrics, width):
    """Pixel-measured semantic wrapping. Every character remains in some page."""
    lines = []
    for paragraph in text.split('\n'):
        remaining = paragraph.strip()
        while remaining:
            end = 1
            while end < len(remaining) and metrics.horizontalAdvance(remaining[:end+1]) <= width:
                end += 1
            if end < len(remaining):
                boundaries = [m.end() for m in re.finditer(r'[，。！？；、,.!?;\s]', remaining[:end])]
                useful = [i for i in boundaries if i >= end//2]
                if useful: end = useful[-1]
            lines.append(remaining[:end].strip())
            remaining = remaining[end:].lstrip()
    return ['\n'.join(lines[i:i+2]) for i in range(0,len(lines),2)]


class Overlay(W.QWidget):
    def __init__(self):
        super().__init__(None, C.Qt.FramelessWindowHint | C.Qt.WindowStaysOnTopHint | C.Qt.Tool)
        self.setWindowTitle('实时字幕 · 悬浮窗')
        self.setAttribute(C.Qt.WA_TranslucentBackground)
        self.locked = self.passthrough = False
        self.drag = None
        layout = W.QVBoxLayout(self)
        self.label = W.QLabel()
        self.label.setTextFormat(C.Qt.PlainText)
        self.label.setWordWrap(False)
        self.label.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        self.label.setAlignment(C.Qt.AlignCenter)
        self.label.setAttribute(C.Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.label)
        layout.setContentsMargins(18,12,18,12)
        self.pages, self.page_index, self.content, self.caption_key = [], 0, '', None
        self.bilingual = None
        self.page_at = self.activity_at = 0
        self.clear_delay = 3
        self.resize(950, 180)
        screen = W.QApplication.primaryScreen().availableGeometry()
        self.resize(min(950, screen.width()-40), 180)
        self.move(screen.center().x()-self.width()//2, screen.bottom()-230)

    def appearance(self, size, color, opacity, font, width):
        screen = self.screen().availableGeometry()
        width = min(width, screen.width()-20)
        self.resize(width, self.height())
        typeface = G.QFont(font); typeface.setPixelSize(size)
        self.label.setFont(typeface)
        self.label.setStyleSheet(f'color:{color};background:transparent;')
        self.alpha = opacity
        self.setFixedHeight(self.label.fontMetrics().lineSpacing()*2+28)
        self.resize(width,self.height())
        self.reflow()
        self.keep_on_screen()
        self.update()

    def reflow(self):
        width=max(40,self.width()-40)
        if self.bilingual:
            lines=[('\n'.join(subtitle_pages(t,self.label.fontMetrics(),width))).split('\n') for t in self.bilingual]
            self.pages=[lines[0][min(i,len(lines[0])-1)]+'\n'+lines[1][min(i,len(lines[1])-1)]
                        for i in range(max(len(lines[0]),len(lines[1])))]
        else:
            self.pages = subtitle_pages(self.content,self.label.fontMetrics(),width)
        self.page_index = min(self.page_index,max(0,len(self.pages)-1))
        self.label.setText(self.pages[self.page_index] if self.pages else '')

    def present(self, text, key, now, refresh=True, bilingual=None):
        if key != self.caption_key:
            self.page_index = 0; self.page_at = now
        self.caption_key, self.content = key, text
        self.bilingual=bilingual
        if refresh: self.activity_at = now
        self.reflow()

    def clear_caption(self):
        self.pages, self.page_index, self.content, self.caption_key = [], 0, '', None
        self.bilingual=None
        self.label.clear()

    def advance(self, now):
        if not self.pages: return False
        # Finish the current utterance's remaining pages before the idle timeout.
        if self.page_index+1 < len(self.pages):
            dwell = max(1.2,min(3,len(self.pages[self.page_index])/14))
            if now-self.page_at >= dwell:
                self.page_index += 1; self.page_at = now
                self.label.setText(self.pages[self.page_index])
            return False
        if now-max(self.activity_at,self.page_at) >= self.clear_delay:
            self.clear_caption(); return True
        return False

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'content'): self.reflow()

    def keep_on_screen(self):
        area=self.screen().availableGeometry()
        self.resize(min(self.width(),area.width()-20),min(self.height(),area.height()-20))
        self.move(max(area.left()+10,min(self.x(),area.right()-self.width()-9)),
                  max(area.top()+10,min(self.y(),area.bottom()-self.height()-9)))

    def paintEvent(self, event):
        p = G.QPainter(self)
        p.setRenderHint(G.QPainter.Antialiasing)
        p.setPen(C.Qt.NoPen)
        p.setBrush(G.QColor(12, 18, 28, getattr(self, 'alpha', 175)))
        p.drawRoundedRect(self.rect(), 14, 14)

    def mousePressEvent(self, e):
        if not self.locked and e.button() == C.Qt.LeftButton:
            self.drag = (e.globalPosition().toPoint(), self.pos(), self.width(), e.position().x() > self.width()-25)

    def mouseMoveEvent(self, e):
        if self.drag:
            start, pos, width, resize = self.drag
            delta = e.globalPosition().toPoint()-start
            if resize:
                self.resize(max(360, width+delta.x()), self.height())
            else:
                self.move(pos+delta)

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.keep_on_screen()

    def penetrate(self, value):
        self.passthrough = value
        self.setWindowFlag(C.Qt.WindowTransparentForInput, value)
        self.show()


class Hotkeys(C.QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.ids = []
        user = ctypes.windll.user32
        for ident, key in [(1, 0x53), (2, 0x4c)]:
            if user.RegisterHotKey(None, ident, 0x4000 | 0x2 | 0x4, key):
                self.ids.append(ident)

    def nativeEventFilter(self, kind, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312:
            if msg.wParam == 1:
                self.window.toggle_pause()
            elif msg.wParam == 2:
                self.window.unlock()
            return True, 0
        return False, 0

    def close(self):
        for ident in self.ids:
            ctypes.windll.user32.UnregisterHotKey(None, ident)


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('听见 · 本地实时字幕')
        self.resize(680, 770)
        self.config = load_config()
        if self.config.get('schema',0) < 2:
            self.config.update(color='#ffffff',size=30,font='Microsoft YaHei',schema=2)
            if (DATA/'models/small/model.bin').exists(): self.config['model']='small'
        if self.config.get('schema',0)<3 and (DATA/'models/streaming-zh-en/encoder.int8.onnx').exists():
            self.config.update(schema=3,model='streaming-zh-en')
        self.engine = None
        self.history = deque(maxlen=10000)
        self.current = CurrentCaption()
        self.closing = False
        self.diagnostics = None
        self.download_events = Queue(4)
        self.download_thread = None
        self.overlay = Overlay()
        self.overlay.show()
        body = W.QWidget()
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        scroll.setWidget(body)
        self.setCentralWidget(scroll)
        layout = W.QVBoxLayout(body)
        title = W.QLabel('听见  /  LIVE CAPTIONS')
        title.setStyleSheet('font-size:25px;font-weight:600;color:#83d8f7')
        layout.addWidget(title)
        layout.addWidget(W.QLabel('本机处理 · 系统声音回环 · 无需上传视频'))
        form = W.QFormLayout()
        layout.addLayout(form)
        self.device = W.QComboBox()
        self.refresh = W.QPushButton('刷新输出设备')
        self.refresh.clicked.connect(self.refresh_devices)
        form.addRow('音频输出', self.device)
        form.addRow('', self.refresh)
        self.model = W.QComboBox()
        self.model.addItems(['streaming-zh-en','tiny', 'base', 'small'])
        self.model.setCurrentText(self.config.get('model', 'streaming-zh-en'))
        form.addRow('识别模型', self.model)
        form.addRow('',W.QLabel('streaming-zh-en：本地中英流式；其它模型：Whisper 多语言兼容（较慢）'))
        self.backend = W.QComboBox()
        self.backend.addItems(['cpu', 'cuda'])
        form.addRow('计算设备', self.backend)
        self.language = W.QComboBox()
        self.language.addItem('自动检测', None)
        for code in _LANGUAGE_CODES:
            if code == 'yue':  # Only large-v3 has the separate Cantonese token.
                continue
            names={'zh':'中文','en':'English','ja':'日本語','ko':'한국어','fr':'Français','de':'Deutsch','es':'Español'}
            self.language.addItem(f'{names[code]} ({code})' if code in names else code, code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.config.get('language'))))
        form.addRow('源语言（中文视频建议指定中文）', self.language)
        self.hotwords = W.QLineEdit(); self.hotwords.setMaxLength(200)
        self.hotwords.setPlaceholderText('可选：本次视频的术语；不自动替换文字，不保存为全局提示')
        form.addRow('本次识别术语（可留空）',self.hotwords)
        self.enhanced=W.QCheckBox('增强声学复核（本地，需额外约 240 MB 模型）')
        self.enhanced.setChecked(self.config.get('enhanced',True))
        self.enhanced.toggled.connect(self.configure_model)
        form.addRow('',self.enhanced)
        self.speed=W.QDoubleSpinBox();self.speed.setRange(0,4);self.speed.setDecimals(2);self.speed.setSingleStep(.05)
        self.speed.setSpecialValueText('未知 / 无需设置');self.speed.setValue(self.config.get('speed_hint',0))
        self.speed.setToolTip('可随播放调整；只调节复核时机，不改变采样率或音频速度。无法读取播放器倍速。')
        self.speed.valueChanged.connect(lambda value:self.engine.set_speed(value) if self.engine and hasattr(self.engine,'set_speed') else None)
        form.addRow('可选倍速提示（0 = 未知）',self.speed)
        self.model.currentTextChanged.connect(self.configure_model)
        self.configure_model()
        self.mode = W.QComboBox()
        for label, value in [('仅原文', 'original'), ('仅译文', 'translation'), ('原文 + 译文', 'both')]:
            self.mode.addItem(label, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.config.get('mode','original'))))
        form.addRow('显示模式', self.mode)
        self.target = W.QComboBox()
        self.target.addItems(['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'ru'])
        self.target.setCurrentText(self.config.get('target','zh'))
        form.addRow('译文语言（zh = 简体中文）', self.target)
        self.download_asr = W.QPushButton('下载所选识别模型（首次使用）')
        self.download_asr.clicked.connect(lambda: self.download(False))
        form.addRow('', self.download_asr)
        self.download_tr = W.QPushButton('下载原文 → 译文语言包（自动检测时下载 en → 目标）')
        self.download_tr.clicked.connect(lambda: self.download(True))
        form.addRow('', self.download_tr)
        self.width = W.QSpinBox(); self.width.setRange(360, 3000); self.width.setValue(self.config.get('width',self.overlay.width()))
        self.size = W.QSpinBox(); self.size.setRange(16,72); self.size.setValue(self.config.get('size',30))
        self.opacity = W.QSpinBox(); self.opacity.setRange(0,255); self.opacity.setValue(self.config.get('opacity',175))
        self.font = W.QFontComboBox(); self.font.setCurrentFont(G.QFont(self.config.get('font','Microsoft YaHei UI')))
        self.color = self.config.get('color','#ffffff')
        self.color_button = W.QPushButton('选择字体颜色'); self.color_button.clicked.connect(self.choose_color)
        form.addRow('字幕宽度（也可拖动右侧边缘）', self.width)
        form.addRow('字号', self.size)
        form.addRow('背景不透明度 0–255', self.opacity)
        form.addRow('字体', self.font)
        self.clear_seconds = W.QDoubleSpinBox(); self.clear_seconds.setRange(1,10)
        self.clear_seconds.setValue(self.config.get('clear_seconds',3))
        self.clear_seconds.valueChanged.connect(lambda v: setattr(self.overlay,'clear_delay',v))
        self.overlay.clear_delay = self.clear_seconds.value()
        form.addRow('无新字幕后清除（秒）',self.clear_seconds)
        form.addRow('', self.color_button)
        self.lock = W.QCheckBox('锁定位置'); self.lock.toggled.connect(lambda v: setattr(self.overlay,'locked',v))
        self.through = W.QCheckBox('鼠标穿透（Ctrl+Shift+L 解除）'); self.through.toggled.connect(self.overlay.penetrate)
        form.addRow(self.lock,self.through)
        for widget in (self.size,self.width,self.opacity):
            widget.valueChanged.connect(self.apply_appearance)
        self.font.currentFontChanged.connect(self.apply_appearance)
        row = W.QHBoxLayout(); layout.addLayout(row)
        self.start_button = W.QPushButton('开始'); self.start_button.clicked.connect(self.start)
        self.pause_button = W.QPushButton('暂停 / 恢复'); self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button = W.QPushButton('停止'); self.stop_button.clicked.connect(self.stop)
        self.export_button = W.QPushButton('导出 TXT / SRT'); self.export_button.clicked.connect(self.export_session)
        for widget in (self.start_button,self.pause_button,self.stop_button,self.export_button): row.addWidget(widget)
        self.statuses = {}
        self.status = W.QLabel('尚未开始'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.error = W.QLabel(); self.error.setWordWrap(True); self.error.setStyleSheet('color:#ffb595'); layout.addWidget(self.error)
        layout.addStretch()
        layout.addWidget(W.QLabel('Ctrl+Shift+S 开始/暂停/恢复 · Ctrl+Shift+L 解除穿透并显示控制台\n关闭窗口会留在托盘；从托盘“退出”可释放资源并退出。'))
        # Style the scroll content and every editor, not only QMainWindow:
        # Windows light palettes otherwise leave pale text on a white surface.
        self.setStyleSheet('''
            QWidget {color:#e6edf4;background-color:#14202d;}
            QScrollArea {border:0;}
            QLabel,QCheckBox {background:transparent;}
            QPushButton,QComboBox,QAbstractSpinBox,QLineEdit {
                color:#f0f4f8;background-color:#27394b;
                padding:5px;border:1px solid #52677d;border-radius:4px;
                selection-background-color:#326891;selection-color:#ffffff;
            }
            QLineEdit {placeholder-text-color:#bac8d5;}
            QPushButton:hover {background-color:#36516b;}
            QPushButton:pressed {background-color:#1b3043;}
            QWidget:disabled {color:#b4c0cc;}
            QPushButton:disabled,QComboBox:disabled,QAbstractSpinBox:disabled,QLineEdit:disabled {
                color:#b4c0cc;background-color:#1d2c3b;border-color:#435567;
            }
            QComboBox QAbstractItemView {color:#f0f4f8;background-color:#27394b;selection-background-color:#326891;}
            QToolTip {color:#f0f4f8;background-color:#27394b;border:1px solid #83d8f7;}
        ''')
        self.tray = W.QSystemTrayIcon(self.style().standardIcon(W.QStyle.SP_MediaVolume),self)
        menu = W.QMenu()
        for text, callback in [('显示控制台',self.show_control),('开始/暂停/恢复',self.toggle_pause),('停止',self.stop),('解除穿透',self.unlock),('退出',self.quit)]:
            menu.addAction(text,callback)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason:self.show_control() if reason==W.QSystemTrayIcon.DoubleClick else None); self.tray.show()
        self.hotkeys = Hotkeys(self)
        W.QApplication.instance().installNativeEventFilter(self.hotkeys)
        if len(self.hotkeys.ids)<2: self.error.setText('部分快捷键被占用；请使用控制台或托盘解除穿透。')
        self.refresh_devices(); self.apply_appearance()
        x,y = self.config.get('x'),self.config.get('y')
        if isinstance(x,int) and isinstance(y,int):
            if any(s.availableGeometry().contains(C.QPoint(x,y)) for s in W.QApplication.screens()): self.overlay.move(x,y)
        self.overlay.keep_on_screen()
        self.timer = C.QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(50)

    def apply_appearance(self, *_):
        self.overlay.appearance(self.size.value(),self.color,self.opacity.value(),self.font.currentFont().family(),self.width.value())

    def configure_model(self,*_):
        streaming=self.model.currentText()=='streaming-zh-en'
        if streaming:self.backend.setCurrentText('cpu')
        self.backend.setEnabled(not streaming and self.engine is None)
        self.hotwords.setEnabled(self.engine is None and (not streaming or self.enhanced.isChecked()))
        self.enhanced.setEnabled(streaming and self.engine is None)
        self.speed.setEnabled(streaming)

    def choose_color(self):
        color = W.QColorDialog.getColor(G.QColor(self.color),self)
        if color.isValid(): self.color=color.name(); self.apply_appearance()

    def refresh_devices(self):
        old = self.device.currentText() or self.config.get('device')
        self.device.clear()
        try:
            entries = devices()
            self.device.addItems([d['name'] for d in entries])
            self.device.setCurrentText(old if old in [d['name'] for d in entries] else default_device())
        except Exception as e: self.error.setText(f'未找到可用回环设备：{e}')

    def settings(self):
        return dict(schema=3,enhanced=self.enhanced.isChecked(),speed_hint=self.speed.value(),clear_seconds=self.clear_seconds.value(),model=self.model.currentText(),language=self.language.currentData(),mode=self.mode.currentData(),target=self.target.currentText(),device=self.device.currentText(),width=self.overlay.width(),size=self.size.value(),opacity=self.opacity.value(),font=self.font.currentFont().family(),color=self.color,x=self.overlay.x(),y=self.overlay.y())

    def save(self):
        try: save_config(self.settings())
        except OSError as e: self.error.setText(f'配置保存失败：{e}')

    def download(self, translation):
        if self.engine: return
        if self.download_thread and self.download_thread.is_alive(): return
        source = self.language.currentData() or 'en'
        target, model = self.target.currentText(), self.model.currentText()
        enhanced=self.enhanced.isChecked();has_terms=bool(self.hotwords.text().strip())
        self.error.setText('正在下载本地模型，请稍候；仅下载文件，不上传音频或字幕。')
        self.download_asr.setEnabled(False); self.download_tr.setEnabled(False)
        def work():
            try:
                path = download_translation(source,target) if translation else download_model(model)
                if not translation and model=='streaming-zh-en' and enhanced:
                    download_model('sensevoice')
                    if has_terms:download_model('small')
                self.download_events.put(('完成',str(path)))
            except Exception as e: self.download_events.put(('失败',str(e)))
        self.download_thread = Thread(target=work,daemon=True); self.download_thread.start()

    def start(self):
        if self.engine: return
        if self.download_thread and self.download_thread.is_alive():
            self.error.setText('请等待模型下载完成后再开始。'); return
        path = DATA/'models'/self.model.currentText()
        streaming=self.model.currentText()=='streaming-zh-en'
        required=['encoder.int8.onnx','decoder.int8.onnx','tokens.txt'] if streaming else ['model.bin','config.json','tokenizer.json']
        if not all((path/f).exists() for f in required):
            self.error.setText('缺少完整识别模型。请先点击“下载所选识别模型”；联网仅用于下载。'); return
        if streaming and self.language.currentData() not in (None,'zh','en'):
            self.error.setText('流式模型支持中文/英文自动混合识别。其它语言请选择 tiny/base/small 兼容模型。');return
        if not self.device.currentText(): self.error.setText('请连接音频输出设备并刷新。'); return
        self.save(); self.history.clear(); self.overlay.clear_caption(); self.error.clear()
        self.engine = Engine(str(path),self.device.currentText(),self.language.currentData(),self.target.currentText(),self.mode.currentData()!='original',self.backend.currentText(),hotwords=self.hotwords.text(),enhanced=self.enhanced.isChecked(),speed_hint=self.speed.value())
        self.current.reset(self.engine.session,self.engine.epoch)
        self.statuses={}; self.engine.start()
        for widget in self.session_controls(): widget.setEnabled(False)

    def session_controls(self):
        return (self.start_button,self.device,self.refresh,self.model,self.language,self.hotwords,self.enhanced,self.mode,self.target,self.backend,self.download_asr,self.download_tr)

    def toggle_pause(self):
        if not self.engine: self.start(); return
        if not self.engine.stop_event.is_set():
            self.engine.pause(not self.engine.paused.is_set())
            self.current.reset(self.engine.session,self.engine.epoch)
            self.overlay.clear_caption()

    def stop(self):
        if self.engine:
            self.engine.stop(); self.statuses['capture']='正在停止，等待当前推理释放…'
            self.current.reset(self.engine.session,self.engine.epoch)
            self.overlay.clear_caption()

    def poll(self):
        try:
            state,message=self.download_events.get_nowait()
            self.error.setText(f'下载{state}：{message}')
            self.download_asr.setEnabled(True); self.download_tr.setEnabled(True)
        except Empty: pass
        if self.engine:
            if (self.current.session,self.current.epoch) != (self.engine.session,self.engine.epoch):
                self.current.reset(self.engine.session,self.engine.epoch)
                self.overlay.clear_caption()
            for _ in range(128):
                try: kind,value=self.engine.events.get_nowait()
                except Empty: break
                if self.diagnostics is not None and kind in ('partial','final','translated','error','translation_error'):
                    self.diagnostics.append({'at':time.monotonic(),'kind':kind,
                        'value':asdict(value) if kind in ('partial','final') else value})
                if kind in ('error','translation_error'): self.error.setText(value)
                elif kind in ('partial','final'):
                    if self.engine.paused.is_set() or self.engine.stop_event.is_set(): continue
                    if kind=='final' and (value.session,value.epoch)==(self.engine.session,self.engine.epoch):
                        prior=next((c for c in self.history if (c.session,c.epoch,c.id)==(value.session,value.epoch,value.id)),None)
                        if prior is None or value.revision>prior.revision:
                            if prior is not None:self.history.remove(prior)
                            self.history.append(value)
                            if len(self.history)>1 and self.history[-2].start>value.start:
                                self.history=deque(sorted(self.history,key=lambda c:(c.start,c.id)),maxlen=10000)
                    if self.current.accept(value,kind=='final'):
                        self.statuses['subtitle']='字幕：已确认' if kind=='final' else '字幕：识别中（临时结果）'
                        self.render()
                elif kind=='translated':
                    for c in reversed(self.history):
                        if (c.session,c.epoch,c.id,c.revision)==tuple(value[:4]): c.translation=value[4]; break
                    if self.current.translate(*value): self.render(refresh=False)
                elif kind=='empty_final':
                    c=self.current.caption
                    if c and (c.session,c.epoch,c.id)==tuple(value):
                        self.current.expired=True; self.overlay.clear_caption()
                elif kind=='clear_partial': self.overlay.clear_caption()
                else: self.statuses[kind]=value
            if not self.engine.alive():
                self.engine=None; self.statuses['capture']='已停止 · 音频设备与工作线程已释放'
                self.overlay.clear_caption(); self.current.expired=True
                for widget in self.session_controls(): widget.setEnabled(True)
                self.configure_model()
            self.status.setText('\n'.join(self.statuses.values()))
        if self.overlay.advance(time.monotonic()): self.current.expired=True
        if self.closing and self.engine is None:
            self.hotkeys.close(); self.tray.hide(); W.QApplication.instance().quit()

    def render(self,refresh=True):
        c=self.current.caption
        if c:
            bilingual=None
            if self.mode.currentData()=='both' and c.translation:
                original=display_text(c.text,c.language)
                translated=display_text(c.translation,self.target.currentText())
                if original!=translated:bilingual=(original,translated)
            self.overlay.present(self.current.text(self.mode.currentData(),self.target.currentText()),
                                 self.current.key(c),time.monotonic(),refresh=refresh,bilingual=bilingual)
            if self.engine and hasattr(self.engine,'trace'):
                self.engine.trace('display',id=c.id,revision=c.revision,final=self.current.confirmed,
                                  ui_ms=(time.monotonic()-c.timing.get('translation_produced_at' if not refresh else 'produced_at',time.monotonic()))*1000,
                                  audio_end=c.end,translated=not refresh,text=self.overlay.label.text(),full_text=self.overlay.content)
            if self.diagnostics is not None:
                self.diagnostics.append({'at':time.monotonic(),'kind':'display',
                    'value':{'session':c.session,'epoch':c.epoch,'id':c.id,'revision':c.revision,
                             'text':self.overlay.label.text(),'pages':list(self.overlay.pages)}})

    def show_control(self): self.showNormal(); self.raise_(); self.activateWindow()
    def unlock(self): self.through.setChecked(False); self.lock.setChecked(False); self.show_control()
    def export_session(self):
        path,_=W.QFileDialog.getSaveFileName(self,'导出当前会话','captions.srt','SRT (*.srt);;TXT (*.txt)')
        if path:
            try: export(list(self.history),path,self.mode.currentData())
            except OSError as e: self.error.setText(f'导出失败：{e}')
    def closeEvent(self,event):
        self.save()
        if self.tray.isSystemTrayAvailable(): self.hide(); event.ignore()
        else: self.quit(); event.ignore()
    def quit(self):
        self.save(); self.closing=True; self.stop(); self.hide(); self.overlay.hide()


def main():
    parser=argparse.ArgumentParser(description='Windows 本地实时字幕')
    parser.add_argument('--start',action='store_true',help='启动后开始捕获')
    parser.add_argument('--quit-after',type=int,help='验收用：指定秒数后停止并退出')
    parser.add_argument('--diagnostics',type=Path,help='显式保存验收事件（包含字幕文本，不含音频）')
    args=parser.parse_args()
    app=W.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window=MainWindow(); window.show()
    if args.diagnostics:
        window.diagnostics=deque(maxlen=10000)
        def write_diagnostics():
            args.diagnostics.write_text(json.dumps({'events':list(window.diagnostics),
                'released':window.engine is None,'captions':len(window.history)},ensure_ascii=False,indent=2),encoding='utf-8')
        app.aboutToQuit.connect(write_diagnostics)
    if args.start: C.QTimer.singleShot(300,window.start)
    if args.quit_after: C.QTimer.singleShot(max(1,args.quit_after)*1000,window.quit)
    return app.exec()
