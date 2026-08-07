from typing import Any

from pydantic import ValidationError

FIELD_LABELS = {
    "recruitment_status": "募集状況",
    "company_name": "企業名",
    "industry": "業界",
    "sector": "業種",
    "event_name": "イベント名",
    "deadline": "締め切り",
    "event_type": "種別",
    "description": "内容",
    "event_format": "開催形式",
    "location": "開催地",
    "selection_process": "選考フロー",
    "homepage_url": "HPリンク",
    "job_categories": "職種",
    "tags": "タグ／キーワード",
    "event_start_date": "実施開始日",
    "event_end_date": "実施終了日",
    "period_note": "実施期間補足",
    "requirements": "募集要件",
    "compensation": "待遇",
    "graduation_years": "対象卒業年",
    "degrees": "対象学位",
    "audience_note": "対象者補足",
    "recruitment_start_date": "募集開始日",
    "entry_url": "エントリーはこちら",
    "source_url": "情報源",
    "expected_updated_at": "更新前の最終確認日時",
    "collection_target_id": "情報収集対象ID",
    "priority_tier": "収集優先度",
    "check_interval_days": "確認間隔",
    "selection_reason": "選定理由",
    "sources": "公式情報源",
    "source_type": "情報源の種類",
    "url": "公式情報源URL",
    "result": "確認結果",
    "opportunity_id": "募集情報ID",
    "note": "確認メモ",
    "is_active": "有効状態",
}

DATE_FIELDS = {"deadline", "event_start_date", "event_end_date", "recruitment_start_date"}
URL_FIELDS = {"homepage_url", "entry_url", "source_url", "url"}


def pydantic_errors(exc: ValidationError, raw: dict[str, Any]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False):
        key = str(error["loc"][0]) if error["loc"] and error["loc"][0] != "__root__" else "入力全体"
        expected: str | None = None
        example: Any = None
        alternative: str | None = None
        if key in DATE_FIELDS:
            expected = "YYYY-MM-DD形式（2000-01-01から実行日の5年後まで）"
            example = "2026-08-31"
            alternative = "不明な場合はnullとし、補足項目に記載してください"
        elif key in URL_FIELDS:
            expected = "https形式（ホスト名必須、短縮URL・IP直指定不可）"
            example = "https://example.com/recruit"
            if key == "source_url":
                expected = "https形式の一次情報URL（求人サイト・短縮URL・IP直指定不可）"
                alternative = "企業自身の採用ページが見つからない場合は登録を見送ってください"
        formatted.append(
            {
                "field": FIELD_LABELS.get(key, key),
                "received": raw.get(key) if key != "入力全体" else None,
                "reason": error["msg"],
                "expected": expected,
                "example": example,
                "alternative": alternative,
            }
        )
    return formatted


def master_error(field: str, received: Any, available: list[str]) -> dict[str, Any]:
    return {
        "field": FIELD_LABELS.get(field, field),
        "received": received,
        "reason": "定義されていない固定値です",
        "expected": available,
        "example": available[0] if available else None,
        "alternative": "判断できない場合は「不明」または「その他」を選んでください",
    }
