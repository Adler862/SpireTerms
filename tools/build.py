"""Build zh->en bilingual card localization overrides for Slay the Spire 2.

Pipeline
--------
1. Read the official ``zhs`` and ``eng`` tables out of the game's pck.
2. Build a zh-term -> en-term glossary from three sources, in precedence order:
   * ``learned``  - majority-vote alignment of ``[gold]`` spans between the two
     languages of the same card description (official parallel text).
   * ``table``    - reverse lookup of ``.title`` keys across every localization
     table (zero collisions in practice).
   * ``manual``   - a short curated list for terms that no table defines
     (zones like 手牌 / 抽牌堆) or where the learned mapping is context-wrong.
3. Emit overrides that keep the Chinese text byte-identical and only *insert*
   English, so the result is reversible and machine-checkable.

Invariants enforced by :func:`check`:
  * removing the inserted English yields the official Chinese exactly;
  * the ordered list of top-level ``{...}`` expressions is unchanged, so the
    game can still resolve every dynamic variable;
  * braces stay balanced and nothing is inserted inside ``{...}``;
  * only keys that exist in the official zhs table are emitted.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pck import Pck  # noqa: E402

SPAN_RE = re.compile(r"\[gold\](.*?)\[/gold\]")
HAS_EXPR = re.compile(r"\{.*\}")

DEFAULT_PCK = os.environ.get(
    "STS2_PCK", r"D:\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck"
)

# Tables whose ``.title`` keys describe a term the player can meet in card text.
POOL_TABLES = (
    "cards",
    "powers",
    "orbs",
    "afflictions",
    "enchantments",
    "card_keywords",
    "static_hover_tips",
    "relics",
    "potions",
)

# Terms no table defines, or where word-level learning is contextually wrong.
# These are the only hand-written strings in the whole pipeline.
MANUAL = {
    "手牌": "Hand",
    "抽牌堆": "Draw Pile",
    "弃牌堆": "Discard Pile",
    "消耗牌堆": "Exhaust Pile",
    "牌组": "Deck",
    "最大生命值": "Max HP",
    "充能球": "Orb",
    "冰霜充能球": "Frost Orb",
    "升级": "Upgraded",
    "升级过": "Upgraded",
    "升级过的": "Upgraded",
    "稀有": "Rare",
    "普通": "Common",
    "罕见": "Uncommon",
    "能力": "Power",
    "攻击牌": "Attack",
    "个黑暗": "Dark",
    "生成过": "Channeled",
    "激发闪电": "Evoke Lightning",
    # Relic text names things no table titles: the game writes "Enchant",
    # "Potions", "Act" in its own English, so these follow that spelling.
    "遗物": "Relics",
    "蜡制遗物": "Wax Relic",
    "附魔": "Enchant",
    "药水": "Potions",
    "变化": "Transform",
    "休息": "Rest",
    "休息处": "Rest Site",
    "阶段": "Act",
    "先古": "Ancient",
    "先古牌": "Ancient Card",
    "稀有牌": "Rare Card",
    "多人游戏牌": "Multiplayer Cards",
}

SKIP_TERMS = {"?", ""}

TRUST_MIN = 2
TRUST_RATIO = 0.8

# Fields that carry player-visible prose and may embed keywords. `flavor` is
# deliberately absent: it is lore, not rules text, and annotating it would put
# English inside a sentence the player reads for atmosphere.
TEXT_FIELDS = {
    "cards": ("description", "selectionScreenPrompt", "discardSelectionPrompt"),
    "relics": (
        "description",
        "eventDescription",
        "selectionScreenPrompt",
        "infoText",
        "historyEntry",
        "additionalRestSiteHealText",
        "readyToEvolve",
        "waxRelicPrefix",
        "approval",
        "warning",
    ),
}


def is_text_field(table: str, field: str) -> bool:
    return field in TEXT_FIELDS.get(table, ()) or field.endswith("Prompt")


def is_title_field(field: str) -> bool:
    """`打击.title`, `DINGY_DAGGER.title.dingy`, `SEA_GLASS.DEFECT.title`."""
    return field == "title" or field.startswith("title.") or field.endswith(".title")


@dataclass
class Glossary:
    terms: dict[str, str]
    source: dict[str, str]

    def get(self, term: str) -> str | None:
        return self.terms.get(term)


def load_tables(root: Path, lang: str) -> dict[str, dict]:
    out = {}
    for path in (root / lang).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            out[path.stem] = data
    return out


def extract_tables(pck_path: str, root: Path) -> None:
    with Pck(pck_path) as pck:
        for entry in pck.entries:
            parts = entry.path.split("/")
            if (
                len(parts) != 3
                or parts[0] != "localization"
                or not entry.path.endswith(".json")
                or len(parts[1]) != 3
            ):
                continue
            pck.extract(entry, root / parts[1] / parts[2])


def build_glossary(zh: dict[str, dict], en: dict[str, dict]) -> Glossary:
    terms: dict[str, str] = {}
    source: dict[str, str] = {}

    # 1. table titles (authoritative names)
    for table in POOL_TABLES:
        zt, et = zh.get(table, {}), en.get(table, {})
        for key, value in zt.items():
            if not key.endswith(".title") or not isinstance(value, str):
                continue
            other = et.get(key)
            if isinstance(other, str) and other and other != value and "{" not in value:
                terms.setdefault(value, other)
                source.setdefault(value, f"table:{table}")

    # 2. learned from aligned parallel descriptions
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for key, text in zh.get("cards", {}).items():
        if not key.endswith(".description"):
            continue
        other = en.get("cards", {}).get(key)
        if not isinstance(other, str):
            continue
        zs, es = SPAN_RE.findall(text), SPAN_RE.findall(other)
        if len(zs) != len(es) or not zs:
            continue
        for a, b in zip(zs, es):
            if HAS_EXPR.search(a) or HAS_EXPR.search(b) or not b:
                continue
            votes[a][b] += 1
    for term, counter in votes.items():
        best, count = counter.most_common(1)[0]
        total = sum(counter.values())
        if count >= TRUST_MIN and count / total >= TRUST_RATIO:
            terms[term] = best
            source[term] = "learned"

    # 3. manual corrections win over everything
    for term, value in MANUAL.items():
        terms[term] = value
        source[term] = "manual"

    for term in SKIP_TERMS:
        terms.pop(term, None)
        source.pop(term, None)
    return Glossary(terms, source)


def bilingual_title(zh_title: str, en_title: str | None) -> str:
    if not en_title or en_title == zh_title:
        return zh_title
    return f"{zh_title} / {en_title}"


def brace_depth(text: str) -> list[int]:
    """Depth of `{...}` nesting at each character (0 = plain prose)."""
    depth = 0
    out = []
    for char in text:
        if char == "{":
            depth += 1
        out.append(depth)
        if char == "}":
            depth -= 1
    return out


def top_level_expressions(text: str) -> list[str]:
    """Every `{...}` at depth 0, in order. Nested braces stay inside their parent."""
    out: list[str] = []
    start = -1
    depth = 0
    for i, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(text[start : i + 1])
    return out


def annotate_description(text: str, glossary: Glossary) -> str:
    depth = brace_depth(text)

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        # A gold span can sit inside a SmartFormat branch, e.g.
        # `{IfUpgraded:show:[gold]升级过的[/gold]}`. Inserting there changes the
        # expression itself, which the game then refuses to resolve.
        if depth[match.start()] > 0 or HAS_EXPR.search(inner):
            return match.group(0)
        english = glossary.get(inner)
        if not english or english == inner or inner.isascii():
            # `[gold]Boss[/gold]`: the span is already the English word.
            return match.group(0)
        return f"[gold]{inner} ({english})[/gold]"

    return SPAN_RE.sub(repl, text)


def strip_annotation(text: str, glossary: Glossary) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        for term, english in glossary.terms.items():
            suffix = f" ({english})"
            if inner.endswith(suffix) and inner[: -len(suffix)] == term:
                return f"[gold]{term}[/gold]"
        return match.group(0)

    return SPAN_RE.sub(repl, text)


def check(table: str, source: dict[str, str], built: dict[str, str],
          glossary: Glossary) -> list[str]:
    problems: list[str] = []
    for key, value in built.items():
        original = source.get(key)
        if original is None:
            problems.append(f"{key}: not in official zhs table")
            continue
        if is_text_field(table, key.rsplit(".", 1)[-1]):
            roundtrip = strip_annotation(value, glossary)
            if roundtrip != original:
                problems.append(f"{key}: not reversible")
        if value.count("{") != value.count("}"):
            problems.append(f"{key}: unbalanced braces")
        if "{ " in value or " }" in value:
            problems.append(f"{key}: stray brace spacing")
        if top_level_expressions(value) != top_level_expressions(original):
            problems.append(f"{key}: expression changed")
    return problems


def build_table(table: str, source: dict[str, str], english: dict[str, str],
                glossary: Glossary, ids: list[str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, text in source.items():
        entry_id, _, field = key.partition(".")
        if ids is not None and entry_id not in ids:
            continue
        if is_title_field(field):
            # `DINGY_DAGGER.title.dingy`, `SEA_GLASS.DEFECT.title`: one card can
            # carry several selectable names, each under its own key.
            out[key] = bilingual_title(text, english.get(key))
        elif is_text_field(table, field):
            out[key] = annotate_description(text, glossary)
        else:
            continue
    return out


def game_version(pck_path: str, fallback: str = "0.0.0") -> str:
    """Version the tables were baked from, straight out of the game's own report."""
    info = Path(pck_path).with_name("release_info.json")
    try:
        return json.loads(info.read_text(encoding="utf-8"))["version"].lstrip("v")
    except (OSError, ValueError, KeyError, TypeError):
        return fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pck", default=DEFAULT_PCK)
    ap.add_argument("--data", default=str(Path(__file__).parent.parent / "_game"))
    ap.add_argument("--out", default=str(Path(__file__).parent.parent / "dist"))
    ap.add_argument("--ids", nargs="*", help="card ids to include (default: all)")
    ap.add_argument("--refresh", action="store_true", help="re-extract tables from pck")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    data = Path(args.data)
    if args.refresh or not (data / "zhs").exists():
        extract_tables(args.pck, data)

    zh = load_tables(data, "zhs")
    en = load_tables(data, "eng")
    glossary = build_glossary(zh, en)

    source = zh["cards"]
    out = build_table("cards", source, en["cards"], glossary, args.ids)
    problems = check("cards", source, out, glossary)

    mod_id = "SpireTerms"
    out_root = Path(args.out)
    mod_dir = out_root / mod_id
    cards_json = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    # The reviewable source lives outside the mod folder: anything *.json inside a
    # mod dir gets probed by the loader as a possible manifest (log noise).
    (out_root / "cards.zhs.json").write_text(cards_json, encoding="utf-8")

    relic_source = zh["relics"]
    relics = build_table("relics", relic_source, en["relics"], glossary)
    problems += check("relics", relic_source, relics, glossary)
    relics_json = json.dumps(relics, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out_root / "relics.zhs.json").write_text(relics_json, encoding="utf-8")

    # A mod's localization only merges when it ships inside a PCK whose paths are
    # prefixed with the mod id (verified against v0.111.0).
    from pck_write import write_pck

    stale_flat = mod_dir / "localization"
    if stale_flat.exists():
        import shutil

        shutil.rmtree(stale_flat)

    mod_version = game_version(args.pck)
    if mod_version == "0.0.0":
        print("warning: release_info.json not found next to the pck, min_game_version unset",
              file=sys.stderr)

    write_pck(
        mod_dir / f"{mod_id}.pck",
        {
            f"{mod_id}/localization/zhs/cards.json": cards_json.encode("utf-8"),
            f"{mod_id}/localization/zhs/relics.json": relics_json.encode("utf-8"),
        },
    )
    (mod_dir / f"{mod_id}.json").write_text(
        json.dumps(
            {
                "id": mod_id,
                "name": "SpireTerms - 卡牌遗物术语中英对照",
                "author": "SpireTerms",
                "version": "0.3.0",
                "description": "卡牌与遗物的名称双写、关键词英文标注。纯本地化覆盖，无代码。",
                "min_game_version": mod_version,
                "has_pck": True,
                "has_dll": False,
                "affects_gameplay": False,
                "dependencies": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    src_by = collections.Counter(glossary.source.values())
    lines = [
        f"glossary terms: {len(glossary.terms)}  by source: {dict(src_by)}",
        f"problems: {len(problems)}",
    ]
    summary = list(lines)
    summary += [f"  ! {p}" for p in problems[:20]]
    for table, built in (("cards", out), ("relics", relics)):
        ids = {key.split(".", 1)[0] for key in built}
        texts = {key for key in built if not is_title_field(key.partition(".")[2])}
        summary.append(f"{table}: {len(ids)} entries, {len(built)} keys, {len(texts)} text keys")
        lines.append("")
        lines.append(f"{table}: {len(ids)} entries, {len(built)} keys, {len(texts)} text keys")
        for key in sorted(built):
            if is_title_field(key.partition(".")[2]):
                lines.append(f"  {key} -> {built[key]}")
    print("\n".join(summary))
    if args.report:
        Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
