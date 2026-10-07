# RX3 data baseline against SOUND_PRO (2026-10-07)

This is a read-only test of the **already committed** host-cache bridge, before
adding direct deck-side metadata or bounded audio reads. SOUND_PRO was mounted
on the computer; it was not in the deck during this scan. The earlier physical
USB-B paused-track smoke test is recorded in `PRE_GIG_BRIDGE.md` and is not a
new live test.

`python3 scripts/pre_gig.py scan /Volumes/SOUND_PRO --out local/usb-live-baseline-20261007`
parsed 238 export rows. 236 have validated beat grids and PSSI phrase maps;
two (IDs 152 and 233) have usable grids but invalid PSSI and must report phrase
unavailable. The two tracks used in prior physical tests (IDs 150 and 195)
have 916/656 beats and 23/17 phrases respectively. Their analysis files expose
PWV2/PWV3/PWV4/PWV5 tags. Tag presence is **not decoded waveform features**.
The host cache is ignored/private; this document omits track titles and USB
paths. `python3 -m unittest tests.test_pre_gig tests.test_prodjlink_bridge`
passes seven tests, including local UDP-to-TCP contract delivery.

The linked TouchDesigner work calls for a live field inspector and an ocean-blue
particle visual. Its existing **offline** render consumes track title, original
and adjusted BPM, source position, beat index/bar/phase, PSSI phrase label and
progress, three waveform bands, derived activity, and authored mix gain. The
committed RX3 bridge can presently provide the metadata, timing, and phrase
subset for a matching prepared single USB, with explicit validity and age.

Remaining gaps before that visual can honestly run from the deck:

- PWV4/PWV5 waveform decoding and source-time sampling of three bands/activity.
- No continuous mixer fader, actual gain, or measured audio level. On-air is a
  boolean only; an inspector must show unavailable or manual selection.
- No live TouchDesigner JSON/OSC adapter and no native real-time particle
  workflow accepted against the RX3 stream yet. The film uses offline replay.
- No source-media slot in the current RX3 packet. A second USB can reuse the
  same track ID, so the cache join assumes exactly one prepared music USB.
- Source frame rate mapping is physically checked for one 44.1-kHz track only.
  Direct metadata reads and any audio range service require separate hardware
  validation and an explicit byte/latency budget.

The optional music-sample port is a later, read-only, bounded file-range
operation, not a field already emitted by Now Playing. Its request/response
must verify the exact source USB and file, allow only supported audio paths,
enforce rate and byte limits, and never run disk I/O in a player callback.
