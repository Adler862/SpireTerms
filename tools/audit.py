"""Scan the official parallel text for terms one glossary entry cannot cover.

The glossary maps one Chinese term to one English string. The game's own English
does not always agree: `升级` is *Upgrade* when it is a verb and *Upgraded* when it
is an adjective. This prints every term whose aligned `[gold]` spans carry more
than one English form, so the choice of a POSTFIX / MANUAL entry is a decision
made from evidence instead of a guess.

Usage:
    python tools/audit.py [--min 3] [--ratio 0.9]

A term is reported when the runner-up form shows up at least `--min` times and
holds more than `1 - ratio` of the occurrences — a dominant form at 95% is normal
plural/passive noise, a 70/30 split is a rule waiting to be written.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

SPAN_RE = re.compile(r"\[gold\](.*?)\[/gold\]")
TAG_RE = re.compile(r"\[/?\w+\]")

TABLES = ("cards", "relics")


def read(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parent.parent / "_game"))
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--ratio", type=float, default=0.9)
    args = ap.parse_args()

    data = Path(args.data)
    seen: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for table in TABLES:
        zh = read(data / "zhs" / f"{table}.json")
        en = read(data / "eng" / f"{table}.json")
        for key, text in zh.items():
            if not key.endswith(".description"):
                continue
            zs, es = SPAN_RE.findall(text), SPAN_RE.findall(en.get(key, "") or "")
            if not zs or len(zs) != len(es):
                continue
            for a, b in zip(zs, es):
                if "{" in a or "{" in b or not b:
                    continue
                seen[a][TAG_RE.sub("", b).strip()] += 1

    noisy = 0
    for term, forms in sorted(seen.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(forms.values())
        if total < args.min or len(forms) < 2:
            continue
        best, count = forms.most_common(1)[0]
        if count / total >= args.ratio:
            noisy += 1
            continue
        spread = ", ".join(f"{form}×{n}" for form, n in forms.most_common(4))
        print(f"{term:<8} {count}/{total} {best:<14} | {spread}")

    print(f"\n(collapsed {noisy} term(s) dominated by one form above {args.ratio:.0%})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
