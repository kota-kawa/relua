import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic.json_schema import WithJsonSchema

from app.dates import years_ahead_in_tokyo

SHORTENER_HOSTS = {
    "bit.ly",
    "goo.gl",
    "t.co",
    "tinyurl.com",
    "is.gd",
    "ow.ly",
    "buff.ly",
}
#: Job boards, aggregators and review sites. A listing there is part of a database someone else
#: built and whose terms forbid automated reuse, so restating it here trades our own compilation
#: for theirs. Only source_url is checked: citing one of these means the record came from the
#: aggregator, while entry_url may legitimately point at a platform the employer chose to use.
#: Extend as new services appear -- a missing host is a gap, never a false rejection.
AGGREGATOR_HOSTS = {
    "asagaku.com",
    "br-campus.jp",
    "career-tasu.jp",
    "careerpark.jp",
    "doda.jp",
    "en-japan.com",
    "gaishishukatsu.com",
    "goodfind.jp",
    "green-japan.com",
    "indeed.com",
    "internshipguide.jp",
    "jobtalk.jp",
    "kyujinbox.com",
    "labbase.jp",
    "levtech.jp",
    "mynavi.jp",
    "offerbox.jp",
    "onecareer.jp",
    "openwork.jp",
    "paiza.jp",
    "rikunabi.com",
    "supporterz.jp",
    "syukatsu-kaigi.jp",
    "type.jp",
    "unistyleinc.com",
    "wantedly.com",
}
FORBIDDEN_TEXT = re.compile(r"<[^>]+>|!\[[^]]*]\([^)]*\)|\[[^]]+]\(https?://[^)]+\)", re.IGNORECASE)


def validate_https_url(value: str | None) -> str | None:
    if value is None:
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or len(value) > 2048:
        raise ValueError("https形式でホスト名を含む2048文字以内のURLを指定してください")
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        raise ValueError("localhostまたはIPアドレスを直接指定するURLは使用できません")
    if host in SHORTENER_HOSTS:
        raise ValueError("短縮URLは使用できません。元のURLを指定してください")
    return value


def validate_source_host(value: str) -> str:
    host = (urlparse(value).hostname or "").lower()
    # Subdomain match, so job.mynavi.jp is caught by the registrable domain alone.
    if any(host == domain or host.endswith(f".{domain}") for domain in AGGREGATOR_HOSTS):
        raise ValueError(
            "求人サイト・口コミサイトのURLは情報源に指定できません。"
            "企業自身の採用ページなど、一次情報のURLを指定してください"
        )
    return value


def validate_plain_text(value: str | None) -> str | None:
    if value and FORBIDDEN_TEXT.search(value):
        raise ValueError("HTMLタグ、Markdown画像、Markdown形式の外部リンクは使用できません")
    return value


RecruitmentStatusValue = Literal["募集予定", "募集中", "締切", "通年募集", "不明"]
IndustryValue = Literal[
    "IT・通信", "メーカー", "商社", "金融", "コンサル・シンクタンク", "広告・メディア",
    "建設・不動産", "運輸・物流", "医療・製薬", "エネルギー・インフラ", "小売・流通",
    "サービス", "教育", "公務・団体",
]
EventTypeValue = Literal["インターン", "本選考", "説明会・セミナー", "エントリー受付", "イベント", "その他"]
EventFormatValue = Literal["オンライン", "対面", "ハイブリッド", "不明"]
JobCategoryValue = Literal[
    "ソフトウェアエンジニア", "データサイエンティスト", "機械学習エンジニア", "インフラ・SRE",
    "セキュリティ", "研究開発", "生産技術", "品質保証", "営業", "マーケティング", "企画・経営企画",
    "人事", "経理・財務", "法務", "コンサルタント", "デザイナー", "総合職", "事務職", "その他",
]
GraduationYearValue = Literal["26卒", "27卒", "28卒", "29卒", "30卒", "学年不問"]
DegreeValue = Literal["学部", "修士", "博士", "高専", "専門", "不問"]
SortValue = Literal["relevance", "deadline", "updated", "created"]


#: Reused by every optional free-text field so the JSON Schema states the "do not guess" rule once.
UNKNOWN_IS_NULL = "推測できない場合はnullにしてください。"
#: The facts in a posting (dates, pay, who may apply) are free to restate, but the wording carrying
#: them belongs to whoever wrote the source page. Stated per field rather than only in the server
#: instructions, because a client that skips the instructions still reads the payload schema.
NO_VERBATIM = (
    "出典の文章をそのまま転記せず、事実だけを自分の言葉で書いてください。"
    "キャッチコピーや宣伝文など、出典独自の表現は使用しません。"
)
#: Postings often name a recruiter or give a direct contact. Neither is needed to describe an
#: opportunity, and no other field in this service identifies an individual.
NO_PERSONAL_DATA = "担当者名などの個人名と、個人宛のメールアドレス・電話番号は含めません。"
#: A short prompt is easy for an MCP client to follow and keeps descriptions informative without
#: asking it to invent facts that are absent from the primary source.
DESCRIPTION_GUIDANCE = (
    "一言で終わらせず、出典で確認できる範囲で2〜4文（目安100〜300文字）を使って具体的にまとめてください。"
    "「何をする募集か」「主な業務・プログラム内容」「対象者」「実施形式・期間」「経験できること・特徴」から、"
    "確認できた情報をできるだけ含めます。情報がない項目は推測せず省略し、日程・場所・選考・応募要件・報酬は各専用項目にも入力してください。"
)


