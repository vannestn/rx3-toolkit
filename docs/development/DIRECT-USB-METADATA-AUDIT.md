# Read-only RX3 USB metadata transport audit

Scope: the direct-USB metadata candidate on firmware 1.19. This does not
certify a live gig. The existing performance core and its player hooks are
byte-identical to the previously audited combined diagnostic core; the new
logic is a standalone ARM process launched after the existing mount, firmware,
safe-mode, and player-readiness guards. It is never preloaded into `rbp`.

The process accepts one TCP request at a time on port 50131 from a link-local
USB-B peer. It serves only the mounted USB's `PIONEER/rekordbox/export.pdb`
and `PIONEER/USBANLZ/.../ANLZ0000.DAT|EXT`. It opens each component relative
to an already-open USB directory with `O_NOFOLLOW`, rejects traversal and
nonanalysis names, and opens files read-only. The PDB cap is 16 MiB; each
analysis file cap is 4 MiB. It sends at roughly 1 MiB/s at most and closes
each connection. On the host, the existing defensive PDB/PQTZ/PSSI parser
builds a volatile catalog; audio files are not exposed by this service.

Failure analysis:

| Failure | Effect and containment |
| --- | --- |
| Malformed PDB/path/analysis tag | Host rejects it; no player callback parses USB bytes. |
| Helper crash, bind failure, unplug | No metadata service; `rbp` and playback are separate. The host reports unavailable. |
| Slow or stalled peer | One connection at a time; two-second socket deadlines and file/throughput caps. |
| Reinserted mod | A RAM PID file identifies only the prior executable and stops that helper before restart. No firmware or persistent player file is changed by this step. |
| Two USBs or media switch | Existing startup guard refuses unsafe initial topology. The current Now Playing packet still lacks a source slot; never claim verified identity after a second music USB appears. |
| Startup status report | UDP 50126 reported complete with `coreReady=yes` and no error in the successful physical run. The first candidate also reported its helper failure without interrupting playback. |

Host validation: the standalone server read the real SOUND_PRO export and
track 150 analysis in a localhost build, resolving 238 tracks and 916 beats/
23 phrases. A local end-to-end RX3 bridge test combined that metadata with
synthetic Now Playing/position datagrams and emitted a valid current phrase.
The target is a static ARM EABI5 executable with no dynamic imports. The
independently built performance core hash matches the previous audited core.
Focused safety and bridge tests passed. The first physical candidate failed
to open the USB root because it used asm-generic open-flag values instead of
ARM's `O_DIRECTORY` and `O_NOFOLLOW` values. The player still started and
streamed normally; the helper reported exit code 3. The corrected ARM build
uses the architecture-specific values from Linux's ARM UAPI `fcntl.h` and
passed the exact-source package audit. On the RX3, its TCP 50131 port opened,
the host fetched a 238-track PDB and track 150's 916-beat grid and 23 PSSI
phrases, and the localhost bridge emitted “Kesi De” with live beat, phrase,
and PWV5 motion values. This is one-track bench validation, not an endurance
or two-deck acceptance test.

Bricking likelihood from the new helper is low: its only persistent read target
is a removable USB, and its failure is process-local. It does not flash
firmware or add an in-player hook. The residual risk is that the existing
mod's already-tested startup/relaunch path still runs when installing this
candidate, and unusual USB or filesystem states may behave differently on
hardware. Test in the room, keep the previous USB image backup, and check
normal stock restart before any performance use.
