# RX3 pre-gig export and live contract bridge

## Direct USB metadata path to build next

The RX3 runtime receives the mounted music USB path as `$USB` from
`autoexec.sh`. The drive remains mounted while its tracks are in use, so the
runtime can read `PIONEER/rekordbox/export.pdb` and the corresponding
`PIONEER/USBANLZ` files directly. Loading the mod into RAM does not itself
copy those files into RAM or remove access to the stick. The current host-side
catalog join is an interim implementation, **not** a requirement that the DJ
pre-scan every USB to obtain track names or phrases.

The next deck-side increment should read metadata only from the actual mounted
music USB, identify the loaded deck's media slot and export generation, and
associate its track ID with the matching PDB row and analysis path. Do bounded
file reads and parsing on the mod's worker thread, never in a player callback;
cache the selected track's title, artist, beat grid and PSSI phrases in volatile
memory. Publish a compact identity/analysis asset once on load or media change,
then live beat, position and phrase state on USB-B. If a read, slot association,
or parse fails, report unknown rather than using a same-numbered ID from the
wrong drive. Do not write to rekordbox files or keep a file descriptor open
across drive removal. Validate this path on hardware before treating the host
pre-gig scan as optional for a show.

The present PR has **not implemented or tested** direct deck-side PDB/ANLZ
reading. Until it does, its live names and phrases depend on the selected
host cache and single prepared music USB described below.

The pre-gig scanner and bridge live in this toolkit. They require no VJ checkout
and do not retrieve music over USB-B. The DJ's rekordbox USB is mounted on the
computer before the set; the scanner reads its `export.pdb` and matching
`ANLZ0000.DAT`/`.EXT` files into an ignored host cache. It copies **no audio**
and changes **no USB file**. A track with a valid grid but bad/missing PSSI
keeps its grid and reports phrase unavailability explicitly.

```
python3 scripts/pre_gig.py scan /Volumes/DJ_USB --out local/gigs/show-001
```

The cache contains `manifest.json` (export hash and counts), `tracks.json`
(all parsed track IDs and individual statuses), and `analysis/<id>.json`
(validated beat grid, phrase entries, raw-label provenance, source file hashes,
and waveform tag presence). It is a private host cache; track titles and paths
can be sensitive. A newer Device Library Plus USB without classic
`PIONEER/rekordbox/export.pdb` is reported as unsupported rather than silently
matched by title.

The **optional** install step writes only two files at the USB root. It checks
the scanned PDB and analysis hashes again, verifies firmware, image, manifest,
and package audit, and backs up any existing root files in the host cache.
Use it only for a known RX3 1.19 and the matching audited package; it does not
turn a bench candidate into a performance-certified release.

```
python3 scripts/pre_gig.py install /Volumes/DJ_USB \
  --cache local/gigs/show-001 \
  --package local/build-combined-diagnostic-final \
  --firmware 1.19
```

After a normal USB eject, insert the prepared stick in the RX3 and connect
its rear USB-B to the host. Start this service on the host:

```
python3 scripts/prodjlink_bridge.py --catalog local/gigs/show-001 \
  --firmware 1.19 --source 169.254.159.144 --port 50130
nc 127.0.0.1 50130
```

The bridge receives existing RX3 UDP Now Playing/position streams on
50123/50124 and publishes newline-delimited JSON snapshots to TCP clients on
localhost:50130 (override `--host`/`--port`). Each line follows the proposed
Pro DJ Link **semantic** contract: schema/session/sequence and deck identity,
then `track`, `transport`, `timing`, `phrase`, `mixer`, and `audio` groups. This
is not a raw Beat Link packet emulator. Numeric track IDs resolve only against
the explicitly selected cache. `track.source_slot` remains null and
`capabilities.media_slot_verified` is false because the RX3 packet does not
identify which USB supplied the track. **Use exactly the prepared music USB**;
a second music USB can reuse IDs and make host-side association wrong.

Timing uses measured RX3 reader frames divided by 44,100, the exported grid's
individual beat times, and the PSSI phrase boundaries. The frame conversion is
marked provisional for other source sample rates. A load/reload waits for a new
reader generation before attaching a position to the new track. Packet gaps
invalidate timing after 500 ms and the Now Playing state after three seconds;
unknown is null, never an invented zero. Current phrase and next phrase appear
in the live snapshot. The full phrase map stays in the host cache and is
referenced by `track.analysis_key`/`phrase.asset_id`, avoiding a large asset in
each 20 Hz packet. Loop bounds, master/sync state, continuous mixer controls,
audio meters, and PCM remain unavailable. `on_air` is exposed but is not a
volume measure.

The bench rolling recorder also binds UDP 50123/50124; stop it before starting
the bridge. The bridge never sends to the deck. A host-only TCP/UDP integration
test and a receive-only physical paused-track smoke test passed on firmware
1.19: the latter resolved the loaded track title, source position, and phrase
through the selected cache. This is not a two-deck set/endurance acceptance.
The separate UDP 50126 startup status report is still missing in the current
diagnostic package and must be investigated before calling it gig-ready.
