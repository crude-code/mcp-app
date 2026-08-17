"""triage.py's room-root contract: every path it records is relative to the
room root, so `documents[].path` and `provenance.source_file` stay room-relative
all the way into the extraction. VDR exports almost always wrap their contents
in one top-level folder, and passing the unzip destination used to make that
folder segment 1 of every path — folders rendered as
"Asset 53622 - 2026-8-12-429efe9d.../01~ Overview" in the viewer, and two runs
of the same room disagreed on provenance."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parent.parent
           / "skills" / "dataroom-extract" / "triage.py")

spec = importlib.util.spec_from_file_location("triage", _SCRIPT)
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


def _room(base: Path, *files: str) -> Path:
    for rel in files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"contents of {rel}\n")
    return base


def test_descends_past_a_single_wrapper_folder(tmp_path):
    _room(tmp_path, "Asset 53622 - 2026-8-12-429efe9d/01~ Overview/Teaser.pdf",
          "Asset 53622 - 2026-8-12-429efe9d/02~ Finance/Revenue/stub.pdf")
    assert triage.room_root(tmp_path).name == "Asset 53622 - 2026-8-12-429efe9d"


def test_stops_at_the_first_folder_with_real_content(tmp_path):
    _room(tmp_path, "01~ Overview/Teaser.pdf", "02~ Finance/stub.pdf")
    assert triage.room_root(tmp_path) == tmp_path


def test_a_root_level_file_pins_the_root(tmp_path):
    """A room whose teaser sits beside its folders is already the root."""
    _room(tmp_path, "Teaser.pdf", "01~ Overview/deck.pdf")
    assert triage.room_root(tmp_path) == tmp_path


def test_a_lone_content_folder_keeps_its_name(tmp_path):
    """The case that makes blind descent wrong: the room's only top-level entry
    is a real folder of documents, not a wrapper. Descending would flatten
    "Check Stubs/a.pdf" to "a.pdf" and label the group "(root)"."""
    _room(tmp_path, "Check Stubs/a.pdf", "Check Stubs/b.pdf")
    assert triage.room_root(tmp_path) == tmp_path


def test_double_wrapped_zip_unwraps_all_the_way(tmp_path):
    _room(tmp_path, "Asset 53622/Asset 53622/01~ Overview/t.pdf",
          "Asset 53622/Asset 53622/02~ Finance/s.pdf")
    assert triage.room_root(tmp_path).relative_to(tmp_path).as_posix() == (
        "Asset 53622/Asset 53622")


def test_zip_noise_does_not_block_the_descent(tmp_path):
    _room(tmp_path, "__MACOSX/._Asset", ".DS_Store",
          "Asset/01~ Overview/t.pdf", "Asset/02~ Finance/s.pdf")
    assert triage.room_root(tmp_path).name == "Asset"


def test_prior_triage_output_does_not_block_a_rerun(tmp_path):
    _room(tmp_path, "Asset/01~ Overview/t.pdf", "Asset/02~ Finance/s.pdf",
          "Asset/_triage/manifest.json", "_triage/manifest.json")
    assert triage.room_root(tmp_path).name == "Asset"


def test_nesting_is_depth_capped(tmp_path):
    _room(tmp_path, "a/b/c/d/e/f/deep.pdf")
    root = triage.room_root(tmp_path)
    assert root.relative_to(tmp_path).as_posix() == "a/b/c/d"


def test_manifest_paths_are_room_relative_end_to_end(tmp_path):
    _room(tmp_path, "Asset 53622/01~ Overview/Teaser.pdf",
          "Asset 53622/02~ Finance/Revenue/stub.pdf")
    proc = subprocess.run([sys.executable, str(_SCRIPT), str(tmp_path)],
                          capture_output=True, text=True, check=True)
    assert "room root: Asset 53622/" in proc.stdout

    manifest = json.loads(
        (tmp_path / "Asset 53622" / "_triage" / "manifest.json").read_text())
    assert manifest["dataroom_root"] == "Asset 53622"
    assert sorted(e["path"] for e in manifest["files"]) == [
        "01~ Overview/Teaser.pdf", "02~ Finance/Revenue/stub.pdf"]
