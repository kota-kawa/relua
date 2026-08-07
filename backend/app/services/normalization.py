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
