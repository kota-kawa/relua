#!/usr/bin/env python3
"""Verify that file paths referenced from Markdown documents exist in the repository.

Checks two kinds of references in every tracked ``*.md`` file:

* relative Markdown link targets such as ``[text](./docs/knowledge/debugging.md#section)``
* inline-code path tokens such as ```` `backend/app/main.py` ```` or ```` `.env.example` ````

A token is treated as a path only when it looks like one (no spaces, URL scheme, glob,
shell or template characters) and either contains a ``/`` plus a file extension or trailing
slash, or is a repository-root file with a documentation-style extension. Bare module paths
such as ``next/link`` and URL routes such as ``robots.txt`` therefore do not count, and neither do
bare file names without a directory (``models.py``, ``20260726_0001_initial.py``): only references
that name a location are verified. ADRs whose status is ``Superseded`` describe a past state and
are skipped entirely. Only files tracked by git are scanned, so ``git add`` a new document first. Tokens are resolved against the repository root, the
directory of the document, and a few well-known sub-roots so shorthand like
``services/companies.py`` or ``tests/test_oauth.py`` still resolves.

Exit status is non-zero when any reference does not exist. Run from anywhere:

    python3 scripts/check_doc_paths.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Path segments that are never committed (see .gitignore); a reference through them cannot be
# checked out in CI, whether written as ``backend/.venv`` or ``backend/.venv/bin/pytest``.
UNCHECKABLE_PARTS = {".venv", "node_modules", ".next", ".playwright-mcp", ".env"}

# A token without "/" is only a path when it ends with one of these.
ROOT_FILE_SUFFIXES = (".md", ".yml", ".yaml", ".toml", ".conf", ".example", ".ini", ".json", ".mjs", "Makefile")

# Shorthand roots used by ARCHITECTURE.md and the knowledge docs.
SEARCH_ROOTS = (
    Path("."),
    Path("backend"),
    Path("backend/app"),
    Path("backend/tests"),
    Path("frontend"),
    Path("docs"),
    Path("docs/knowledge"),
    Path("docs/decisions"),
    Path(".github"),
    Path(".github/workflows"),
)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE_RE = re.compile(r"`([^`\n]+)`")
PATH_TOKEN_RE = re.compile(r"^\.?[\w.\-\[\]]+(?:/[\w.\-\[\]]+)*/?$")
SUPERSEDED_RE = re.compile(r"^- Status: Superseded", re.MULTILINE)
FILE_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
# Extension-less files that are still file references when they end a path.
EXTENSIONLESS_FILES = {"Dockerfile", "Makefile"}


def tracked_markdown_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "*.md", "**/*.md"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        files = sorted({REPO_ROOT / line for line in output.splitlines() if line.strip()})
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if not any(part in {".git", "node_modules", ".venv", ".next"} for part in path.parts)
    )


def looks_like_path(token: str) -> bool:
    if not PATH_TOKEN_RE.match(token):
        return False
    if "/" in token:
        # A directory reference ends with "/"; a file reference needs an extension. Anything else
        # (``next/link``, ``fix/topic``) is a module or a name, not a repository path.
        last = token.rsplit("/", 1)[1]
        return token.endswith("/") or last in EXTENSIONLESS_FILES or bool(FILE_EXTENSION_RE.search(last))
    return token.endswith(ROOT_FILE_SUFFIXES)


def is_uncheckable(token: str) -> bool:
    return any(part in UNCHECKABLE_PARTS for part in Path(token).parts)


def resolve(token: str, document: Path) -> bool:
    candidates = [document.parent / token]
    candidates.extend(REPO_ROOT / root / token for root in SEARCH_ROOTS)
    for candidate in candidates:
        if candidate.exists():
            return True
    return False


def check_document(document: Path) -> list[str]:
    text = document.read_text(encoding="utf-8")
    problems: list[str] = []
    if SUPERSEDED_RE.search(text):
        return problems
    seen: set[str] = set()

    for match in LINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if target in seen:
            continue
        seen.add(target)
        if not (document.parent / target).exists():
            problems.append(f"link target not found: {target}")

    for match in CODE_RE.finditer(text):
        token = match.group(1).strip()
        if token in seen or not looks_like_path(token) or is_uncheckable(token):
            continue
        seen.add(token)
        if not resolve(token, document):
            problems.append(f"path not found: {token}")

    return problems


def main() -> int:
    failures = 0
    for document in tracked_markdown_files():
        if not document.is_file():
            print(f"{document.relative_to(REPO_ROOT)}: tracked but missing from disk")
            failures += 1
            continue
        for problem in check_document(document):
            failures += 1
            print(f"{document.relative_to(REPO_ROOT)}: {problem}")
    if failures:
        print(f"\n{failures} unresolved path reference(s).", file=sys.stderr)
        return 1
    print("All documented paths exist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
