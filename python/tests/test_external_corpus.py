"""Opt-in exact comparisons against the pre-refactor reader's camera corpus."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from cine_reader import Cine

REFERENCE = json.loads((Path(__file__).parent / "data/corpus_reference.json").read_text())
CORPUS = os.environ.get("CINE_TEST_CORPUS")


@pytest.mark.skipif(not CORPUS, reason="Set CINE_TEST_CORPUS to the external sample_cines directory")
@pytest.mark.parametrize("reference", REFERENCE, ids=lambda record: record["name"])
def test_camera_frames_match_archived_reader(reference):
    path = Path(CORPUS) / reference["name"]
    assert path.stat().st_size == reference["bytes"]
    with Cine(path) as cine:
        assert cine.total_frames == reference["frames"]
        assert cine.camera_setup.RealBPP == reference["real_bpp"]
        assert cine.image_header.biCompression == reference["compression"]
        assert cine.cfa_code == reference["cfa"]
        for index, expected_hash in reference["hashes"].items():
            cine.load_frame(cine.first_frame_number + int(index))
            assert list(cine.image.shape) == reference["shape"]
            assert hashlib.sha256(cine.image.tobytes()).hexdigest() == expected_hash
