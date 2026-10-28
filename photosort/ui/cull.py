"""The Cull screen: Filmstrip view (default) and Grid view, keyboard-first.

Keys (settled in the cull-feel prototype, wayfinder ticket 004):
  ← / →            previous / next photo; holding shows a blurry placeholder until release
  A / S / D        Pick / Reject / Unmark (A and S toggle)
  T                auto-advance after setting a Pick or Reject
  Z, double-click  100% zoom at the mouse; drag to pan; ← / → keep the zoom spot
  R                cycle the Filter
  Tab              switch Filmstrip / Grid; in Grid, Enter or double-click opens a photo
  ? or F1          help;  Esc  leaves zoom or help, otherwise goes back to the home screen

The public methods under "actions" are also what the Xbox controller calls.
"""
import bisect

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..images import ImageCache, ThumbStore
from ..shoot import PICK, REJECT
from ..thumbs import ThumbBuilder

FILTERS = ["all", "hide rejects", "picks only", "unmarked only"]
GREEN, RED, GREY = QColor(60, 200, 90), QColor(230, 70, 60), QColor(140, 140, 140)
BACKGROUND = QColor(18, 18, 18)

STRIP_HEIGHT = 130
STRIP_THUMB = (150, 100)
GRID_CELL = (240, 180)
INFO_HEIGHT = 30

HELP = [
    ("← →", "previous / next photo (hold to fly past with a quick preview)"),
    ("A  S  D", "Pick / Reject / Unmark  (A or S again clears the mark)"),
    ("T", "auto-advance after a Pick or Reject"),
    ("Z, double-click", "100% zoom at the mouse; drag to pan; ← → keep the spot"),
    ("R", "filter: all / hide rejects / picks only / unmarked only"),
    ("Tab", "switch Filmstrip / Grid;  Grid: arrows move, Enter opens"),
    ("Home  End", "first / last photo"),
    ("Esc", "leave zoom or help, otherwise back to the home screen"),
    ("", ""),
    ("Controller", ""),
    ("A  B  X", "Pick / Reject / Unmark"),
    ("D-pad, left stick", "previous / next  (Grid: move)"),
    ("Y", "toggle 100% zoom at the centre;  hold RT to peek at 100%"),
    ("Right stick", "pan while zoomed"),
    ("View  /  Menu", "cycle filter  /  auto-advance"),
    ("Right-stick click", "switch Filmstrip / Grid (Grid: open photo)"),
]


