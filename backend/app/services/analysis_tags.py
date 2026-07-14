"""
Extracción determinista de tags a partir del documento final de análisis.

Estas tags priorizan el contenido realmente observado y sintetizado por el
pipeline, de modo que la biblioteca no dependa únicamente de los topics de
GitHub, que pueden faltar o fallar por rate limit.
"""

from __future__ import annotations

import re

_MAX_ANALYSIS_TAGS = 8

_TAG_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("python", (r"\bpython\b", r"\bpyproject\.toml\b", r"\brequirements\.txt\b")),
    ("typescript", (r"\btypescript\b", r"\btsconfig\.json\b")),
    ("javascript", (r"\bjavascript\b", r"\bnode\.js\b", r"\bpackage\.json\b")),
    ("go", (r"\bgolang\b", r"\bgo\b", r"\bgo\.mod\b")),
    ("rust", (r"\brust\b", r"\bcargo\.toml\b")),
    ("fastapi", (r"\bfastapi\b",)),
    ("django", (r"\bdjango\b",)),
    ("flask", (r"\bflask\b",)),
    ("astro", (r"\bastro\b",)),
    ("react", (r"\breact\b",)),
    ("next.js", (r"\bnext\.?js\b",)),
    ("vue", (r"\bvue\b",)),
    ("nuxt", (r"\bnuxt\b",)),
    ("svelte", (r"\bsvelte\b",)),
    ("docker", (r"\bdocker\b", r"\bdocker compose\b", r"\bdocker-compose\b")),
    ("supabase", (r"\bsupabase\b",)),
    ("postgresql", (r"\bpostgres(?:ql)?\b",)),
    ("mysql", (r"\bmysql\b",)),
    ("sqlite", (r"\bsqlite\b",)),
    ("mongodb", (r"\bmongodb\b",)),
    ("redis", (r"\bredis\b",)),
    ("rest-api", (r"\brest\b", r"\bapi http\b", r"\bapi y contratos\b")),
    ("sse", (r"\bsse\b", r"\bserver-sent events?\b")),
    ("github-actions", (r"\bgithub actions\b", r"\.github/workflows\b")),
]


def _normalize_tag(tag: str) -> str:
    """Normaliza una tag al formato usado por la biblioteca."""
    return tag.strip().lower()


def derive_analysis_tags(document: str) -> list[str]:
    """
    Deriva tags semánticas a partir del documento final de análisis.

    La salida es deliberadamente acotada para que la card de biblioteca muestre
    solo las señales más útiles y no una nube ruidosa de keywords.
    """
    haystack = document.casefold()
    tags: list[str] = []

    for tag, patterns in _TAG_PATTERNS:
        if any(re.search(pattern, haystack) for pattern in patterns):
            tags.append(tag)
        if len(tags) >= _MAX_ANALYSIS_TAGS:
            break

    return tags


def merge_tags(*tag_groups: list[str]) -> list[str]:
    """
    Fusiona grupos de tags preservando prioridad y unicidad.

    Los primeros grupos tienen prioridad visual en la biblioteca.
    """
    merged: list[str] = []
    seen: set[str] = set()

    for group in tag_groups:
        for raw_tag in group:
            tag = _normalize_tag(raw_tag)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            merged.append(tag)

    return merged
