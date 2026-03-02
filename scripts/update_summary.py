#!/usr/bin/env python3
"""Regenerate SUMMARY.md from the filesystem.

Defaults:
- Top-level markdown files (repo root) are listed first (excluding SUMMARY.md).
- Two sections are generated for `content/` and `examples/`.
- Directory structure is represented via README.md files inside folders.
- Titles come from the first H1 in each file, or a filename-derived fallback.
- Ordering preserves any existing order in SUMMARY.md when possible; new items
  are appended in sorted path order.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "SUMMARY.md"

DEFAULT_SECTIONS = [
    ("Content", "content"),
    ("Examples", "examples"),
]

LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)\* \[(?P<title>.+)\]\((?P<path>.+)\)\s*$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")


@dataclass
class Item:
    title: str
    path: str
    children: List["Item"] = field(default_factory=list)


@dataclass
class SummaryOrder:
    order_map: Dict[str, List[str]] = field(default_factory=dict)

    def add(self, parent_dir: str, path: str) -> None:
        if parent_dir not in self.order_map:
            self.order_map[parent_dir] = []
        if path not in self.order_map[parent_dir]:
            self.order_map[parent_dir].append(path)

    def sort_items(self, parent_dir: str, items: List[Item]) -> List[Item]:
        order = self.order_map.get(parent_dir)
        if not order:
            return sorted(items, key=lambda i: i.path)

        index = {p: i for i, p in enumerate(order)}

        def sort_key(item: Item) -> Tuple[int, str]:
            return (index.get(item.path, 10**9), item.path)

        return sorted(items, key=sort_key)


def read_existing_order(path: Path) -> SummaryOrder:
    order = SummaryOrder()
    if not path.exists():
        return order

    stack: List[Optional[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LIST_ITEM_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        level = indent // 2
        item_path = m.group("path")

        while len(stack) > level:
            stack.pop()
        parent_item = stack[-1] if stack else None
        parent_dir = os.path.dirname(parent_item) if parent_item else ""
        order.add(parent_dir, item_path)
        stack.append(item_path)

    return order


def first_h1_title(path: Path) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = H1_RE.match(line)
            if m:
                return m.group(1).strip()
    except Exception:
        return None
    return None


def filename_title(path: Path) -> str:
    stem = path.stem
    title = stem.replace("-", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in title.split())


def escape_title(title: str) -> str:
    return title.replace("[", "\\[").replace("]", "\\]")


def title_for(path: Path) -> str:
    title = first_h1_title(path)
    if not title:
        title = filename_title(path)
    return escape_title(title)


def rel_posix(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def ensure_readme(dir_path: Path) -> Path:
    readme = dir_path / "README.md"
    if readme.exists():
        return readme
    title = filename_title(dir_path)
    content = f"# {title}\n"
    readme.write_text(content, encoding="utf-8")
    return readme


def build_items_for_dir(dir_path: Path, order: SummaryOrder) -> List[Item]:
    items: List[Item] = []

    # Files
    for file_path in sorted(dir_path.glob("*.md")):
        if file_path.name == "README.md":
            continue
        if file_path.name == "SUMMARY.md":
            continue
        items.append(Item(title_for(file_path), rel_posix(file_path)))

    # Subdirectories
    for subdir in sorted([p for p in dir_path.iterdir() if p.is_dir()]):
        readme = ensure_readme(subdir)
        child_items = build_items_for_dir(subdir, order)
        items.append(Item(title_for(readme), rel_posix(readme), child_items))

    rel_dir = rel_posix(dir_path)
    return order.sort_items(rel_dir, items)


def render_items(items: Iterable[Item], indent: int = 0) -> List[str]:
    lines: List[str] = []
    for item in items:
        prefix = "  " * indent + "* "
        lines.append(f"{prefix}[{item.title}]({item.path})")
        if item.children:
            lines.extend(render_items(item.children, indent + 1))
    return lines


def build_summary(sections: List[Tuple[str, str]]) -> str:
    order = read_existing_order(SUMMARY_PATH)

    lines: List[str] = ["# Table of contents", ""]

    # Root-level markdown files (excluding SUMMARY.md and section roots).
    root_files = []
    for file_path in sorted(ROOT.glob("*.md")):
        if file_path.name == "SUMMARY.md":
            continue
        root_files.append(Item(title_for(file_path), rel_posix(file_path)))

    root_files = order.sort_items("", root_files)
    lines.extend(render_items(root_files))
    lines.append("")

    for section_title, section_dir in sections:
        section_path = ROOT / section_dir
        if not section_path.exists():
            continue
        lines.append(f"## {section_title}")
        lines.append("")
        section_items = build_items_for_dir(section_path, order)
        lines.extend(render_items(section_items))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_sections_arg(value: str) -> List[Tuple[str, str]]:
    sections: List[Tuple[str, str]] = []
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise argparse.ArgumentTypeError(
                "Sections must be in 'Title:dir' format, separated by commas."
            )
        title, directory = pair.split(":", 1)
        sections.append((title.strip(), directory.strip()))
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate SUMMARY.md")
    parser.add_argument(
        "--sections",
        type=parse_sections_arg,
        default=DEFAULT_SECTIONS,
        help="Comma-separated list of section mappings in 'Title:dir' format.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated SUMMARY.md to stdout instead of writing.",
    )

    args = parser.parse_args()
    content = build_summary(args.sections)

    if args.dry_run:
        print(content)
    else:
        SUMMARY_PATH.write_text(content, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
