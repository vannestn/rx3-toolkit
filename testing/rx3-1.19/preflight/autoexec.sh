#!/bin/sh
# Observation-only probe: no player stop, preload, code patch or device writes.
USB=${1%/}
case "$USB" in /media/usb1/*|/media/usb2/*) ;; *) exit 1 ;; esac
name=${USB#/media/usb?/}
case "$name" in ''|*/*|*[!A-Za-z0-9._-]*) exit 1 ;; esac
[ -d "$USB" ] && [ ! -L "$USB" ] || exit 1
# Write only to the supplied, mounted removable FAT volume.
awk -v path="$USB" '$2==path && $1 ~ /^\/dev\// && $3=="vfat" {n++} END {exit n!=1}' /proc/mounts || exit 1
OUT="$USB/RX3_PREFLIGHT.txt"
[ ! -L "$OUT" ] || exit 1
if [ -e "$OUT" ]; then [ -f "$OUT" ] || exit 1; fi
{
    echo 'RX3 observation-only preflight v1'
    echo 'No hooks, player restart, flash or settings writes requested.'
    echo '--- mount table ---'
    cat /proc/mounts
    echo '--- path types (no file contents) ---'
    for p in /root /root/pdj /root/pdj/rbp /tmp /tmp/rx3-patch.state /tmp/rx3-performance.ready /tmp/rx3-stems.log /tmp/rx3-rbp_stdout.txt /tmp/rx3-rbp_restore.txt; do
        printf '%s exists=' "$p"; [ -e "$p" ] && printf yes || printf no
        printf ' symlink='; [ -L "$p" ] && printf yes || printf no
        printf ' directory='; [ -d "$p" ] && printf yes || printf no
        printf ' regular='; [ -f "$p" ] && printf yes || printf no
        printf '\n'
        if [ -L "$p" ]; then readlink "$p"; fi
    done
    echo '--- end ---'
} > "$OUT"

# Optional finite sender: isolated process, stdin only, no receiver or commands.
# Physical acceptance is separate from host/ARM compilation checks.
if [ -x /mnt/iso/report-send ]; then
    /mnt/iso/report-send < "$OUT" >/dev/null 2>&1 &
fi