#: The company profile answers "what does this company do", which a student needs before deciding
#: whether a posting is worth reading. It is deliberately about the business, not a recommendation:
#: relua does not rate companies.
#:
#: Stated per field rather than only in the server instructions, because a client that skips the
#: instructions still reads the payload schema. The minimum lengths below are enforced, so a
#: one-line profile is rejected at the boundary instead of producing a page with nothing on it.
COMPANY_NO_EVALUATION = (
    "将来性・成長性・働きやすさ・優良かどうかなどの評価や見通しは書かないでください。"
    "事業の内容そのものだけを、公式情報で確認できた範囲で書きます。"
)
COMPANY_SUMMARY_GUIDANCE = (
    "この企業が何をしている会社かを1〜2文（30〜200文字）で言い切ってください。"
    "業界名だけ、社名の言い換え、「総合サービス企業です」のような内容のない一文は避け、"
    "扱う製品・サービスと主な顧客が分かる書き方にします（例:「小売業向けにPOSレジと在庫管理システムを"
    "開発・販売し、全国の小売チェーンへ導入している。」）。"
)
COMPANY_DESCRIPTION_GUIDANCE = (
    "企業の事業内容の本文です。一言で終わらせず、300〜1200文字を使って具体的にまとめてください。"
    "「主力事業と収益の源泉」「主な製品・サービスと提供先」「顧客・市場（BtoB／BtoCや業界）」"
    "「事業の規模（売上・従業員数・拠点・シェアなど）」「技術や体制の特徴」「近年の事業展開」から、"
    "公式サイトの会社概要・事業紹介・IR資料などで確認できた情報をできるだけ多く含めます。"
    "確認できない項目は推測せず省略します。"
    "話題が変わるところで空行を入れて段落に分けてください。段落は企業ページでそのまま段落として表示されます。"
)
COMPANY_BUSINESS_AREA_GUIDANCE = (
    "主な事業を事業ごとに分けて登録します。企業ページでは事業ごとの見出し付きブロックとして表示され、"
    "本文を読まなくても事業の全体像が分かる部分になります。"
    "売上や従業員の大きい主要事業から順に並べ、単一事業の企業は1件だけ指定します。"
)


class OpportunityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recruitment_status: Annotated[
        RecruitmentStatusValue,
        Field(description="募集の現在状況。判断できない場合は「不明」。", examples=["募集中"]),
    ]
    company_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        Field(
            description="企業の正式名称。「(株)」などの略記は正規化され、既存企業と自動的に同一視されます。",
            examples=["株式会社リルア"],
        ),
    ]
    industry: Annotated[IndustryValue, Field(description="業界の固定値。", examples=["IT・通信"])]
    sector: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(
            description=(
                "業種の固定値。指定した業界に属する値だけが有効です。"
                "get_sectorsで業界配下の候補を取得してから指定してください。"
            ),
            examples=["Webサービス"],
        ),
    ]
    event_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        Field(description="募集・イベントの名称。企業名は含めません。", examples=["サマーインターン2027"]),
    ]
    deadline: Annotated[
        date | None,
        Field(description=f"応募締め切り日（YYYY-MM-DD）。{UNKNOWN_IS_NULL}", examples=["2026-08-31"]),
    ] = None
    event_type: Annotated[EventTypeValue, Field(description="募集の種別。", examples=["インターン"])]
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
        Field(
            description=(
                f"募集内容の説明。{DESCRIPTION_GUIDANCE}{NO_VERBATIM}{NO_PERSONAL_DATA}"
                "HTMLタグ、Markdown画像、Markdownリンクは使用できません。"
            ),
            examples=[
                "Webサービスの企画・開発課題に取り組む2週間の実務型インターンです。"
                "社員のサポートを受けながらチームで要件整理から実装、成果発表まで行い、"
                "現場の開発プロセスを体験できます。対象は情報系を学ぶ学生です。"
            ],
        ),
    ]
    event_format: Annotated[EventFormatValue, Field(description="開催形式。", examples=["オンライン"])]
    location: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None,
        Field(
            description=f"開催地。開催形式がオンラインの場合は必ずnullにしてください。{UNKNOWN_IS_NULL}",
            examples=["東京都渋谷区"],
        ),
    ] = None
    selection_process: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
        Field(
            description=f"選考フロー。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["書類選考→面接1回"],
        ),
    ] = None
    homepage_url: Annotated[
        str | None,
        Field(description=f"企業または募集のHP（https必須）。{UNKNOWN_IS_NULL}", examples=["https://example.com/"]),
    ] = None
    job_categories: Annotated[
        list[JobCategoryValue],
        Field(min_length=1, description="対象職種の固定値。1件以上、重複不可。", examples=[["ソフトウェアエンジニア"]]),
    ]
    tags: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]],
        Field(max_length=10, description="自由記述のキーワード。最大10件、1件20文字以内。", examples=[["長期", "有給"]]),
    ] = []
    event_start_date: Annotated[
        date | None,
        Field(description=f"実施開始日（YYYY-MM-DD）。{UNKNOWN_IS_NULL}", examples=["2026-09-01"]),
    ] = None
    event_end_date: Annotated[
        date | None,
        Field(description=f"実施終了日（YYYY-MM-DD）。実施開始日以降。{UNKNOWN_IS_NULL}", examples=["2026-09-14"]),
    ] = None
    period_note: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None,
        Field(description=f"実施期間の補足。{NO_VERBATIM}{UNKNOWN_IS_NULL}", examples=["全5日間、平日のみ"]),
    ] = None
    requirements: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
        Field(
            description=f"応募要件。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["Python実務経験があると望ましい"],
        ),
    ] = None
    compensation: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None,
        Field(
            description=f"報酬・待遇。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["日給10,000円、交通費支給"],
        ),
    ] = None
    graduation_years: Annotated[
        list[GraduationYearValue],
        Field(min_length=1, description="対象卒業年の固定値。1件以上、重複不可。", examples=[["28卒"]]),
    ]
    degrees: Annotated[
        list[DegreeValue],
        Field(min_length=1, description="対象学位の固定値。1件以上、重複不可。", examples=[["学部", "修士"]]),
    ]
    audience_note: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None,
        Field(
            description=f"対象者の補足。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["情報系学部生歓迎"],
        ),
    ] = None
    recruitment_start_date: Annotated[
        date | None,
        Field(description=f"募集開始日（YYYY-MM-DD）。締め切り以前。{UNKNOWN_IS_NULL}", examples=["2026-06-01"]),
    ] = None
    entry_url: Annotated[
        str | None,
        Field(description=f"応募ページのURL（https必須）。{UNKNOWN_IS_NULL}", examples=["https://example.com/entry"]),
    ] = None
    source_url: Annotated[
        str,
        Field(
            description=(
                "情報の出典URL（https必須）。企業自身の採用ページなど、一次情報のURLを指定してください。"
                "求人サイト・就活情報サイト・口コミサイト、短縮URL、IP直指定は使用できません。"
            ),
            examples=["https://example.com/recruit/intern"],
        ),
    ]

    @field_validator("homepage_url", "entry_url", "source_url")
    @classmethod
    def https_urls(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator("source_url")
    @classmethod
    def citable_source(cls, value: str) -> str:
        return validate_source_host(value)

    @field_validator(
        "event_name",
        "description",
        "location",
        "selection_process",
        "period_note",
        "requirements",
        "compensation",
        "audience_note",
    )
    @classmethod
    def plain_text(cls, value: str | None) -> str | None:
        return validate_plain_text(value)

    @field_validator("job_categories", "tags", "graduation_years", "degrees")
    @classmethod
    def no_duplicates(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("同じ値を重複して指定できません")
        return values

    @model_validator(mode="after")
    def related_fields(self) -> "OpportunityInput":
        if self.event_start_date and self.event_end_date and self.event_end_date < self.event_start_date:
            raise ValueError("実施終了日は実施開始日以降にしてください")
        if self.recruitment_start_date and self.deadline and self.deadline < self.recruitment_start_date:
            raise ValueError("締め切りは募集開始日以降にしてください")
        if self.event_format == "オンライン" and self.location:
            raise ValueError("開催形式がオンラインの場合、開催地はnullにしてください")
        # years_ahead_in_tokyo, not date.today().replace(year=...): the latter raises "day is out of
        # range for month" on a leap day (2028-02-29 -> 2033), which would fail *every* write with an
        # unrelated 422, and it reads the server's local date instead of the JST business day.
        limit = years_ahead_in_tokyo(5)
        for field_name in ("deadline", "event_start_date", "event_end_date", "recruitment_start_date"):
            value = getattr(self, field_name)
            if value and not (date(2000, 1, 1) <= value <= limit):
                raise ValueError(f"{field_name}は2000-01-01から実行日の5年後までにしてください")
        return self


class OpportunityUpdate(OpportunityInput):
    """MVP updates are full replacements to preserve all-field validation."""


class MasterItem(BaseModel):
    id: int
    slug: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class SectorItem(MasterItem):
    industry_id: int


class CompanyItem(BaseModel):
    id: int
    name: str
    public_code: str
    url: str = Field(description="企業ページの公開URL。")


class MastersResponse(BaseModel):
    recruitment_statuses: list[MasterItem]
    industries: list[MasterItem]
    sectors: list[SectorItem]
    event_types: list[MasterItem]
    event_formats: list[MasterItem]
    job_categories: list[MasterItem]
    graduation_years: list[MasterItem]
    degrees: list[MasterItem]


class OpportunityResponse(BaseModel):
    id: str
    public_code: str
    url: str
    recruitment_status: MasterItem
    company: CompanyItem
    industry: MasterItem
    sector: MasterItem
    event_name: str
    deadline: date | None
    event_type: MasterItem
    description: str
    event_format: MasterItem
    location: str | None
    selection_process: str | None
    homepage_url: str | None
    job_categories: list[MasterItem]
    tags: list[str]
    event_start_date: date | None
    event_end_date: date | None
    period_note: str | None
    requirements: str | None
    compensation: str | None
    graduation_years: list[MasterItem]
    degrees: list[MasterItem]
    audience_note: str | None
    recruitment_start_date: date | None
    entry_url: str | None
    source_url: str
    created_at: datetime
    updated_at: datetime
    source_checked_at: datetime | None = Field(
        default=None, description="公式情報（source_url）を最後に確認できた日時。未確認の古いレコードはnull。"
    )


class OpportunityListResponse(BaseModel):
    items: list[OpportunityResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


RequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=100),
    Field(
        description=(
            "操作ごとにクライアントが発行する一意なID（8〜100文字）。"
            "同じ操作を再試行するときだけ同じ値を使うと、二重登録されずに前回の結果が返ります。"
        ),
        examples=["chatgpt-20260806-0001"],
    ),
]
ClientName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    Field(description="監査ログとレート制限に記録される呼び出し元の名前。", examples=["chatgpt"]),
]

