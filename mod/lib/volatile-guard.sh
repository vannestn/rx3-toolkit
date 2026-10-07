#!/bin/sh
# SPDX-License-Identifier: MPL-2.0
# Read-only preflight, before even the panel probe creates temporary files.
# Reject unusual layouts conservatively; do not try to repair/remount them.
volatile_mount_layout()
{
    [ -r "$1" ] || return 1
    awk '
        function ram(t) { return t=="tmpfs" || t=="ramfs" || t=="rootfs" }
        NF < 4 { bad=1 }
        $2=="/" { roots++; if (!ram($3)) bad=1 }
        $2=="/root" || $2=="/root/pdj" || $2=="/tmp" {
            if (!ram($3)) bad=1
        }
        index($2,"/root/pdj/")==1 || index($2,"/tmp/")==1 { bad=1 }
        # Linux may retain rootfs beneath the active tmpfs root. Every
        # root entry must be RAM-backed; require at least one.
        END { exit (bad || roots<1) }
    ' "$1"
}
volatile_path_layout()
{
    # Fixed paths and their ancestors must not redirect writes elsewhere.
    # Optional root is for host fixtures, never supplied by production startup.
    _vg_root=$1
    for _vg_path in /root /root/pdj /tmp; do
        [ ! -L "$_vg_root$_vg_path" ] && [ -d "$_vg_root$_vg_path" ] || return 1
    done
    for _vg_path in /root/pdj/rbp /tmp/rx3-patch.state /tmp/rx3-performance.ready \
        /tmp/rx3-stems.log /tmp/rx3-rbp_stdout.txt /tmp/rx3-rbp_restore.txt; do
        [ ! -L "$_vg_root$_vg_path" ] || return 1
        if [ -e "$_vg_root$_vg_path" ]; then
            [ -f "$_vg_root$_vg_path" ] || return 1
        fi
    done
}
