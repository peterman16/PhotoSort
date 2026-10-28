import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from photosort.appdata import Prefs  # noqa: E402
from photosort.shoot import PICK, REJECT, Shoot  # noqa: E402
from photosort.ui.cull import CullView  # noqa: E402

from .conftest import capture_time, make_jpg  # noqa: E402


@pytest.fixture
def view(tmp_path):
    QApplication.instance() or QApplication([])
    folder = tmp_path / "shoot"
    for n in range(5):
        make_jpg(folder / f"IMG_{n}.JPG", capture_time(n))
    v = CullView(Shoot.open(folder), Prefs(), (800, 600))
    yield v
    v.close_shoot()


def test_a_and_s_toggle_and_d_unmarks(view):
    view.mark(PICK)
    assert view.current.mark == PICK
    view.mark(PICK)
    assert view.current.mark is None
    view.mark(REJECT)
    view.mark(None)
    assert view.current.mark is None


def test_auto_advance_moves_on_after_marking_but_not_after_clearing(view):
    view.toggle_auto_advance()
    view.mark(PICK)
    assert view.i == 1
    view.navigate(-1)
    view.mark(PICK)  # clears the Pick
    assert view.i == 0


def test_filter_skips_hidden_photos(view):
    view.mark(REJECT)
    view.navigate(1)
    view.mark(REJECT)
    view.cycle_filter()  # hide rejects
    assert view.i == 2
    view.navigate(-1)
    assert view.i == 2  # nothing visible before it


def test_marks_reach_the_state_file(view):
    view.mark(PICK)
    assert Shoot.read(view.shoot.folder).photos[0].mark == PICK
