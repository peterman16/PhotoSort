import pytest

from photosort import exporter, importer
from photosort.shoot import PICK, REJECT, Shoot
from photosort.thumbs import thumbs_dir

from .conftest import make_jpg, make_raw


@pytest.fixture
def imported(tmp_path, monkeypatch):
    """A Shoot imported from a fake Card with three JPG+CR3 pairs: Pick, Reject, Pick-without-RAW."""
    card_dir = tmp_path / "card" / "DCIM"
    for n, minute in ((1, 0), (2, 1), (3, 2)):
        make_jpg(card_dir / "100CANON" / f"IMG_000{n}.JPG", f"2025:09:20 09:0{minute}:00")
    make_raw(card_dir / "100CANON" / "IMG_0001.CR3", b"raw one")
    make_raw(card_dir / "100CANON" / "IMG_0002.CR3", b"raw two")
    card = importer.scan_card(card_dir, set())
    [(dest, photos)] = importer.plan(tmp_path / "G", importer.group_by_day(card.photos), "Mount Baker")
    shoot = importer.copy_into(dest, photos, card)
    shoot.set_mark(shoot.photos[0], PICK)
    shoot.set_mark(shoot.photos[1], REJECT)
    shoot.set_mark(shoot.photos[2], PICK)

    recycled = []
    monkeypatch.setattr(exporter, "send2trash", lambda paths: [recycled.append(p) for p in paths])
    return shoot, card_dir, recycled


def test_picks_raws_are_copied_and_verified(imported):
    shoot, card_dir, _ = imported
    items = exporter.plan_export(shoot, exporter.RawFinder())
    assert [(i.photo.name, i.target, i.problem) for i in items] == [
        ("IMG_0001.JPG", "IMG_0001.CR3", None),
        ("IMG_0003.JPG", "IMG_0003.JPG", "no RAW found"),
    ]

    result = exporter.copy_raws(shoot, items)

    assert result.copied == 1 and not result.failed
    assert (shoot.folder / "IMG_0001.CR3").read_bytes() == b"raw one"
    assert not (shoot.folder / "IMG_0002.CR3").exists()  # a Reject's RAW stays on the Card
    assert Shoot.read(shoot.folder).photos[0].raw_hash == exporter.file_hash(card_dir / "100CANON" / "IMG_0001.CR3")


def test_rerunning_skips_raws_that_already_verify(imported):
    shoot, _, _ = imported
    items = exporter.plan_export(shoot, exporter.RawFinder())
    exporter.copy_raws(shoot, items)
    again = exporter.copy_raws(shoot, exporter.plan_export(shoot, exporter.RawFinder()))
    assert (again.copied, again.already_done) == (0, 1)


def test_finishing_recycles_verified_picks_and_rejects_but_keeps_a_pick_without_raw(imported):
    shoot, card_dir, recycled = imported
    items = exporter.plan_export(shoot, exporter.RawFinder())
    result = exporter.copy_raws(shoot, items)

    exporter.finish(shoot, items, result, remove_jpgs=True, renaming=False)

    assert sorted(p.rsplit("\\", 1)[-1] for p in recycled) == ["IMG_0001.JPG", "IMG_0002.JPG"]
    assert shoot.exported and not thumbs_dir(shoot.folder).exists()
    assert sorted(p.name for p in card_dir.joinpath("100CANON").iterdir()) == [
        "IMG_0001.CR3", "IMG_0001.JPG", "IMG_0002.CR3", "IMG_0002.JPG", "IMG_0003.JPG"]  # Card untouched


def test_batch_rename_numbers_picks_in_capture_order(imported):
    shoot, _, _ = imported
    pattern = exporter.default_pattern(shoot)
    assert pattern == "2025_09_20_Mount-Baker_{n}"
    items = exporter.plan_export(shoot, exporter.RawFinder(), pattern)
    result = exporter.copy_raws(shoot, items)
    exporter.finish(shoot, items, result, remove_jpgs=False, renaming=True)

    assert (shoot.folder / "2025_09_20_Mount-Baker_001.CR3").exists()
    assert (shoot.folder / "2025_09_20_Mount-Baker_002.JPG").exists()  # Pick without RAW, same sequence
    record = Shoot.read(shoot.folder)
    assert record.photos[0].raw == "2025_09_20_Mount-Baker_001.CR3"
    assert record.photos[2].original == "IMG_0003.JPG"


def test_a_rename_pattern_cannot_leave_the_shoot_folder():
    assert exporter.renamed("..\\..\\Mount Baker_{n}", 1, 5) == "-..-Mount Baker_001"
    assert exporter.renamed("a/b:c_{n}", 12, 5) == "a-b-c_012"


def test_a_missing_card_waits_unless_raws_are_located(imported, tmp_path):
    shoot, card_dir, _ = imported
    for photo in shoot.photos:
        photo.card = "0000-0000"  # a Card that isn't inserted
    finder = exporter.RawFinder()
    assert finder.missing_cards(shoot, [shoot.photos[0]]) == ["card"]
    assert exporter.plan_export(shoot, finder)[0].problem == "its card isn't inserted"

    finder.locate(card_dir)
    assert exporter.plan_export(shoot, finder)[0].raw == card_dir / "100CANON" / "IMG_0001.CR3"


def test_a_different_file_with_the_target_name_is_never_overwritten(imported):
    shoot, _, _ = imported
    (shoot.folder / "IMG_0001.CR3").write_bytes(b"something else")
    result = exporter.copy_raws(shoot, exporter.plan_export(shoot, exporter.RawFinder()))
    assert result.failed and (shoot.folder / "IMG_0001.CR3").read_bytes() == b"something else"


def test_a_raw_found_through_overlapping_folders_counts_once(imported):
    shoot, card_dir, _ = imported
    for photo in shoot.photos:
        photo.card = photo.source = None  # opened as a folder: no recorded Card
    finder = exporter.RawFinder()
    finder.locate(card_dir.parent)
    finder.locate(card_dir)  # the same RAWs again, by another route

    item = exporter.plan_export(shoot, finder)[0]
    assert item.raw is not None and item.problem is None


def test_an_export_that_copies_nothing_is_not_finished(imported):
    shoot, card_dir, recycled = imported
    for raw in card_dir.joinpath("100CANON").glob("*.CR3"):
        raw.unlink()
    items = exporter.plan_export(shoot, exporter.RawFinder())
    result = exporter.copy_raws(shoot, items)

    assert not result.finished
    exporter.finish(shoot, items, result, remove_jpgs=True, renaming=False)
    assert not shoot.exported and not recycled and thumbs_dir(shoot.folder).exists()
