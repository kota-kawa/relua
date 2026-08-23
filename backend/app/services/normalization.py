import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "utm_campaign",
    "utm_content",
    "utm_creative_format",
    "utm_id",
    "utm_marketing_tactic",
    "utm_medium",
    "utm_source",
    "utm_source_platform",
    "utm_term",
}


def normalize_common(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value.casefold()


def normalize_company_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[（(](?:株)[）)]|㈱", "株式会社", value)
    without_legal = value.replace("株式会社", "").replace("有限会社", "")
    # "・" separates loanword syllables ("ディー・エヌ・エー"), so it varies freely with the
    # unseparated spelling ("ディーエヌエー") and must not distinguish otherwise-identical names.
    without_legal = without_legal.replace("・", "")
    return without_legal.casefold()


def normalize_tag(value: str) -> str:
    value = normalize_common(value)
    return re.sub(r"[\s\-_・/／]+", "", value)


def normalize_source_url(value: str) -> str:
    """Canonicalize an already validated source URL for duplicate warnings.

    Meaningful query parameters are retained because one corporate page can serve several postings.
    Fragments and well-known tracking parameters do not identify different source material.
    """
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host if port is None or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def source_host(value: str) -> str:
    """Return the normalized hostname used by a company's official-source allowlist."""

    host = (urlsplit(value.strip()).hostname or "").casefold().rstrip(".")
    return host.removeprefix("www.")


def source_url_is_allowed(value: str, allowed_urls: list[str]) -> bool:
    """Accept an exact registered source or another page below the same official host.

    Collection sources are deliberately the trust anchor.  The registered host and its child hosts
    are accepted (``company.example`` and ``careers.company.example``), while parent and sibling
    hosts require an explicit source entry.  This avoids broadening an allowlist entry for a hosted
    recruitment service to that service's entire registrable domain, and avoids treating a host as
    official merely because it is absent from the global aggregator denylist.
    """

    normalized = normalize_source_url(value)
    host = source_host(value)
    for allowed in allowed_urls:
        if normalize_source_url(allowed) == normalized:
            return True
        allowed_host = source_host(allowed)
        if host == allowed_host or host.endswith(f".{allowed_host}"):
            return True
    return False
