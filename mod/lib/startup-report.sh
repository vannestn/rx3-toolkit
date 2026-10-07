#!/bin/sh
# Read-only observation; invoked in a separate reporting process.
    echo 'RX3 position-runtime preflight v1'
    echo 'Pre-hook observation; guarded position runtime starts separately.'
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
if [ -r /mnt/iso/lib/volatile-guard.sh ]; then
    . /mnt/iso/lib/volatile-guard.sh
    volatile_mount_layout /proc/mounts
    printf 'mount_guard_status=%s\n' "$?"
    volatile_path_layout ""
    printf 'path_guard_status=%s\n' "$?"
fi
