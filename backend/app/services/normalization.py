import re
import unicodedata


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
