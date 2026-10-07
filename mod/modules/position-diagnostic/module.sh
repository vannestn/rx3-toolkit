#!/bin/sh
# SPDX-License-Identifier: MPL-2.0
module_begin position-diagnostic position_diagnostic
position_diagnostic_prepare()
{
    module_disabled_by_switch position-diagnostic && return 0
    [ -r "$CORE_OBJECT" ] || return 1
    # ACCEPTED is the already-verified stock/normalized player hash. The
    # global compatibility module also accepts other versions; this probe
    # deliberately does not, regardless of the builder UI selection.
    [ "$ACCEPTED" = cf309238491e73cdbdc1f08a09f7a3177e079068 ] || {
        say "Position diagnostic refused: exact firmware 1.19 player required"
        return 1
    }
    module_export RX3_POSITION_DIAGNOSTIC 1 "Experimental raw playback position" || :
}
register_prepare_hook position_diagnostic_prepare
