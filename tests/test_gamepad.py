from photosort import gamepad
from photosort.gamepad import XINPUT_GAMEPAD, Gamepad
from photosort.shoot import PICK


class FakeView:
    view = "filmstrip"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args, kwargs))


def pad(buttons=0, lx=0, rt=0):
    return XINPUT_GAMEPAD(wButtons=buttons, sThumbLX=lx, bRightTrigger=rt)


def test_buttons_fire_once_per_press():
    g, view = Gamepad.__new__(Gamepad), FakeView()
    g.buttons, g.direction, g.repeating, g.next_repeat = 0, None, False, 0
    g.target = view
    g.handle(pad(gamepad.BUTTON_A))
    g.handle(pad(gamepad.BUTTON_A))  # still held: no second Pick
    assert [c for c in view.calls if c[0] == "mark"] == [("mark", (PICK,), {})]


def test_holding_right_moves_then_repeats_as_held_and_lands_on_release(monkeypatch):
    g, view = Gamepad.__new__(Gamepad), FakeView()
    g.buttons, g.direction, g.repeating, g.next_repeat = 0, None, False, 0
    g.target = view
    clock = [100.0]
    monkeypatch.setattr(gamepad.time, "monotonic", lambda: clock[0])

    g.handle(pad(lx=30000))
    clock[0] += 0.5
    g.handle(pad(lx=30000))
    g.handle(pad())

    moves = [c for c in view.calls if c[0] in ("navigate", "land")]
    assert moves == [("navigate", (1, False), {}), ("navigate", (1, True), {}), ("land", (), {})]
