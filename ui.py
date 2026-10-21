from PySide6.QtCore import Qt, QTimer, QRect, QRunnable, QThreadPool, QObject, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMenu,
    QMainWindow, QPushButton, QSpinBox, QVBoxLayout, QWidget, QMessageBox,
)

import capture
from model import Source, load_layout, save_layout

pool = QThreadPool()
pool.setMaxThreadCount(1)


def pil_to_qimage(img):
    img = img.convert("RGBA")
    w, h = img.size
    return QImage(img.tobytes(), w, h, 4 * w, QImage.Format_RGBA8888).copy()


def clamp_crop(crop, w, h):
    x, y, cw, ch = crop
    if cw <= 0 or ch <= 0:
        return 0, 0, w, h
    x, y = max(0, min(x, w - 1)), max(0, min(y, h - 1))
    return x, y, max(1, min(cw, w - x)), max(1, min(ch, h - y))


class Bridge(QObject):
    done = Signal(object)


class Job(QRunnable):
    def __init__(self, hwnd, crop, bridge):
        super().__init__()
        self.hwnd, self.crop, self.bridge = hwnd, crop, bridge

    def run(self):
        qimg = None
        try:
            img = capture.capture_window(self.hwnd)
            if img is not None:
                x, y, w, h = clamp_crop(self.crop, *img.size)
                qimg = pil_to_qimage(img.crop((x, y, x + w, y + h)))
        except Exception:
            pass
        self.bridge.done.emit(qimg)


class CropWidget(QWidget):
    def __init__(self, image, crop):
        super().__init__()
        self.image = image
        iw, ih = image.width(), image.height()
        self.k = min(1000 / iw, 650 / ih, 1.0)
        self.setFixedSize(int(iw * self.k), int(ih * self.k))
        self.rect_img = QRect(*crop) if crop[2] > 0 and crop[3] > 0 else QRect()
        self.start = None

    def to_img(self, p):
        return int(max(0, min(p.x() / self.k, self.image.width()))), \
               int(max(0, min(p.y() / self.k, self.image.height())))

    def mousePressEvent(self, e):
        self.start = self.to_img(e.position())

    def mouseMoveEvent(self, e):
        if self.start:
            x, y = self.to_img(e.position())
            sx, sy = self.start
            self.rect_img = QRect(min(sx, x), min(sy, y), abs(x - sx), abs(y - sy))
            self.update()

    def mouseReleaseEvent(self, e):
        self.start = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)
        if not self.rect_img.isNull():
            r = self.rect_img
            p.setPen(QPen(QColor(255, 0, 0), 2))
            p.setBrush(QColor(255, 0, 0, 40))
            p.drawRect(QRect(int(r.x() * self.k), int(r.y() * self.k),
                             int(r.width() * self.k), int(r.height() * self.k)))


class CropDialog(QDialog):
    def __init__(self, hwnd, crop, parent=None):
        super().__init__(parent)
        self.setWindowTitle("クロップ編集（ドラッグで範囲指定）")
        self.hwnd, self.crop = hwnd, list(crop)
        self.lay = QVBoxLayout(self)
        self.widget = None
        self.reload()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b_re = bb.addButton("再取得", QDialogButtonBox.ActionRole)
        b_all = bb.addButton("全体", QDialogButtonBox.ActionRole)
        b_re.clicked.connect(self.reload)
        b_all.clicked.connect(self.clear)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.lay.addWidget(bb)

    def reload(self):
        if self.widget:
            self.crop = self.current()
            self.lay.removeWidget(self.widget)
            self.widget.deleteLater()
            self.widget = None
        img = capture.capture_window(self.hwnd)
        if img is None:
            self.widget = QLabel("キャプチャできません（最小化中/見つからない）")
        else:
            self.widget = CropWidget(pil_to_qimage(img), self.crop)
        self.lay.insertWidget(0, self.widget)

    def clear(self):
        if isinstance(self.widget, CropWidget):
            self.widget.rect_img = QRect()
            self.widget.update()

    def current(self):
        if isinstance(self.widget, CropWidget) and not self.widget.rect_img.isNull() \
                and self.widget.rect_img.width() > 1 and self.widget.rect_img.height() > 1:
            r = self.widget.rect_img
            return [r.x(), r.y(), r.width(), r.height()]
        return [0, 0, 0, 0] if isinstance(self.widget, CropWidget) else self.crop

    def result_crop(self):
        return self.current()


class SourceItem(QGraphicsPixmapItem):
    def __init__(self, win, src):
        super().__init__()
        self.win, self.src, self.hwnd, self.busy = win, src, None, False
        self.setFlags(QGraphicsPixmapItem.ItemIsMovable | QGraphicsPixmapItem.ItemIsSelectable
                      | QGraphicsPixmapItem.ItemSendsGeometryChanges)
        self.setTransformationMode(Qt.SmoothTransformation)
        ph = QPixmap(200, 40)
        ph.fill(QColor(60, 60, 60))
        p = QPainter(ph)
        p.setPen(Qt.white)
        p.drawText(ph.rect(), Qt.AlignCenter, src.title[:24] + " (待機中)")
        p.end()
        self.setPixmap(ph)
        self.setPos(src.x, src.y)
        self.setScale(src.scale)
        self.bridge = Bridge()
        self.bridge.done.connect(self.on_image)
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(100, src.interval))
        QTimer.singleShot(0, self.tick)

    def set_interval(self, ms):
        self.src.interval = ms
        self.timer.start(max(100, ms))

    def find_hwnd(self):
        if not capture.is_valid(self.hwnd):
            self.hwnd = capture.find_by_title(self.src.title, exclude=(self.win.own_hwnd(),))
        return self.hwnd

    def tick(self):
        if self.busy or not self.find_hwnd():
            return
        self.busy = True
        pool.start(Job(self.hwnd, list(self.src.crop), self.bridge))

    def on_image(self, qimg):
        self.busy = False
        if qimg is not None:
            self.setPixmap(QPixmap.fromImage(qimg))

    def dispose(self):
        self.timer.stop()
        try:
            self.bridge.done.disconnect()
        except Exception:
            pass

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.ItemPositionHasChanged:
            self.src.x, self.src.y = value.x(), value.y()
            self.win.changed()
        return super().itemChange(change, value)

    def contextMenuEvent(self, e):
        self.setSelected(True)
        m = QMenu()
        a_crop = m.addAction("クロップ編集")
        a_park = m.addAction("復帰" if self.src.parked_rect else "退避")
        a_del = m.addAction("削除")
        act = m.exec(e.screenPos())
        if act == a_crop:
            self.win.edit_crop(self)
        elif act == a_park:
            self.win.toggle_park(self)
        elif act == a_del:
            self.win.remove_item(self)