CollectionSourceType = Literal["recruit", "internship", "event", "news", "other"]
CollectionCheckResult = Literal["found", "no_opening", "unreachable", "needs_review"]
CollectionTargetCheckStatus = Literal[
    "unreviewed", "found", "no_active_opportunity", "source_unavailable", "needs_review"
]


class CollectionSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Annotated[
        CollectionSourceType,
        Field(description="公式ページの種類。recruit=採用総合、internship=インターン、event=イベント、news=告知。"),
    ]
    url: Annotated[
        str,
        Field(description="企業自身が公開する一次情報のURL（https必須）。"),
    ]

    @field_validator("url")
    @classmethod
    def official_source_url(cls, value: str) -> str:
        return validate_source_host(validate_https_url(value) or value)


class CompanyIndustryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    industry: Annotated[IndustryValue, Field(description="企業が属する業界。")]
    sector: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(description="業界配下の業種。まだ判断できない場合はnull。"),
    ] = None


#: Kept as its own annotated type because create and update describe the same list identically.
CompanyIndustries = Annotated[
    list[CompanyIndustryInput],
    Field(
        min_length=1,
        max_length=14,
        description=(
            "企業が属する業界と業種。事業が複数業界にまたがる企業は複数指定します"
            "（例: Ubieは IT・通信/AI と 医療・製薬/ヘルスケア）。先頭が代表の業界として扱われます。"
        ),
    ),
]


class CompanyIndustryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_id: Annotated[int, Field(ge=1, description="カテゴリを設定する既存CompanyのID。resolve_companyで確認します。")]
    industries: CompanyIndustries
    request_id: RequestId
    client_name: ClientName = "mcp-client"


#: The profile fields a caller may write. Shared with the write service so the tool, the schema and
#: the audit snapshot cannot drift apart on what counts as profile content.
COMPANY_PROFILE_FIELD_NAMES = frozenset({"business_summary", "description", "business_areas", "website_url"})


class CompanyBusinessAreaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=2, max_length=60),
        Field(
            description="事業の名称。公式サイトの事業区分に合わせます（例:「産業用センサー事業」）。",
            examples=["産業用センサー事業"],
        ),
    ]
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=60, max_length=400),
        Field(
            description=(
                "その事業が何を作り、誰に提供しているかを60〜400文字で説明します。"
                "製品・サービス名、提供先、規模のうち確認できたものを含めます。"
            )
        ),
    ]

    @field_validator("name", "description")
    @classmethod
    def plain_text(cls, value: str) -> str:
        return validate_plain_text(value) or value


#: A profile carries the company's main businesses; more than six reads as a list of every product
#: line rather than an overview of the company.
CompanyBusinessAreas = Annotated[
    list[CompanyBusinessAreaInput],
    Field(min_length=1, max_length=6, description=COMPANY_BUSINESS_AREA_GUIDANCE),
]


