from __future__ import annotations

import re

STOP = set("""a an the and or of to in on for with is are was were be been it its this that these those what which who how
do does did we our you your i my they their can could should would must may might will shall if as at by from about
into than then so not no any all each per has have had there here when where why under over""".split())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