class CullView(QWidget):
    home_requested = Signal()
    marks_changed = Signal()

    def __init__(self, shoot, prefs, screen_size):
        super().__init__()
        self.shoot = shoot
        self.prefs = prefs
        self.photos = shoot.cull_photos()
        paths = [shoot.folder / p.name for p in self.photos]
        self.images = ImageCache(paths, screen_size)
        self.thumbs = ThumbStore(shoot.folder, [p.name for p in self.photos])
        self.images.loaded.connect(self.on_image_loaded)
        self.thumbs.loaded.connect(lambda _: self.update())
        # Existing folders opened as a Shoot get their Grid thumbnails built in the background;
        # until then the Grid shows the embedded EXIF thumbnails.
        self.builder = ThumbBuilder(shoot.folder, [p.name for p in self.photos])
        self.builder.built.connect(self.thumbs.disk_thumb_built)

        self.view = prefs["view"]
        self.filter = prefs["filter"] if prefs["filter"] in FILTERS else "all"
        self.auto_advance = prefs["auto_advance"]
        self.zoom = False
        self.peek = False                  # 100% while the controller's RT is held
        self.zoom_center = [0.5, 0.5]      # fraction of the photo under the centre of the screen
        self.flying = False                # Next is held: show placeholders, don't decode
        self.help = False
        self.drag = None
        self.grid_scroll = 0
        self.photo_rect = QRect()          # where the photo was last drawn, for zoom-at-mouse
        self.grid_cells = []               # (rect, index) drawn last, for clicks

        self.visible = []                  # indices of photos the Filter shows
        self.update_visible()
        names = [p.name for p in self.photos]
        self.i = names.index(shoot.last_viewed) if shoot.last_viewed in names else 0
        if self.visible and self.i not in self.visible:
            self.i = self.visible[0]
        self.images.request(self.i)

        # While the Library drive is unplugged, keep trying to save.
        self.retry = QTimer(self, interval=2000, timeout=self.retry_save)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def close_shoot(self):
        self.shoot.save()
        self.images.close()
        self.thumbs.close()
        self.builder.close()
        self.retry.stop()

    # ---------- model ----------

    @property
    def current(self):
        return self.photos[self.i]

    def shows(self, photo):
        m = photo.mark
        return {"all": True, "hide rejects": m != REJECT, "picks only": m == PICK,
                "unmarked only": m is None}[self.filter]

    def update_visible(self):
        self.visible = [j for j, p in enumerate(self.photos) if self.shows(p)]

    def visible_position(self):
        """Position of the current photo among the visible ones (or where it would be)."""
        return bisect.bisect_left(self.visible, self.i)

    def go_to(self, j, decode=True):
        self.i = j
        self.shoot.last_viewed = self.photos[j].name
        if decode:
            self.images.request(j)
        if self.zoom or self.peek:
            self.images.request_full(j)
        self.update()

    def step(self, d, decode=True):
        """Move d visible photos on. Returns False at either end."""
        pos = self.visible_position()
        if self.i in self.visible:
            pos += d
        elif d < 0:
            pos -= 1  # current one is hidden; bisect points just after it
        if not 0 <= pos < len(self.visible):
            return False
        self.go_to(self.visible[pos], decode)
        return True

    # ---------- actions (keyboard and controller) ----------

    def navigate(self, d, held=False):
        """Previous/next. While held, fly past with placeholders and decode only where you land."""
        if held:
            self.flying = True
        self.step(d, decode=not held)

    def land(self):
        if self.flying:
            self.flying = False
            self.images.request(self.i)
            self.update()

    def mark(self, mark):
        if not self.photos:
            return
        photo = self.current
        if mark is not None and photo.mark == mark:
            mark = None  # A on a Pick (or S on a Reject) clears it
        if not self.shoot.set_mark(photo, mark):
            self.retry.start()
        self.update_visible()
        self.marks_changed.emit()
        if mark is not None and self.auto_advance:
            self.step(1)
        self.update()

    def toggle_auto_advance(self):
        self.auto_advance = not self.auto_advance
        self.prefs["auto_advance"] = self.auto_advance
        self.update()

    def cycle_filter(self):
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self.prefs["filter"] = self.filter
        self.update_visible()
        if self.i not in self.visible and not self.step(1):
            self.step(-1)
        self.update()

    def switch_view(self):
        self.set_view("grid" if self.view == "filmstrip" else "filmstrip")

    def set_view(self, view):
        self.view = view
        self.prefs["view"] = view
        self.zoom = self.peek = False
        self.update()

    def open_in_filmstrip(self, j):
        self.set_view("filmstrip")
        self.go_to(j)

    def toggle_zoom(self, at=None):
        """100% zoom at a point on screen (the mouse), or at the photo's centre."""
        if self.view != "filmstrip":
            return
        self.zoom = not self.zoom
        if self.zoom:
            r = self.photo_rect
            if at is not None and r.contains(at):
                self.zoom_center = [(at.x() - r.left()) / r.width(), (at.y() - r.top()) / r.height()]
            elif at is None:
                self.zoom_center = [0.5, 0.5]
            self.images.request_full(self.i)
        self.update()

    def set_peek(self, on):
        if self.view != "filmstrip" or on == self.peek:
            return
        self.peek = on
        if on:
            self.images.request_full(self.i)
        self.update()

    def pan(self, dx, dy):
        """Move the zoomed view by (dx, dy) screen pixels."""
        if not (self.zoom or self.peek):
            return
        w, h = self.images.full_size(self.i) or (6000, 4000)
        ratio = self.devicePixelRatioF()
        self.zoom_center = [min(1, max(0, self.zoom_center[0] + dx * ratio / w)),
                            min(1, max(0, self.zoom_center[1] + dy * ratio / h))]
        self.update()

    def grid_move(self, dx, dy):
        if not self.visible:
            return
        pos = self.visible_position() if self.i in self.visible else max(0, self.visible_position() - 1)
        pos = max(0, min(len(self.visible) - 1, pos + dx + dy * self.grid_columns()))
        self.go_to(self.visible[pos])

    def activate(self):
        """Right-stick click / Enter: in Grid, open the photo; in Filmstrip, switch to Grid."""
        if self.view == "grid":
            self.open_in_filmstrip(self.i)
        else:
            self.switch_view()

    # ---------- saving while the drive is unplugged ----------

    def retry_save(self):
        if self.shoot.save():
            self.retry.stop()
            self.update()

    # ---------- input ----------

    def keyPressEvent(self, e):
        k, held = e.key(), e.isAutoRepeat()
        grid = self.view == "grid"
        if not self.photos:
            if k == Qt.Key_Escape:
                self.home_requested.emit()
            return
        if k in (Qt.Key_Right, Qt.Key_Left):
            d = 1 if k == Qt.Key_Right else -1
            if grid:
                self.grid_move(d, 0)
            else:
                self.navigate(d, held)
        elif k in (Qt.Key_Up, Qt.Key_Down) and grid:
            self.grid_move(0, 1 if k == Qt.Key_Down else -1)
        elif k in (Qt.Key_PageUp, Qt.Key_PageDown) and grid:
            rows = max(1, self.height() // GRID_CELL[1] - 1)
            self.grid_move(0, rows if k == Qt.Key_PageDown else -rows)
        elif k in (Qt.Key_Home, Qt.Key_End) and self.visible:
            self.go_to(self.visible[0 if k == Qt.Key_Home else -1])
        elif k == Qt.Key_A:
            self.mark(PICK)
        elif k == Qt.Key_S:
            self.mark(REJECT)
        elif k == Qt.Key_D:
            self.mark(None)
        elif k == Qt.Key_T:
            self.toggle_auto_advance()
        elif k == Qt.Key_R:
            self.cycle_filter()
        elif k == Qt.Key_Z:
            self.toggle_zoom(self.mapFromGlobal(QCursor.pos()))
        elif k == Qt.Key_Tab:
            self.switch_view()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and grid:
            self.open_in_filmstrip(self.i)
        elif k in (Qt.Key_Question, Qt.Key_Slash, Qt.Key_F1):
            self.help = not self.help
            self.update()
        elif k == Qt.Key_Escape:
            if self.help or self.zoom:
                self.help = self.zoom = False
                self.update()
            else:
                self.home_requested.emit()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if not e.isAutoRepeat() and e.key() in (Qt.Key_Right, Qt.Key_Left):
            self.land()

    def focusNextPrevChild(self, _):
        return False  # let Tab reach keyPressEvent

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if self.view == "grid":
            j = self.cell_at(pos)
            if j is not None:
                self.go_to(j)
        elif self.zoom and e.button() == Qt.LeftButton:
            self.drag = e.position()
        elif e.button() == Qt.LeftButton and pos.y() > self.height() - STRIP_HEIGHT:
            j = self.strip_cell_at(pos)
            if j is not None:
                self.go_to(j)

    def mouseMoveEvent(self, e):
        if self.drag is not None and self.zoom:
            d = e.position() - self.drag
            self.drag = e.position()
            self.pan(-d.x(), -d.y())

    def mouseReleaseEvent(self, e):
        self.drag = None

    def mouseDoubleClickEvent(self, e):
        pos = e.position().toPoint()
        if self.view == "grid":
            j = self.cell_at(pos)
            if j is not None:
                self.open_in_filmstrip(j)
        elif pos.y() < self.height() - STRIP_HEIGHT:
            self.toggle_zoom(pos)

    def wheelEvent(self, e):
        if self.view == "grid":
            self.grid_scroll = max(0, self.grid_scroll - e.angleDelta().y())
            self.update()

    def on_image_loaded(self, i):
        if abs(i - self.i) <= 1 or i == self.i:
            self.update()

    # ---------- painting ----------

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), BACKGROUND)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.thumbs.next_frame()
        if not self.photos:
            p.setPen(GREY)
            p.drawText(self.rect(), Qt.AlignCenter, "No JPGs left to cull in this Shoot.  Esc = home")
            return
        if self.view == "grid":
            self.paint_grid(p)
        else:
            self.paint_filmstrip(p)
        self.paint_info(p)
        if self.shoot.unsaved:
            self.paint_banner(p, "The Library drive is disconnected. Your marks are kept and will "
                                 "be saved when it's back.")
        elif not self.visible:
            self.paint_banner(p, f"No photos match the filter \"{self.filter}\". Press R to change it.")
        if self.help:
            self.paint_help(p)

    def paint_filmstrip(self, p):
        area = self.rect().adjusted(0, INFO_HEIGHT, 0, -STRIP_HEIGHT)
        if self.zoom or self.peek:
            self.paint_zoomed(p, area)
        else:
            self.paint_fitted(p, area)
        self.paint_badge(p, area, self.current.mark, big=True)
        self.paint_strip(p)

    def best_image(self, i):
        """The sharp screen-sized photo if decoded, else its small placeholder."""
        img = None if self.flying else self.images.get(i)
        return (img, True) if img is not None else (self.thumbs.get(i), False)

    def paint_fitted(self, p, area):
        img, sharp = self.best_image(self.i)
        if img is None:
            p.setPen(GREY)
            p.drawText(area, Qt.AlignCenter, "decoding…")
            return
        size = img.size().scaled(area.size(), Qt.KeepAspectRatio)
        r = QRect(0, 0, size.width(), size.height())
        r.moveCenter(area.center())
        p.drawImage(r, img)
        self.photo_rect = r

    def paint_zoomed(self, p, area):
        full = self.images.get_full(self.i)
        if full is not None:
            src, scale = full, 1.0
        else:  # upscale what we have until the full-size decode lands
            src = self.best_image(self.i)[0]
            if src is None:
                return
            full_w, _ = self.images.full_size(self.i) or (src.width() * 4, 0)
            scale = src.width() / full_w
        ratio = self.devicePixelRatioF()  # 100% means one photo pixel per screen pixel
        w, h = area.width() * ratio * scale, area.height() * ratio * scale
        cx, cy = self.zoom_center[0] * src.width(), self.zoom_center[1] * src.height()
        p.drawImage(QRectF(area), src, QRectF(cx - w / 2, cy - h / 2, w, h))
        if full is None:
            p.setPen(GREY)
            p.drawText(area.adjusted(12, 8, 0, 0), Qt.AlignLeft | Qt.AlignTop, "100% loading…")

    def strip_layout(self):
        """(rect, index) for each thumbnail in the filmstrip, centred on the current photo."""
        tw, th = STRIP_THUMB
        n = self.width() // (tw + 6) + 2
        pos = self.visible_position()
        x0 = self.width() // 2 - tw // 2 - (n // 2) * (tw + 6)
        cells = []
        for k in range(n):
            vp = pos - n // 2 + k
            if 0 <= vp < len(self.visible):
                cells.append((QRect(x0 + k * (tw + 6), self.height() - STRIP_HEIGHT + 15, tw, th),
                              self.visible[vp]))
        return cells

    def strip_cell_at(self, pos):
        return next((j for r, j in self.strip_layout() if r.contains(pos)), None)

    def paint_strip(self, p):
        for r, j in self.strip_layout():
            self.paint_thumb(p, r, j, selected=j == self.i, border=True)

    def paint_thumb(self, p, r, j, selected, border=False):
        img = self.thumbs.get(j)
        if img is not None:  # keep the aspect ratio: portraits are pillarboxed
            size = img.size().scaled(r.size(), Qt.KeepAspectRatio)
            ir = QRect(0, 0, size.width(), size.height())
            ir.moveCenter(r.center())
            p.drawImage(ir, img)
        mark = self.photos[j].mark
        if mark == REJECT:
            p.fillRect(r, QColor(0, 0, 0, 150))
        p.setBrush(Qt.NoBrush)
        if selected:
            p.setPen(QPen(Qt.white, 4))
            p.drawRect(r.adjusted(-3, -3, 3, 3))
        elif border:
            p.setPen(QPen(GREEN if mark == PICK else RED if mark else QColor(60, 60, 60), 2))
            p.drawRect(r)
        if not border:
            self.paint_badge(p, r, mark)

    def grid_columns(self):
        return max(1, self.width() // GRID_CELL[0])

    def paint_grid(self, p):
        cols = self.grid_columns()
        cw, ch = self.width() // cols, GRID_CELL[1]
        top_margin = INFO_HEIGHT + 10
        row = max(0, self.visible_position() - (self.i not in self.visible)) // cols
        top, bottom = row * ch, (row + 1) * ch
        if top < self.grid_scroll:  # keep the selected row on screen
            self.grid_scroll = top
        elif bottom > self.grid_scroll + self.height() - top_margin:
            self.grid_scroll = bottom - self.height() + top_margin
        self.grid_cells = []
        first = self.grid_scroll // ch * cols
        last = min(len(self.visible), (self.grid_scroll + self.height()) // ch * cols + cols)
        for k in range(first, last):
            j = self.visible[k]
            r = QRect((k % cols) * cw + 8, (k // cols) * ch - self.grid_scroll + top_margin, cw - 16, ch - 16)
            self.grid_cells.append((r, j))
            self.paint_thumb(p, r, j, selected=j == self.i)

    def cell_at(self, pos):
        return next((j for r, j in self.grid_cells if r.contains(pos)), None)

    def paint_badge(self, p, r, mark, big=False):
        if not mark:
            return
        size = 34 if big else 20
        badge = QRect(r.right() - size - 8, r.top() + 8, size, size)
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN if mark == PICK else RED)
        p.drawEllipse(badge)
        p.setPen(Qt.white)
        f = QFont("Segoe UI", 16 if big else 10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(badge, Qt.AlignCenter, "✓" if mark == PICK else "✕")

    def paint_info(self, p):
        c = self.shoot.counts()
        photo = self.current
        mark = {PICK: "PICK", REJECT: "REJECT"}.get(photo.mark, "unmarked")
        parts = [
            f"{photo.name}",
            f"{self.i + 1} / {len(self.photos)}",
            mark,
            f"picks {c.picks} · rejects {c.rejects} · unmarked {c.unmarked}",
            f"filter: {self.filter}" + (f" ({len(self.visible)})" if self.filter != "all" else ""),
            f"auto-advance: {'on' if self.auto_advance else 'off'}",
            "? = keys",
        ]
        p.fillRect(QRect(0, 0, self.width(), INFO_HEIGHT), QColor(0, 0, 0))
        p.setFont(QFont("Segoe UI", 10))
        x = 12
        for k, text in enumerate(parts):
            colour = {PICK: GREEN, REJECT: RED}.get(photo.mark, QColor(220, 220, 220)) if k == 2 \
                else QColor(220, 220, 220)
            p.setPen(colour)
            p.drawText(QRect(x, 0, 2000, INFO_HEIGHT), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += p.fontMetrics().horizontalAdvance(text) + 28

    def paint_banner(self, p, text):
        r = QRect(0, INFO_HEIGHT, self.width(), 34)
        p.fillRect(r, QColor(160, 90, 20, 230))
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(r, Qt.AlignCenter, text)

    def paint_help(self, p):
        line = 26
        r = QRect(0, 0, 760, 40 + line * len(HELP))
        r.moveCenter(self.rect().center())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 225))
        p.drawRoundedRect(r, 12, 12)
        for k, (keys, what) in enumerate(HELP):
            y = r.top() + 24 + line * k
            f = QFont("Segoe UI", 11)
            f.setBold(not what)  # section headings
            p.setFont(f)
            p.setPen(QColor(255, 210, 0))
            p.drawText(QPointF(r.left() + 28, y + 16), keys)
            p.setPen(Qt.white)
            p.drawText(QPointF(r.left() + 220, y + 16), what)