class CompanyProfileUpdateRequest(BaseModel):
    """A patch: an omitted field keeps its stored value, an explicit null clears it.

    Every text field has an enforced minimum length, so the profile a company page shows is either
    absent or substantial. business_areas is the one exception to patching: like a company's industry
    list, the value given replaces the stored set completely.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_id: Annotated[
        int, Field(ge=1, description="プロフィールを更新する既存CompanyのID。resolve_companyで確認します。")
    ]
    business_summary: Annotated[
        str | None,
        Field(
            default=None,
            min_length=30,
            max_length=200,
            description=(
                f"企業の一言説明。{COMPANY_SUMMARY_GUIDANCE}{COMPANY_NO_EVALUATION}{NO_VERBATIM}"
                "削除する場合だけnullを明示し、変更しない場合は項目自体を省略してください。"
            ),
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            default=None,
            min_length=300,
            max_length=4000,
            description=(
                f"企業の事業内容。{COMPANY_DESCRIPTION_GUIDANCE}{COMPANY_NO_EVALUATION}"
                f"{NO_VERBATIM}{NO_PERSONAL_DATA}"
                "削除する場合だけnullを明示し、変更しない場合は項目自体を省略してください。"
            ),
        ),
    ] = None
    business_areas: Annotated[
        CompanyBusinessAreas | None,
        Field(
            default=None,
            description=(
                f"主な事業の一覧。{COMPANY_BUSINESS_AREA_GUIDANCE}"
                "指定した内容で全置換します。削除する場合だけnullを明示し、変更しない場合は項目自体を省略してください。"
            ),
        ),
    ] = None
    website_url: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "企業の公式サイトURL（https必須）。"
                "削除する場合だけnullを明示し、変更しない場合は項目自体を省略してください。"
            ),
        ),
    ] = None
    source_url: Annotated[
        str,
        Field(
            description=(
                "この内容を確認した企業自身のページURL（会社概要・事業紹介など）。"
                "求人サイト・口コミサイトは指定できません。"
            ),
        ),
    ]
    request_id: RequestId
    client_name: ClientName = "mcp-client"

    @field_validator("business_summary", "description")
    @classmethod
    def plain_profile_text(cls, value: str | None) -> str | None:
        # str_strip_whitespace has already run, so a whitespace-only value arrives as "".
        return validate_plain_text(value) or None

    @field_validator("website_url")
    @classmethod
    def official_website_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        return validate_source_host(validate_https_url(value) or value)

    @field_validator("source_url")
    @classmethod
    def official_source_url(cls, value: str) -> str:
        return validate_source_host(validate_https_url(value) or value)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "CompanyProfileUpdateRequest":
        if not COMPANY_PROFILE_FIELD_NAMES & self.model_fields_set:
            raise ValueError(
                "business_summary、description、business_areas、website_urlのいずれかを指定してください"
            )
        return self


class CollectionTargetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_id: Annotated[
        int | None,
        Field(
            default=None,
            ge=1,
            description="既存CompanyのID。resolve_companyまたはlist_unmonitored_companiesが返すIDを指定する場合はcompany_nameを省略します。",
        ),
    ] = None
    company_name: Annotated[
        str | None,
        StringConstraints(min_length=1, max_length=200),
        Field(description="新規企業として追加する正式名。既存Companyを指定するcompany_idとは併用できません。"),
    ] = None
    industries: CompanyIndustries
    priority_tier: Annotated[int, Field(ge=1, le=3, description="内部の収集優先度。1が最優先、3が低優先。")]
    check_interval_days: Annotated[int, Field(ge=1, le=365, description="公式ページを再確認する間隔。")]
    selection_reason: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=500),
        Field(description="収集対象に含める内部運用上の理由。企業の評価には使用しません。"),
    ] = None
    sources: Annotated[
        list[CollectionSourceInput],
        Field(min_length=1, max_length=20, description="確認する企業公式ページ。1件以上指定します。"),
    ]
    request_id: RequestId
    client_name: ClientName = "mcp-client"

    @field_validator("selection_reason")
    @classmethod
    def plain_reason(cls, value: str | None) -> str | None:
        return validate_plain_text(value)

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, sources: list[CollectionSourceInput]) -> list[CollectionSourceInput]:
        if len({source.url for source in sources}) != len(sources):
            raise ValueError("同じURLを重複して指定できません")
        return sources

    @model_validator(mode="after")
    def has_exactly_one_company_reference(self) -> "CollectionTargetCreateRequest":
        if (self.company_id is None) == (self.company_name is None):
            raise ValueError("company_idまたはcompany_nameのどちらか一方を指定してください")
        return self


class CollectionTargetUpdateRequest(BaseModel):
    """A real patch: omitted values stay unchanged.

    `industries` is the exception - it replaces the company's classifications wholesale, so adding
    an industry means sending the existing ones alongside it. Anything else would make "remove a
    misclassification" impossible to express.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_name: Annotated[str | None, StringConstraints(min_length=1, max_length=200)] = None
    industries: CompanyIndustries | None = None
    priority_tier: Annotated[int | None, Field(ge=1, le=3)] = None
    check_interval_days: Annotated[int | None, Field(ge=1, le=365)] = None
    selection_reason: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    is_active: bool | None = None
    request_id: RequestId
    client_name: ClientName = "mcp-client"

    @field_validator("selection_reason")
    @classmethod
    def plain_reason(cls, value: str | None) -> str | None:
        return validate_plain_text(value)

    @model_validator(mode="after")
    def has_change(self) -> "CollectionTargetUpdateRequest":
        editable = {
            "company_name",
            "industries",
            "priority_tier",
            "check_interval_days",
            "selection_reason",
            "is_active",
        }
        if not self.model_fields_set.intersection(editable):
            raise ValueError("更新する項目を1件以上指定してください")
        return self


class CollectionSourceCreateRequest(CollectionSourceInput):
    request_id: RequestId
    client_name: ClientName = "mcp-client"


class CollectionSourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: CollectionSourceType | None = None
    url: str | None = None
    is_active: bool | None = None
    request_id: RequestId
    client_name: ClientName = "mcp-client"

    @field_validator("url")
    @classmethod
    def official_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_source_host(validate_https_url(value) or value)

    @model_validator(mode="after")
    def has_change(self) -> "CollectionSourceUpdateRequest":
        if not self.model_fields_set.intersection({"source_type", "url", "is_active"}):
            raise ValueError("更新する項目を1件以上指定してください")
        return self


class CollectionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    result: Annotated[
        CollectionCheckResult,
        Field(
            description="found=募集を発見、no_opening=募集中なし、unreachable=確認不能、needs_review=人の確認が必要。"
        ),
    ]
    source_url: Annotated[
        str,
        Field(description="実際に確認したURL。foundでは募集のsource_url、その他では登録済み公式sourceを指定します。"),
    ]
    opportunity_id: str | None = None
    note: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    discovered_sources: Annotated[
        list[CollectionSourceInput],
        Field(
            max_length=20,
            description=(
                "確認中に見つけた企業公式ページ。企業トップページしか登録されていない対象で採用ページや"
                "インターンページを見つけたら、ここへ渡すとそのまま情報源として追加されます。登録済みURLは無視します。"
            ),
        ),
    ] = []
    request_id: RequestId
    client_name: ClientName = "mcp-client"

    @field_validator("discovered_sources")
    @classmethod
    def unique_discovered_sources(cls, sources: list[CollectionSourceInput]) -> list[CollectionSourceInput]:
        if len({source.url for source in sources}) != len(sources):
            raise ValueError("同じURLを重複して指定できません")
        return sources

    @field_validator("source_url")
    @classmethod
    def checked_source_url(cls, value: str) -> str:
        return validate_source_host(validate_https_url(value) or value)

    @model_validator(mode="after")
    def result_matches_opportunity(self) -> "CollectionCheckRequest":
        if self.result == "found" and self.opportunity_id is None:
            raise ValueError("foundでは確認したopportunity_idを指定してください")
        if self.result != "found" and self.opportunity_id is not None:
            raise ValueError("opportunity_idはfoundの場合だけ指定できます")
        return self

    @field_validator("note")
    @classmethod
    def plain_note(cls, value: str | None) -> str | None:
        return validate_plain_text(value)


