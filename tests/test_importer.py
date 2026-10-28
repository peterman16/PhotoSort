from datetime import date

from photosort import importer
from photosort.shoot import Shoot
from photosort.thumbs import thumb_path

from .conftest import make_jpg


def make_card(tmp_path):
    card = tmp_path / "card" / "DCIM"
    make_jpg(card / "100CANON" / "IMG_0001.JPG", "2025:09:20 09:00:00")
    make_jpg(card / "100CANON" / "IMG_0002.JPG", "2025:09:20 09:01:00")
    make_jpg(card / "100CANON" / "IMG_0003.JPG", "2025:09:21 08:00:00")
    return card


def test_scan_groups_by_capture_day_and_flags_already_imported(tmp_path):
    card = importer.scan_card(make_card(tmp_path), known_keys={("img_0001.jpg", "2025-09-20T09:00:00")})
    days = importer.group_by_day(card.photos)
    assert {d: len(ps) for d, ps in days.items()} == {date(2025, 9, 20): 2, date(2025, 9, 21): 1}
    assert [p.already_imported for p in card.photos] == [True, False, False]
    assert card.photos[0].source.endswith(r"DCIM\100CANON\IMG_0001.JPG")


def test_days_become_one_shoot_named_by_the_first_day_unless_split(tmp_path):
    card = importer.scan_card(make_card(tmp_path), set())
    days = importer.group_by_day(card.photos)
    root = tmp_path / "G"

    [(dest, photos)] = importer.plan(root, days, "Mount Baker")
    assert dest.folder == root / "2025" / "2025_09_20 Mount Baker" and len(photos) == 3

    split = importer.plan(root, days, split_days=True)
    assert [d.folder.name for d, _ in split] == ["2025_09_20", "2025_09_21"]


def test_import_copies_jpgs_records_the_card_and_builds_thumbnails(tmp_path):
    card = importer.scan_card(make_card(tmp_path), set())
    [(dest, photos)] = importer.plan(tmp_path / "G", importer.group_by_day(card.photos))

    shoot = importer.copy_into(dest, photos, card)

    assert [p.name for p in shoot.photos] == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"]
    assert all(p.card == card.serial and p.source for p in shoot.photos)
    assert thumb_path(dest.folder, "IMG_0001.JPG").exists()
    assert (tmp_path / "card" / "DCIM" / "100CANON" / "IMG_0001.JPG").exists()  # Card untouched


def test_same_date_joins_the_shoot_unless_it_is_exported(tmp_path):
    root = tmp_path / "G"
    day = date(2025, 9, 20)
    first = importer.destination_for(root, day)
    first.folder.mkdir(parents=True)
    Shoot(first.folder).save()
    assert importer.destination_for(root, day) == importer.Destination(first.folder, joins=True)

    shoot = Shoot.read(first.folder)
    shoot.exported_at = "2025-09-22T10:00:00"
    shoot.save()
    assert importer.destination_for(root, day).folder.name == "2025_09_20_2"


def test_a_clashing_filename_from_another_camera_gets_a_camera_tag(tmp_path):
    card_dir = tmp_path / "card" / "DCIM"
    make_jpg(card_dir / "100CANON" / "IMG_3988.JPG", "2025:05:26 10:00:00", model="Canon EOS R8")
    make_jpg(card_dir / "101CANON" / "IMG_3988.JPG", "2025:05:26 13:42:54", model="Canon EOS 70D")
    card = importer.scan_card(card_dir, set())
    [(dest, photos)] = importer.plan(tmp_path / "G", importer.group_by_day(card.photos))

    shoot = importer.copy_into(dest, photos, card)

    assert [p.name for p in shoot.photos] == ["IMG_3988.JPG", "IMG_3988_70D.JPG"]
    assert shoot.photos[1].original == "IMG_3988.JPG"
    assert {p.key for p in shoot.photos} == {p.key for p in card.photos}


def test_reimporting_the_same_card_adds_nothing(tmp_path):
    card = importer.scan_card(make_card(tmp_path), set())
    [(dest, photos)] = importer.plan(tmp_path / "G", importer.group_by_day(card.photos))
    importer.copy_into(dest, photos, card)
    shoot = importer.copy_into(dest, photos, card)
    assert len(shoot.photos) == 3
