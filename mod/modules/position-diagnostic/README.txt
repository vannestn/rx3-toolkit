Playback position diagnostic — experimental, firmware 1.19 only

Explicit module selection: position-diagnostic (requires core + now-playing).
Disabled by default. Do not select other performance modules for the first test.
No hardware position validation yet. This is not a completed Beat Link adapter.

What changes on the deck
Uses the existing shared TimeStretch audio observer and PcmReader::load identity
hook. Core now installs the identity hook for an audio-only client before its
UI-free early return. No extra UI hooks are enabled. Existing executable and
instruction guards remain. A failed identity install stops the modules and
runs the existing cleanup path. With only Now Playing selected, this diagnostic
is not started and the new identity hook is not requested.

The audio callback ignores the sample buffer and publishes four scalar values
under a one-attempt atomic gate. Contention drops a sample. No callback I/O,
allocation, clock lookup or wait. A worker sends at <=20 Hz on UDP 50124 to the
USB link-local broadcast; nothing listens for commands. Existing Now Playing
UDP 50123 is unchanged. No firmware, bootloader, settings or audio writes added.

Wire data
JSON type=position-diagnostic, version=1, sequence=uint32, units=unverified.
Two deck entries numbered 1/2:
- readerGeneration: increments on the existing reader's will-load notification.
- sample: null until observed in this generation; otherwise generation,
  observation (uint32 counter), rawPosition (signed 32-bit), frames (uint32).
Repeated observations are exported again; the host tracks their age. They do
not prove current playback or audibility. Values wrap at their integer width.
No pointers, titles, track IDs or audio leave through this new message.

Reader generation is not a rekordbox ID or source-media ID. It is deliberately
not joined with the independent Now Playing feed. The existing core load hook
publishes reader identity without interpreting the native load return code;
we have not verified its failure semantics. Unload may leave a last observation
until reload, so consumers must not use this stream alone as loaded/play state.
Late/in-flight callbacks, reused reader pointers, audible latency, render-ahead,
position units and pitch/master-tempo behavior require physical validation.
No exact source position/phrase mapping should be enabled based on this probe.

Recovery / limitations
Preserve the existing USB package before replacing it. Use a stopped-player,
cold-start test and a clean stock restart afterward. No live library unloading.
Upstream audio-stage release uses a drain without a timeout and retains a hook
if restoration fails. This diagnostic does not strengthen that inherited
teardown or prove recovery from arbitrary crashes. Volatile privileged hooks
still can crash or interrupt playback; this is not a no-risk certification.

See testing/rx3-1.19/POSITION-TEST.txt for the controlled test procedure and
scripts/position_diagnostic.py for the receive-only recorder.
