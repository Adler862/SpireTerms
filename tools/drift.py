"""Compare the shipped build against the currently installed game.

Answers "can I still ship this build?" without rebuilding, per table:

  stale      keys in the build that no longer exist in the game (they will simply
             never resolve, but they also mean the build is behind)
  missing    game keys the build does not cover (new cards/relics after an update)
  changed    keys whose official Chinese text differs from what was baked in —
             these are the dangerous ones, because the override ships the old
             wording for both languages
  vars       keys whose `{...}` placeholders no longer match the game's. The
             entry renders the raw placeholder text when a dynamic variable is
             gone or renamed, which is what a player actually sees
  format     baked strings that no longer pass a brace-balance check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import is_text_field, is_title_field, top_level_expressions  # noqa: E402
from pck import Pck  # noqa: E402

DEFAULT_PCK = os.environ.get(
    "STS2_PCK", r"D:\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck"
)
MOD_ID = "SpireTerms"

TABLES = ("cards", "relics")

# Fields the build drops on purpose, so "missing" does not count them.
SKIP_FIELDS = {"relics": ("flavor",)}


def read_table(pck_path: str, table: str, mod_prefix: str = "") -> dict[str, str]:
    path = f"localization/zhs/{table}.json"
    if mod_prefix:
        path = f"{mod_prefix}/{path}"
    with Pck(pck_path) as pck:
        try:
            entry = pck.one(path)
        except LookupError:
            return {}
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


def skipped(table: str, key: str) -> bool:
    field = key.partition(".")[2]
    return field in SKIP_FIELDS.get(table, ())


def compare(table: str, game: dict[str, str], built: dict[str, str]) -> tuple[int, list[str]]:
    stale = sorted(set(built) - set(game))
    missing = sorted(k for k in set(game) - set(built) if not skipped(table, k))
    changed = []
    bad_format = []
    vars_gone = []
    retitled = []

    for key, value in built.items():
        if key.count("{") != key.count("}"):
            bad_format.append(key)
        original = game.get(key)
        if original is None:
            continue
        field = key.partition(".")[2]
        if is_text_field(table, field) and strip_annotation(value) != original:
            changed.append(key)
        if is_title_field(field) and value != original and not value.startswith(original + " / "):
            # The build holds a name the game no longer uses.
            retitled.append(key)
        if top_level_expressions(value) != top_level_expressions(original):
            vars_gone.append(key)

    print(f"[{table}] game {len(game)} / build {len(built)}  stale {len(stale)}  "
          f"missing {len(missing)}  changed {len(changed)}  vars {len(vars_gone)}  "
          f"titles {len(retitled)}  bad format {len(bad_format)}")

    for label, items in (
        ("stale", stale),
        ("missing", missing),
        ("changed", changed),
        ("vars", vars_gone),
        ("titles", retitled),
        ("bad", bad_format),
    ):
        for key in items[:10]:
            print(f"  {label}: {key}")
        if len(items) > 10:
            print(f"  {label}: ... {len(items) - 10} more")

    return len(changed) + len(vars_gone) + len(retitled) + len(bad_format), missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pck", default=DEFAULT_PCK)
    ap.add_argument("--build", default=str(Path(__file__).parent.parent / "dist" / MOD_ID / f"{MOD_ID}.pck"))
    args = ap.parse_args()

    problems = 0
    totals = []
    for table in TABLES:
        game = read_table(args.pck, table)
        built = read_table(args.build, table, MOD_ID)
        if not built:
            print(f"[{table}] not in build")
            continue
        bad, missing = compare(table, game, built)
        problems += bad
        totals.append((table, missing))
        print()

    if len(totals) == 1:
        print("note: build ships no relics table, run build.py to regenerate")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
