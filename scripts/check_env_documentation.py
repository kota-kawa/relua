#!/usr/bin/env python3
"""Verify that ``.env.example`` documents exactly the environment variables the code reads.

Variables are collected from three places:

* ``backend/app/config.py`` — every field of the pydantic ``Settings`` class, upper-cased
* ``frontend/`` — every ``process.env.NAME`` in ``app/``, ``components/``, ``lib/``, ``proxy.ts`` and ``next.config.ts``
* ``docker-compose.yml`` — every ``${NAME...}`` substitution

Variables that are injected by Compose or the platform rather than read from ``.env`` are
listed in ``NOT_FROM_DOTENV`` and are exempt from the "must be documented" check.

The check fails when a variable is read but missing from ``.env.example``, or documented in
``.env.example`` but read nowhere. Run from anywhere:

    python3 scripts/check_env_documentation.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
BACKEND_CONFIG = REPO_ROOT / "backend" / "app" / "config.py"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
FRONTEND_ROOTS = ("frontend/app", "frontend/components", "frontend/lib")
FRONTEND_FILES = ("frontend/proxy.ts", "frontend/next.config.ts")

#: Set by docker-compose.yml / the Dockerfiles / the runtime itself, never by `.env`.
NOT_FROM_DOTENV = {
    "APP_NAME",  # Settings default only; not meant to be configured
    "SITE_URL",  # compose maps NEXT_PUBLIC_SITE_URL onto this backend setting
    "NODE_ENV",  # set by next build / the runner image
    "PORT",  # frontend Dockerfile
    "HOSTNAME",  # frontend Dockerfile
}

ENV_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
SETTINGS_FIELD_RE = re.compile(r"^    ([a-z][a-z0-9_]*):\s", re.MULTILINE)
PROCESS_ENV_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)")
COMPOSE_VAR_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")


def documented_variables() -> set[str]:
    return set(ENV_LINE_RE.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def backend_variables() -> set[str]:
    text = BACKEND_CONFIG.read_text(encoding="utf-8")
    start = text.find("class Settings(")
    if start == -1:
        raise SystemExit("backend/app/config.py: Settings class not found")
    body = text[start:]
    cut = body.find("    @")
    if cut != -1:
        body = body[:cut]
    fields = set(SETTINGS_FIELD_RE.findall(body))
    return {name.upper() for name in fields}


def frontend_variables() -> set[str]:
    names: set[str] = set()
    files: list[Path] = [REPO_ROOT / rel for rel in FRONTEND_FILES]
    for root in FRONTEND_ROOTS:
        files.extend(p for p in (REPO_ROOT / root).rglob("*") if p.suffix in {".ts", ".tsx", ".js", ".mjs"})
    for path in files:
        if not path.is_file():
            continue
        names.update(PROCESS_ENV_RE.findall(path.read_text(encoding="utf-8")))
    return names


def compose_variables() -> set[str]:
    return set(COMPOSE_VAR_RE.findall(COMPOSE_FILE.read_text(encoding="utf-8")))


def main() -> int:
    documented = documented_variables()
    read_by = {
        "backend/app/config.py": backend_variables(),
        "frontend": frontend_variables(),
        "docker-compose.yml": compose_variables(),
    }
    read_anywhere = set().union(*read_by.values())

    problems: list[str] = []
    for source, names in read_by.items():
        for name in sorted(names - documented - NOT_FROM_DOTENV):
            problems.append(f"{name} is read by {source} but missing from .env.example")
    for name in sorted(documented - read_anywhere):
        problems.append(f"{name} is documented in .env.example but read nowhere")

    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} environment documentation problem(s).", file=sys.stderr)
        return 1
    print(f"All {len(documented)} documented environment variables are read, and every read variable is documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
