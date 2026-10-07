"""Source-time motion features from rekordbox PWV5 display metadata.

PWV5 RGB components describe display colors, not calibrated frequency bands.
The activity envelope below is an artistic motion control, not live audio RMS.
"""
from __future__ import annotations

import math


class WaveformMotion:
    def __init__(self, waveform: dict):
        if waveform.get("style") != "PWV5" or waveform.get("rate_hz") != 150:
            raise ValueError("unsupported detailed waveform")
        raw = bytes.fromhex(waveform["data_hex"])
        if not raw or len(raw) % 2:
            raise ValueError("malformed PWV5 payload")
        self.values = []
        fast = slow = context = novelty = 0.0
        fast_rise = 1-math.exp(-1/(150*.025))
        fast_fall = 1-math.exp(-1/(150*.16))
        slow_rate = 1-math.exp(-1/150)
        context_rate = 1-math.exp(-1/450)
        novelty_decay = math.exp(-1/(150*.12))
        for i in range(0, len(raw), 2):
            word = (raw[i] << 8) | raw[i+1]
            height = ((word >> 2) & 31) / 31
            fast += (height-fast)*(fast_rise if height > fast else fast_fall)
            slow += (height-slow)*slow_rate
            context += (height-context)*context_rate
            novelty = max(max(0, fast-slow-.035)*3, novelty*novelty_decay)
            self.values.append((fast, slow, min(1, novelty),
                                max(-1, min(1, (fast-context)*2)),
                                ((word >> 13) & 7)/7,
                                ((word >> 7) & 7)/7,
                                ((word >> 10) & 7)/7))

    def at(self, position_ms: float | None) -> dict:
        if (position_ms is None or not math.isfinite(position_ms) or
                position_ms < 0 or position_ms >= len(self.values)*1000/150):
            return {"valid": False, "reason": "position_outside_waveform",
                    "style": "PWV5", "intensity": None, "activity": None,
                    "accent": None, "contrast": None, "rgb_display": None,
                    "bands": None}
        point = position_ms*150/1000
        index = int(point)
        alpha = point-index
        first = self.values[index]
        second = self.values[min(index+1, len(self.values)-1)]
        sample = [a+(b-a)*alpha for a,b in zip(first,second)]
        return {"valid": True, "reason": None, "style": "PWV5",
                "intensity": sample[0], "activity": sample[1],
                "accent": sample[2], "contrast": sample[3],
                "rgb_display": sample[4:7], "bands": None}
