import os
os.environ.pop('QT_QPA_PLATFORM',None)
from PySide6 import QtWidgets as W, QtGui as G
from captioner import ui
app=W.QApplication([])
app.setFont(G.QFont("Microsoft YaHei",9))
ui.save_config=lambda _:None
ui.Hotkeys.__init__=lambda self,w:(super(ui.Hotkeys,self).__init__(),setattr(self,'ids',[]))[-1]
w=ui.MainWindow();w.show();app.processEvents()
body=w.findChild(W.QScrollArea).widget()
pix=body.grab();pix.save('artifacts/theme-after.png')
color=pix.toImage().pixelColor(2,2)
print('settings background:',color.name())
assert color.lightness()<100,'Light settings background under pale text'
w.tray.hide();w.overlay.hide();w.hide()

