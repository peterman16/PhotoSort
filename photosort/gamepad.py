"""Xbox controller support through XInput (part of Windows), polled on a timer.

Always on: it works whenever a controller is connected and PhotoSort's window is focused
(Windows only sends controller input to the focused window). Fixed mapping, wayfinder ticket 009:

  A / B / X            Pick / Reject / Unmark
  D-pad, left stick    previous / next (holding flies past with placeholders); Grid: move
  Y                    toggle 100% zoom at the centre
  hold RT              100% zoom while held (focus peek)
  right stick          pan while zoomed
  View / Menu          cycle filter / toggle auto-advance
  right-stick click    switch Filmstrip / Grid; in Grid, open the selected photo
LB / RB and the Xbox button are left alone. No rumble.
"""
import ctypes
import logging
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from .shoot import PICK, REJECT

log = logging.getLogger(__name__)

DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
MENU, VIEW, RIGHT_THUMB = 0x0010, 0x0020, 0x0080
BUTTON_A, BUTTON_B, BUTTON_X, BUTTON_Y = 0x1000, 0x2000, 0x4000, 0x8000

POLL_MS = 16
RESCAN_S = 2.0            # how often to look for a newly connected controller
STICK_DIRECTION = 16000   # left stick past about half-way counts as a direction
STICK_DEADZONE = 8689     # Microsoft's recommended right-stick deadzone
TRIGGER_DOWN = 100        # of 255
PAN_SPEED = 30            # screen pixels per poll at full right-stick tilt
REPEAT_DELAY_S = 0.4      # holding a direction: wait this long, then repeat
REPEAT_EVERY_S = 0.08


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def load_xinput():
    for name in ("xinput1_4", "xinput9_1_0"):
        try:
            return ctypes.windll.LoadLibrary(name)
        except OSError:
            pass
    return None


class Gamepad(QObject):
    """Polls the first connected controller and calls actions on the current Cull view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.xinput = load_xinput()
        self.target = None         # the CullView, or None on the home screen
        self.slot = None           # which of XInput's 4 controller slots is in use
        self.last_scan = 0.0
        self.buttons = 0
        self.direction = None      # (dx, dy) currently held, from D-pad or left stick
        self.next_repeat = 0.0
        self.repeating = False
        self.timer = QTimer(self, interval=POLL_MS, timeout=self.poll)
        if self.xinput is None:
            log.info("XInput not available; controller support is off")
        else:
            self.timer.start()

    def set_target(self, view):
        self.target = view
        self.buttons, self.direction = 0, None

    # ---------- reading the controller ----------

    def read(self, slot):
        state = XINPUT_STATE()
        if self.xinput.XInputGetState(slot, ctypes.byref(state)) != 0:
            return None
        return state.Gamepad

    def find_controller(self):
        now = time.monotonic()
        if now - self.last_scan < RESCAN_S:
            return
        self.last_scan = now
        for slot in range(4):
            if self.read(slot) is not None:
                self.slot = slot
                log.info("Controller connected in slot %d", slot)
                return

    def poll(self):
        if self.slot is None:
            self.find_controller()
            return
        pad = self.read(self.slot)
        if pad is None:
            log.info("Controller disconnected")
            self.slot = None
            return
        if self.target is None or QGuiApplication.applicationState() != Qt.ApplicationActive:
            self.buttons, self.direction = pad.wButtons, None
            return
        self.handle(pad)

    # ---------- mapping ----------

    def handle(self, pad):
        view = self.target
        pressed = pad.wButtons & ~self.buttons
        self.buttons = pad.wButtons
        actions = {
            BUTTON_A: lambda: view.mark(PICK),
            BUTTON_B: lambda: view.mark(REJECT),
            BUTTON_X: lambda: view.mark(None),
            BUTTON_Y: lambda: view.toggle_zoom(),
            VIEW: view.cycle_filter,
            MENU: view.toggle_auto_advance,
            RIGHT_THUMB: view.activate,
        }
        for button, action in actions.items():
            if pressed & button:
                action()

        view.set_peek(pad.bRightTrigger > TRIGGER_DOWN)
        rx, ry = pad.sThumbRX, pad.sThumbRY
        if abs(rx) > STICK_DEADZONE or abs(ry) > STICK_DEADZONE:
            view.pan(PAN_SPEED * rx / 32768, -PAN_SPEED * ry / 32768)

        self.handle_direction(view, self.direction_of(pad))

    @staticmethod
    def direction_of(pad):
        b = pad.wButtons
        dx = (1 if b & DPAD_RIGHT or pad.sThumbLX > STICK_DIRECTION else 0) - \
             (1 if b & DPAD_LEFT or pad.sThumbLX < -STICK_DIRECTION else 0)
        dy = (1 if b & DPAD_DOWN or pad.sThumbLY < -STICK_DIRECTION else 0) - \
             (1 if b & DPAD_UP or pad.sThumbLY > STICK_DIRECTION else 0)
        return (dx, dy) if dx or dy else None

    def handle_direction(self, view, direction):
        now = time.monotonic()
        if direction != self.direction:
            if self.direction is not None and self.repeating:
                view.land()
            self.direction, self.repeating = direction, False
            if direction is not None:
                self.move(view, direction, held=False)
                self.next_repeat = now + REPEAT_DELAY_S
        elif direction is not None and now >= self.next_repeat:
            self.repeating = True
            self.move(view, direction, held=True)
            self.next_repeat = now + REPEAT_EVERY_S

    @staticmethod
    def move(view, direction, held):
        dx, dy = direction
        if view.view == "grid":
            view.grid_move(dx, dy)
        elif dx:
            view.navigate(dx, held)
