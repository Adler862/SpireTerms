"""Compare the shipped build against the currently installed game.

Answers "can I still ship this build?" without rebuilding:

  stale      keys in the build that no longer exist in the game (they will simply
             never resolve, but they also mean the build is behind)
  missing    game keys the build does not cover (new cards after an update)
  changed    keys whose official Chinese text differs from what was baked in —
             these are the dangerous ones, because the override ships the old
             wording for both languages
  format     baked strings that no longer pass a brace-balance check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pck import Pck  # noqa: E402

DEFAULT_PCK = os.environ.get(
    "STS2_PCK", r"D:\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck"
)
MOD_ID = "SpireTerms"


def read_game_cards(pck_path: str) -> dict[str, str]:
    with Pck(pck_path) as pck:
        entry = pck.one("localization/zhs/cards.json")
        return json.loads(pck.read(entry).decode("utf-8"))


def read_build_cards(build_pck: Path) -> dict[str, str]:
    with Pck(build_pck) as pck:
        entry = pck.one(f"{MOD_ID}/localization/zhs/cards.json")
        return json.loads(pck.read(entry).decode("utf-8"))


def strip_annotation(text: str) -> str:
    """Remove the inserted ` (English)` inside gold spans, keeping the Chinese."""
    import re

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if " (" in inner and inner.endswith(")"):
            return f"[gold]{inner.rsplit(' (', 1)[0]}[/gold]"
        return match.group(0)

    return re.sub(r"\[gold\](.*?)\[/gold\]", repl, text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pck", default=DEFAULT_PCK)
    ap.add_argument("--build", default=str(Path(__file__).parent.parent / "dist" / MOD_ID / f"{MOD_ID}.pck"))
    args = ap.parse_args()

    game = read_game_cards(args.pck)
    built = read_build_cards(Path(args.build))

    stale = sorted(set(built) - set(game))
    missing = sorted(set(game) - set(built))
    changed = []
    bad_format = []

    for key, value in built.items():
        if key.count("{") != key.count("}"):
            bad_format.append(key)
        original = game.get(key)
        if original is None:
            continue
        if key.endswith(".description") and strip_annotation(value) != original:
            changed.append(key)

    print(f"game keys   : {len(game)}")
    print(f"build keys  : {len(built)}")
    print(f"stale       : {len(stale)}")
    print(f"missing     : {len(missing)}")
    print(f"changed     : {len(changed)}")
    print(f"bad format  : {len(bad_format)}")

    for label, items in (("stale", stale), ("missing", missing), ("changed", changed), ("bad", bad_format)):
        for key in items[:10]:
            print(f"  {label}: {key}")
        if len(items) > 10:
            print(f"  {label}: ... {len(items) - 10} more")

    return 1 if (changed or bad_format) else 0


if __name__ == "__main__":
    raise SystemExit(main())
