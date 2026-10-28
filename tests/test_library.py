from photosort.appdata import Prefs
from photosort.library import Library
from photosort.shoot import PICK, Shoot

from .conftest import capture_time, make_jpg


def make_library(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    prefs = Prefs()
    prefs["library_root"] = str(root)
    return Library(prefs), root


def test_rebuild_finds_shoots_at_the_root_and_in_year_folders(tmp_path):
    library, root = make_library(tmp_path)
    Shoot.open(make_jpg(root / "2025_05_29" / "IMG_1.JPG").parent)
    Shoot.open(make_jpg(root / "2025" / "2025_11_12" / "IMG_2.JPG").parent)
    make_jpg(root / "2025" / "not_a_shoot" / "IMG_3.JPG")

    library.rebuild()

    assert sorted(e["name"] for e, _ in library.shoots()) == ["2025_05_29", "2025_11_12"]


def test_remember_updates_the_summary_without_duplicating(tmp_path):
    library, root = make_library(tmp_path)
    shoot = Shoot.open(make_jpg(root / "2025" / "2025_11_12" / "IMG_1.JPG").parent)
    library.remember(shoot)
    shoot.set_mark(shoot.photos[0], PICK)
    library.remember(shoot)

    [(entry, folder)] = library.shoots()
    assert entry["summary"].startswith("1 photos · 1 picks · 0 unmarked")
    assert folder == shoot.folder


def test_unplugged_shoots_stay_listed_as_offline(tmp_path):
    library, root = make_library(tmp_path)
    shoot = Shoot.open(make_jpg(root / "2025" / "2025_11_12" / "IMG_1.JPG").parent)
    library.remember(shoot)
    entry = library.entries[0]
    entry["path"] = str(tmp_path / "missing" / "2025_11_12")
    entry["serial"] = "0000-0000"

    library.rebuild()

    offline = [e for e, folder in library.shoots() if folder is None]
    assert [e["name"] for e in offline] == ["2025_11_12"]


def test_known_photo_keys_use_card_filename_and_capture_time(tmp_path):
    library, root = make_library(tmp_path)
    shoot = Shoot.open(make_jpg(root / "2025" / "2025_11_12" / "IMG_1.JPG", capture_time(5)).parent)
    library.remember(shoot)
    assert library.known_photo_keys() == {("img_1.jpg", "2025-11-12T10:05:00")}