class Canvas(QGraphicsView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor(30, 30, 30))
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.centerOn(0, 0)
        self.setDragMode(QGraphicsView.NoDrag)

    def wheelEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        if isinstance(it, SourceItem):
            f = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
            self.win.set_scale(it, it.src.scale * f)
            e.accept()
        else:
            super().wheelEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Window Parts Viewer")
        self.items, self.updating = [], False
        self.save_timer = QTimer(singleShot=True, interval=500)
        self.save_timer.timeout.connect(self.save)

        self.canvas = Canvas(self)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(300)
        b_ref = QPushButton("更新")
        b_add = QPushButton("ソース追加")
        self.chk_top = QCheckBox("常に手前")
        self.spin_scale = QDoubleSpinBox(minimum=0.1, maximum=10.0, singleStep=0.1, decimals=2, value=1.0)
        self.spin_int = QSpinBox(minimum=100, maximum=600000, singleStep=100, value=1000)
        self.spin_int.setSuffix(" ms")
        bar = QHBoxLayout()
        for w in (self.combo, b_ref, b_add, self.chk_top, QLabel("倍率"), self.spin_scale,
                  QLabel("更新間隔"), self.spin_int):
            bar.addWidget(w)
        bar.addStretch()
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(bar)
        lay.addWidget(self.canvas)
        self.setCentralWidget(root)

        b_ref.clicked.connect(self.refresh_list)
        b_add.clicked.connect(self.add_source)
        self.chk_top.toggled.connect(self.set_top)
        self.spin_scale.valueChanged.connect(self.on_scale_spin)
        self.spin_int.valueChanged.connect(self.on_int_spin)
        self.canvas.scene().selectionChanged.connect(self.on_selection)

        sources, top, geo = load_layout()
        self.resize(900, 600)
        if geo:
            self.setGeometry(*geo)
        self.refresh_list()
        for s in sources:
            self.add_item(s)
        if top:
            self.chk_top.setChecked(True)

    def own_hwnd(self):
        return int(self.winId())

    def refresh_list(self):
        self.combo.clear()
        for hwnd, title in capture.enum_windows(exclude=(self.own_hwnd(),)):
            self.combo.addItem(title, hwnd)

    def add_item(self, src):
        it = SourceItem(self, src)
        self.canvas.scene().addItem(it)
        self.items.append(it)
        return it

    def add_source(self):
        if self.combo.currentIndex() < 0:
            return
        hwnd, title = self.combo.currentData(), self.combo.currentText()
        src = Source(title=title)
        dlg = CropDialog(hwnd, src.crop, self)
        if dlg.exec():
            src.crop = dlg.result_crop()
        it = self.add_item(src)
        it.hwnd = hwnd
        self.changed()

    def edit_crop(self, it):
        if not it.find_hwnd():
            QMessageBox.warning(self, "エラー", "対象ウインドウが見つかりません")
            return
        dlg = CropDialog(it.hwnd, it.src.crop, self)
        if dlg.exec():
            it.src.crop = dlg.result_crop()
            it.tick()
            self.changed()

    def toggle_park(self, it):
        if not it.find_hwnd():
            return
        if it.src.parked_rect:
            capture.restore_window(it.hwnd, it.src.parked_rect)
            it.src.parked_rect = None
        else:
            it.src.parked_rect = capture.park_window(it.hwnd)
        self.changed()

    def remove_item(self, it):
        it.dispose()
        self.canvas.scene().removeItem(it)
        self.items.remove(it)
        self.changed()

    def selected(self):
        sel = self.canvas.scene().selectedItems()
        return sel[0] if sel and isinstance(sel[0], SourceItem) else None

    def on_selection(self):
        it = self.selected()
        if it:
            self.updating = True
            self.spin_scale.setValue(it.src.scale)
            self.spin_int.setValue(it.src.interval)
            self.updating = False

    def set_scale(self, it, v):
        v = max(0.1, min(10.0, v))
        it.src.scale = v
        it.setScale(v)
        if it is self.selected():
            self.updating = True
            self.spin_scale.setValue(v)
            self.updating = False
        self.changed()

    def on_scale_spin(self, v):
        it = self.selected()
        if it and not self.updating:
            self.set_scale(it, v)

    def on_int_spin(self, v):
        it = self.selected()
        if it and not self.updating:
            it.set_interval(v)
            self.changed()

    def set_top(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self.changed()

    def changed(self):
        self.save_timer.start()

    def save(self):
        g = self.geometry()
        save_layout([i.src for i in self.items], self.chk_top.isChecked(),
                    [g.x(), g.y(), g.width(), g.height()])

    def closeEvent(self, e):
        self.save()
        super().closeEvent(e)