def _inline_model_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline nested definitions because FastMCP wraps a tool payload below its own root schema."""

    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value: Any) -> Any:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                return inline(definitions[reference.rsplit("/", 1)[-1]])
            return {key: inline(item) for key, item in value.items()}
        if isinstance(value, list):
            return [inline(item) for item in value]
        return value

    return inline(schema)


CollectionTargetCreatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CollectionTargetCreateRequest)),
    Field(description="追加する収集対象の企業、所属業界、公式情報源、冪等化情報。"),
]
CompanyIndustryUpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CompanyIndustryUpdateRequest)),
    Field(description="既存企業へ登録する業界・業種カテゴリの一覧。指定した内容で全置換します。"),
]
CompanyProfileUpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CompanyProfileUpdateRequest)),
    Field(description="既存企業の事業内容・公式サイトURLと、それを確認した公式ページ。指定した項目だけを更新します。"),
]
CollectionTargetUpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CollectionTargetUpdateRequest)),
    Field(description="変更する収集対象の項目だけを含む部分更新。industriesは指定した内容で全置換します。"),
]
CollectionSourceCreatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CollectionSourceCreateRequest)),
    Field(description="収集対象へ追加する企業公式ページ。"),
]
CollectionSourceUpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CollectionSourceUpdateRequest)),
    Field(description="変更する公式ページの項目だけを含む部分更新。"),
]
CollectionCheckPayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_inline_model_schema(CollectionCheckRequest)),
    Field(description="公式ページを確認した結果。募集がなかった場合も記録します。"),
]


class MCPWriteRequest(OpportunityInput):
    request_id: RequestId
    client_name: ClientName = "mcp-client"


class MCPUpdateRequest(OpportunityUpdate):
    request_id: RequestId
    client_name: ClientName = "mcp-client"


#: MCP tools take the write payload as a plain dict carrying the model's own JSON Schema.
#: A typed parameter would make FastMCP validate the arguments itself and answer with a raw pydantic
#: message, bypassing the structured field/expected/example errors an agent can act on. Publishing the
#: schema separately keeps the enums and descriptions visible while validation stays in our hands.
WritePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(MCPWriteRequest.model_json_schema()),
    Field(
        description=(
            "登録する募集情報の全項目。固定値はget_master_values／get_sectorsのnameを指定します。"
            f"{DESCRIPTION_GUIDANCE}"
        )
    ),
]
UpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(MCPUpdateRequest.model_json_schema()),
    Field(
        description=(
            "更新後の全項目。部分更新ではないため、変更しない項目も現在値を必ず含めてください。"
            f"descriptionを変更する場合は、{DESCRIPTION_GUIDANCE}"
        )
    ),
]

_opportunity_patch_schema = OpportunityInput.model_json_schema()
_opportunity_patch_schema["required"] = []
_opportunity_patch_schema["title"] = "OpportunityPatch"
OpportunityPatchPayload = Annotated[
    dict[str, Any],
    WithJsonSchema(_opportunity_patch_schema),
    Field(
        description=(
            "変更する募集情報の項目だけを指定します。省略した項目は現在値を維持します。"
            f"descriptionを変更する場合は、{DESCRIPTION_GUIDANCE}"
        )
    ),
]


class ErrorItem(BaseModel):
    field: str
    received: Any = None
    reason: str
    expected: str | list[str] | None = None
    example: Any = None
    alternative: str | None = None
    #: Set when the failure points at a record that already exists, so the client can update it instead.
    existing: list[dict[str, Any]] | None = None


class ValidationErrorResponse(BaseModel):
    error: str = "validation_failed"
    message: str = "入力内容を修正して再試行してください"
    errors: list[ErrorItem]


class OpportunitySummary(BaseModel):
    """Search-result shape. Free-text fields are trimmed; get_opportunityが全文を返します。"""

    id: str
    public_code: str
    url: str
    company_name: str
    event_name: str
    recruitment_status: str
    event_type: str
    event_format: str
    industry: str
    sector: str
    deadline: date | None
    location: str | None
    description_excerpt: str
    job_categories: list[str]
    graduation_years: list[str]
    degrees: list[str]
    tags: list[str]
    entry_url: str | None
    source_url: str
    updated_at: datetime
    source_checked_at: datetime | None = Field(
        default=None, description="公式情報（source_url）を最後に確認できた日時。未確認の古いレコードはnull。"
    )


class MCPSearchResponse(BaseModel):
    items: list[OpportunitySummary]
    total: int
    per_page: int
    next_cursor: str | None = Field(
        description="続きがある場合のカーソル。次のsearch_opportunityへ同じ検索条件とともにそのまま渡します。"
    )


class MCPStaleOpportunityListResponse(BaseModel):
    items: list["OpportunityReviewSummary"]


class OpportunityReviewSummary(OpportunitySummary):
    review_reasons: list[
        Literal["deadline_passed_while_open", "event_ended_while_open", "source_not_checked_recently"]
    ] = Field(
        description=(
            "要確認になった理由。対象は募集予定・募集中・通年募集だけです。期限・実施終了日と"
            "「募集中」の矛盾は、情報源の未確認より優先して返します。"
        )
    )


class MCPWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    opportunity: OpportunityResponse
    warnings: list[ErrorItem] = []


class MCPUpsertResponse(BaseModel):
    result: Literal["created", "existing"]
    #: Carried here for the same reason as on every other write response: without it a retry that the
    #: idempotency record already absorbed is indistinguishable from a fresh create, and an agent that
    #: resends the same request_id after a timeout concludes it has written two records.
    idempotent_replay: bool = False
    message: str
    opportunity: OpportunityResponse
    warnings: list[ErrorItem] = []


class OpportunityDeletionSummary(BaseModel):
    id: str
    public_code: str
    company_name: str
    event_name: str
    source_url: str


class MCPDeletePreviewResponse(BaseModel):
    valid: bool
    message: str
    opportunity: OpportunityDeletionSummary
    expected_updated_at: datetime
    linked_collection_checks: int
    effects: list[str]


class DeletedOpportunity(OpportunityDeletionSummary):
    deleted_at: datetime


class MCPDeleteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    deleted: DeletedOpportunity


class MCPRestoreResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    opportunity: OpportunityResponse


class MCPDuplicateResponse(BaseModel):
    message: str
    matches: list[OpportunitySummary]


class MCPValidationResponse(BaseModel):
    valid: bool
    message: str
    duplicates: list[OpportunitySummary]
    warnings: list[ErrorItem] = []


class CompanyBusinessAreaItem(BaseModel):
    name: str
    description: str


class CompanyAliasResponse(BaseModel):
    id: int
    alias: str
    normalized_alias: str


class CompanyIndustryItem(BaseModel):
    industry: MasterItem
    sector: MasterItem | None
    is_primary: bool


class CompanyIdentityResponse(BaseModel):
    id: int
    public_code: str
    url: str = Field(description="企業ページの公開URL。")
    canonical_name: str
    normalized_name: str
    business_summary: str | None = Field(
        default=None, description="この企業が何をしている会社かを1〜2文でまとめたもの。未登録はnull。"
    )
    description: str | None = Field(default=None, description="運営者が公式情報から記録した事業内容の本文。未登録はnull。")
    business_areas: list[CompanyBusinessAreaItem] = Field(
        default_factory=list, description="主な事業。売上や規模の大きい順。未登録は空配列。"
    )
    website_url: str | None = None
    updated_at: datetime | None = None
    aliases: list[CompanyAliasResponse]
    industries: list[CompanyIndustryItem] = Field(
        default_factory=list,
        description="企業に登録された業界・業種カテゴリ。先頭のis_primary=trueが代表カテゴリです。",
    )


class CompanyCandidateResponse(BaseModel):
    company: CompanyIdentityResponse
    match_type: Literal["canonical_exact", "alias_exact", "partial", "fuzzy"]
    matched_name: str
    score: float = Field(ge=0, le=1)


class MCPCompanyResolutionResponse(BaseModel):
    query: str
    normalized_query: str
    match_type: Literal["canonical_exact", "alias_exact", "partial", "fuzzy", "none"]
    requires_confirmation: bool
    message: str
    candidates: list[CompanyCandidateResponse]


class MCPCompanyAliasWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    changed: bool
    message: str
    company: CompanyIdentityResponse


class MCPCompanyIndustryWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    company: CompanyIdentityResponse


class MCPCompanyProfileWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    changed: bool
    message: str
    company: CompanyIdentityResponse


class CompanyMergeSummary(BaseModel):
    opportunities_moved: int
    aliases_moved: int
    aliases_deduplicated: int
    industries_moved: int
    industries_deduplicated: int
    company_request_records_moved: int
    collection_targets_merged: int
    collection_sources_moved: int
    collection_sources_deduplicated: int
    collection_checks_moved: int


class MCPCompanyMergeResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    source_company_id: int
    target_company: CompanyIdentityResponse
    migration: CompanyMergeSummary


class OpportunityFieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class MCPOpportunityPreviewResponse(BaseModel):
    valid: bool
    message: str
    expected_updated_at: datetime
    changes: list[OpportunityFieldChange]
    warnings: list[ErrorItem]
    merged_payload: dict[str, Any]


class MCPSectorsResponse(BaseModel):
    industry: MasterItem
    sectors: list[MasterItem]


class MCPWriteHistoryItem(BaseModel):
    action: str
    request_id: str | None
    client_name: str
    success: bool
    opportunity_id: str | None
    url: str | None
    source_url: str | None
    errors: list[dict[str, Any]] | None
    created_at: datetime


class MCPWriteHistoryResponse(BaseModel):
    items: list[MCPWriteHistoryItem]


class CollectionSourceResponse(BaseModel):
    id: int
    source_type: CollectionSourceType
    url: str
    is_active: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CollectionOpportunityReference(BaseModel):
    id: str
    public_code: str
    url: str
    event_name: str
    recruitment_status: str
    source_url: str
    updated_at: datetime


class CompanyMaintenanceOpportunity(BaseModel):
    id: str
    public_code: str
    url: str
    event_name: str
    recruitment_status: str
    graduation_years: list[str]
    deadline: date | None
    event_end_date: date | None
    source_url: str
    source_checked_at: datetime | None
    updated_at: datetime


class MCPCompanyMaintenanceContextResponse(BaseModel):
    company: CompanyIdentityResponse
    collection_target_id: int | None = Field(
        default=None, description="情報収集対象が未作成の場合はnullです。"
    )
    collection_last_checked_at: datetime | None = Field(
        default=None, description="企業単位の収集対象を最後に確認した日時。"
    )
    official_sources: list[CollectionSourceResponse] = Field(
        description="企業単位で登録した公式ページ。収集対象が未作成の場合は空です。"
    )
    opportunities: list[CompanyMaintenanceOpportunity] = Field(
        description=(
            "この企業の定期再確認対象（募集予定・募集中・通年募集）だけを返します。"
            "締切などの終了状態は含まず、各募集の一次情報URLと最終確認日時を含みます。"
        )
    )


class CollectionTargetResponse(BaseModel):
    id: int
    company: CompanyItem
    industries: list[CompanyIndustryItem]
    primary_industry: MasterItem | None
    primary_sector: MasterItem | None
    priority_tier: int
    check_interval_days: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    last_check_result: CollectionCheckResult | None
    check_status: CollectionTargetCheckStatus
    last_found_at: datetime | None
    is_active: bool
    selection_reason: str | None
    sources: list[CollectionSourceResponse]
    has_primary_source: bool
    missing_source_types: list[CollectionSourceType]
    opportunities: list[CollectionOpportunityReference] = Field(
        description=(
            "定期再確認対象（募集予定・募集中・通年募集）の募集だけを返します。"
            "締切などの終了状態は含みません。"
        )
    )
    company_opportunity_count: int
    created_at: datetime
    updated_at: datetime


class MCPCollectionTargetListResponse(BaseModel):
    items: list[CollectionTargetResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class UnmonitoredCompanyResponse(CompanyIdentityResponse):
    industries: list[CompanyIndustryItem]
    company_opportunity_count: int
    created_at: datetime


class MCPUnmonitoredCompanyListResponse(BaseModel):
    items: list[UnmonitoredCompanyResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class MCPCollectionQueueResponse(BaseModel):
    items: list[CollectionTargetResponse]


class MCPCollectionWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    target: CollectionTargetResponse


class MCPCollectionSourceWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    source: CollectionSourceResponse


class CollectionCheckResponse(BaseModel):
    id: int
    collection_target_id: int
    result: CollectionCheckResult
    checked_at: datetime
    source_url: str | None
    opportunity_id: str | None
    request_id: str
    client_name: str
    note: str | None


class MCPCollectionCheckWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    check: CollectionCheckResponse
    target: CollectionTargetResponse


class MCPCollectionCheckListResponse(BaseModel):
    items: list[CollectionCheckResponse]


class CompanySummaryResponse(BaseModel):
    """A company as the public company pages and their listing need it."""

    id: int
    public_code: str
    url: str
    name: str
    business_summary: str | None
    description: str | None
    business_areas: list[CompanyBusinessAreaItem]
    website_url: str | None
    industries: list[CompanyIndustryItem]
    current_opportunity_count: int
    #: Newest update among the company's current openings. Company.updated_at only moves when the
    #: profile itself is edited, so this is what tells a sitemap the page content changed.
    openings_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CompanyDetailResponse(CompanySummaryResponse):
    current_opportunities: list[OpportunityResponse]
    past_opportunities: list[OpportunityResponse]


class CompanyListResponse(BaseModel):
    items: list[CompanySummaryResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
