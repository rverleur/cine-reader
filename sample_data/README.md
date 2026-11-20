# Optional local recordings

Large camera recordings are not committed or packaged. You can keep a private
recording named `TrimmedCine.cine` here to enable `test_cine_smoke.py`; this file
is ignored by Git. The maintained examples let you configure a path to your own
recording, and the synthetic writing/processing examples generate their inputs.

For the separate 14-file reference corpus, set `CINE_TEST_CORPUS` as described in
[the development guide](../docs/DEVELOPMENT.md). Neither the original recordings
nor frame exports belong in a release archive.
