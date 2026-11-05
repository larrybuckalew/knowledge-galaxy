#!/usr/bin/env python3
"""
build.py - Scan the notes folder and write viewer/graph-data.js.

Standard library only - no pip installs.

Output shape:

    const GRAPH = {nodes: [...], links: [...]};

Every node carries a numeric `id` equal to its index in the nodes array, and
links use those same indexes, so a note can be looked up by index later.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
NOTES_DIR = PROJECT_ROOT / "notes"
VIEWER_DIR = PROJECT_ROOT / "viewer"
OUTPUT_FILE = VIEWER_DIR / "graph-data.js"

EXCERPT_LENGTH = 700
TITLE_MATCH_BOOST = 3


# ─── Text helpers ────────────────────────────────────────────────────────

def label_from_filename(path: Path) -> str:
    """A readable label derived from the filename."""
    stem = path.stem
    # Drop capture timestamps and ordering prefixes: they are noise in a label.
    stem = re.sub(r"^\d{8}-\d{6}[-_ ]*", "", stem)
    stem = re.sub(r"^\d+[-_ ]+", "", stem)
    words = [w for w in re.split(r"[-_]+", stem) if w]
    if not words:
        return path.stem
    return " ".join(w.capitalize() for w in words)


def group_from_path(path: Path) -> str:
    """The note's parent folder, used to colour-code the galaxy."""
    rel = path.relative_to(NOTES_DIR)
    if rel.parent == Path("."):
        return "root"
    return rel.parent.name


def clean_excerpt(content: str, max_len: int = EXCERPT_LENGTH) -> str:
    """Flatten markdown into a readable ~700 character excerpt."""
    text = re.sub(r"^---[\s\S]*?---", "", content)          # frontmatter
    text = re.sub(r"^#+\s.*$", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)          # wikilinks
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # links
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)            # bold
    text = re.sub(r"\*([^*]+)\*", r"\1", text)                # italic
    text = re.sub(r"```[\s\S]*?```", "", text)                # code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)                  # inline code
    text = re.sub(r"^\s*\|.*\|", "", text, flags=re.MULTILINE)  # tables
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)  # list markers
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        cut = text[:max_len].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


def find_wikilinks(content: str) -> list:
    """All [[wikilink]] targets in a note."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def link_key(text: str) -> str:
    """Normalised key for matching a mention against a note label."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# ─── Build ───────────────────────────────────────────────────────────────

def main() -> int:
    if not NOTES_DIR.exists():
        print(f"Notes folder not found: {NOTES_DIR}", file=sys.stderr)
        return 1

    md_files = sorted(NOTES_DIR.rglob("*.md"))
    if not md_files:
        print(f"No .md files under {NOTES_DIR}", file=sys.stderr)
        return 1

    # Pass 1: read every note, build its node.
    notes = []
    for index, path in enumerate(md_files):
        content = path.read_text(encoding="utf-8", errors="replace")
        label = label_from_filename(path)
        notes.append({
            "id": index,
            "path": path,
            "label": label,
            "group": group_from_path(path),
            "content": content,
            "excerpt": clean_excerpt(content),
        })

    # Pass 2: nodes carry id == index in the nodes array.
    nodes = []
    for index, note in enumerate(notes):
        nodes.append({
            "id": index,
            "label": note["label"],
            "group": note["group"],
            "excerpt": note["excerpt"],
        })

    # Pass 3: links. Two notes link when one mentions the other's title, or
    # when they share a [[wikilink]].
    labels = {note["label"]: note["id"] for note in notes}
    label_keys = {link_key(note["label"]): note["id"] for note in notes}

    pairs = set()

    def add_link(a: int, b: int) -> None:
        if a != b:
            pairs.add((min(a, b), max(a, b)))

    for note in notes:
        source = note["id"]
        body = note["content"]

        # (a) One note mentions another note's title.
        for other in notes:
            if other["id"] == source:
                continue
            if len(other["label"]) >= 4 and other["label"].lower() in body.lower():
                add_link(source, other["id"])

        # (b) Shared [[wikilinks]] - both notes reference the same target.
        for target in find_wikilinks(body):
            key = link_key(target)
            resolved = labels.get(target)
            if resolved is None:
                resolved = label_keys.get(key)
            if resolved is not None:
                add_link(source, resolved)

    # Shared wikilink targets that neither note names directly still connect.
    shared_targets = {}
    for note in notes:
        for target in find_wikilinks(note["content"]):
            shared_targets.setdefault(link_key(target), []).append(note["id"])
    for ids in shared_targets.values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                add_link(ids[i], ids[j])

    links = [{"source": a, "target": b} for a, b in sorted(pairs)]

    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"nodes": nodes, "links": links}
    js = "const GRAPH = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    OUTPUT_FILE.write_text(js, encoding="utf-8")

    groups = {}
    for node in nodes:
        groups[node["group"]] = groups.get(node["group"], 0) + 1

    print(f"Wrote {OUTPUT_FILE}")
    print(f"  nodes: {len(nodes)}")
    print(f"  links: {len(links)}")
    for group, count in sorted(groups.items()):
        print(f"  group '{group}': {count} notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
