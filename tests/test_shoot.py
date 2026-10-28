from photosort import shoot as shoot_module
from photosort.files import read_json
from photosort.shoot import PICK, REJECT, STATE_FILE, Shoot

from .conftest import capture_time, make_jpg


def test_opening_a_folder_of_jpgs_makes_it_a_shoot_in_capture_order(tmp_path):
    folder = tmp_path / "2025_11_12"
    make_jpg(folder / "IMG_0002.JPG", capture_time(1))
    make_jpg(folder / "IMG_0001.JPG", capture_time(2))  # filename order differs from capture order

    shoot = Shoot.open(folder)

    assert [p.name for p in shoot.photos] == ["IMG_0002.JPG", "IMG_0001.JPG"]
    assert shoot.photos[0].camera == "Canon EOS R8"
    assert (folder / STATE_FILE).exists()


def test_marks_save_immediately_and_survive_reopening(tmp_path):
    folder = tmp_path / "shoot"
    make_jpg(folder / "IMG_0001.JPG", capture_time(1))
    make_jpg(folder / "IMG_0002.JPG", capture_time(2))
    shoot = Shoot.open(folder)

    shoot.set_mark(shoot.photos[0], PICK)
    shoot.set_mark(shoot.photos[1], REJECT)

    again = Shoot.open(folder)
    assert [p.mark for p in again.photos] == [PICK, REJECT]
    assert again.counts().unmarked == 0


def test_saving_twice_overwrites_the_hidden_state_file(tmp_path):
    folder = tmp_path / "shoot"
    make_jpg(folder / "IMG_0001.JPG")
    shoot = Shoot.open(folder)
    shoot.set_mark(shoot.photos[0], PICK)
    shoot.set_mark(shoot.photos[0], None)
    assert read_json(folder / STATE_FILE)["photos"][0].get("mark") is None


def test_new_jpgs_are_added_on_reopen_and_missing_ones_are_not_culled(tmp_path):
    folder = tmp_path / "shoot"
    make_jpg(folder / "IMG_0001.JPG", capture_time(1))
    Shoot.open(folder)
    make_jpg(folder / "IMG_0002.JPG", capture_time(2))
    (folder / "IMG_0001.JPG").unlink()

    shoot = Shoot.open(folder)

    assert len(shoot.photos) == 2  # the record of IMG_0001 is kept
    assert [p.name for p in shoot.cull_photos()] == ["IMG_0002.JPG"]


def test_marks_made_while_the_drive_is_unplugged_are_kept_and_applied_later(tmp_path, monkeypatch):
    folder = tmp_path / "shoot"
    make_jpg(folder / "IMG_0001.JPG")
    shoot = Shoot.open(folder)

    real_write_json = shoot_module.write_json

    def unplugged(path, *args, **kwargs):
        if folder in path.parents:
            raise OSError("drive gone")
        real_write_json(path, *args, **kwargs)
    monkeypatch.setattr(shoot_module, "write_json", unplugged)
    assert shoot.set_mark(shoot.photos[0], PICK) is False
    assert shoot.unsaved and shoot.backup_path().exists()
    monkeypatch.setattr(shoot_module, "write_json", real_write_json)

    # The app closes before the drive comes back; the next open applies the backup.
    again = Shoot.open(folder)
    assert again.photos[0].mark == PICK
    assert not again.backup_path().exists()
