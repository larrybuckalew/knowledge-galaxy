#!/usr/bin/env python3
"""
build.py — Scan markdown notes and generate graph-data.js for 3D knowledge galaxy.
Standard library only — no pip installs.
"""

import os
import re
import json
import sys
from pathlib import Path


NOTES_DIR = Path(__file__).parent / "notes"
OUTPUT_FILE = Path(__file__).parent / "viewer" / "graph-data.js"
EXCERPT_LENGTH = 700


def extract_title(content: str, filename: str) -> str:
    """Extract the first H1 heading as title, fallback to filename."""
    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return filename.replace(".md", "").replace("-", " ").title()


def extract_excerpt(content: str, max_len: int = EXCERPT_LENGTH) -> str:
    """Extract a clean excerpt from note content."""
    # Remove frontmatter if present
    content = re.sub(r'^---[\s\S]*?---', '', content)
    # Remove headings
    content = re.sub(r'^#+\s.*$', '', content, flags=re.MULTILINE)
    # Remove wikilinks syntax but keep the text
    content = re.sub(r'\[\[([^\]]+)\]\]', r'\1', content)
    # Remove markdown links but keep text
    content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
    # Remove bold/italic
    content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
    content = re.sub(r'\*([^*]+)\*', r'\1', content)
    # Remove code blocks
    content = re.sub(r'```[\s\S]*?```', '', content)
    content = re.sub(r'`([^`]+)`', r'\1', content)
    # Remove tables
    content = re.sub(r'\|.*\|', '', content)
    # Remove horizontal rules
    content = re.sub(r'^---+$', '', content, flags=re.MULTILINE)
    # Normalize whitespace
    content = re.sub(r'\s+', ' ', content)
    content = content.strip()
    # Truncate
    if len(content) > max_len:
        content = content[:max_len].rsplit(' ', 1)[0] + "…"
    return content


def find_wikilinks(content: str) -> list[str]:
    """Find all [[wikilinks]] in content."""
    return re.findall(r'\[\[([^\]]+)\]\]', content)


def find_title_mentions(content: str, all_titles: list[str]) -> list[str]:
    """Find mentions of other note titles in content."""
    mentions = []
    for title in all_titles:
        if title.lower() in content.lower():
            mentions.append(title)
    return mentions


def get_group_from_path(filepath: Path) -> str:
    """Get group name from parent folder."""
    rel = filepath.relative_to(NOTES_DIR)
    if rel.parent != Path("."):
        return str(rel.parent)
    return "root"


def main():
    if not NOTES_DIR.exists():
        print(f"Notes directory not found: {NOTES_DIR}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Scan all markdown files
    md_files = sorted(NOTES_DIR.rglob("*.md"))
    if not md_files:
        print("No markdown files found", file=sys.stderr)
        sys.exit(1)

    # First pass: collect all titles
    file_data = []
    all_titles = []

    for filepath in md_files:
        content = filepath.read_text(encoding="utf-8")
        title = extract_title(content, filepath.name)
        all_titles.append(title)
        file_data.append({
            "path": filepath,
            "title": title,
            "content": content,
            "group": get_group_from_path(filepath),
        })

    # Second pass: build nodes and links
    nodes = []
    links = []
    title_to_index = {title: i for i, title in enumerate(all_titles)}

    for idx, data in enumerate(file_data):
        excerpt = extract_excerpt(data["content"])
        nodes.append({
            "id": idx,
            "label": data["title"],
            "group": data["group"],
            "excerpt": excerpt,
        })

        # Find links via wikilinks
        wikilinks = find_wikilinks(data["content"])
        for wl in wikilinks:
            # Try exact match first, then case-insensitive
            target_idx = None
            if wl in title_to_index:
                target_idx = title_to_index[wl]
            else:
                for title, i in title_to_index.items():
                    if title.lower() == wl.lower():
                        target_idx = i
                        break
            if target_idx is not None and target_idx != idx:
                links.append({"source": idx, "target": target_idx})

        # Find links via title mentions
        mentions = find_title_mentions(data["content"], all_titles)
        for mention in mentions:
            target_idx = title_to_index[mention]
            if target_idx != idx:
                # Avoid duplicate links
                if not any(l["source"] == idx and l["target"] == target_idx for l in links):
                    links.append({"source": idx, "target": target_idx})

    # Write output
    graph_data = {"nodes": nodes, "links": links}
    js_content = f"window.GRAPH = {json.dumps(graph_data, ensure_ascii=False, separators=(',', ':'))};"

    OUTPUT_FILE.write_text(js_content, encoding="utf-8")
    print(f"Generated {OUTPUT_FILE}")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Links: {len(links)}")


if __name__ == "__main__":
    main()