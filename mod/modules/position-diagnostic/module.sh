#!/bin/sh
# SPDX-License-Identifier: MPL-2.0
module_begin position-diagnostic position_diagnostic
position_diagnostic_prepare()
{
    module_disabled_by_switch position-diagnostic && return 0
    [ -r "$CORE_OBJECT" ] || return 0
    module_export RX3_POSITION_DIAGNOSTIC 1 "Experimental raw playback position"
}
register_prepare_hook position_diagnostic_prepare
