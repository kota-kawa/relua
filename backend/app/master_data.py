from sqlalchemy import Connection, insert

from app.models import Degree, EventFormat, EventType, GraduationYear, Industry, JobCategory, RecruitmentStatus, Sector

INDUSTRY_SECTORS = {
    "IT・通信": ["ソフトウェア", "Webサービス", "SIer・ITコンサル", "通信キャリア", "ハードウェア", "AI"],
    "メーカー": ["電機・精密", "自動車・輸送機器", "機械", "化学", "素材", "食品", "日用品"],
    "商社": ["総合商社", "専門商社"],
    "金融": ["銀行", "証券", "保険", "資産運用", "クレジット・決済"],
    "コンサル・シンクタンク": ["戦略コンサル", "総合コンサル", "ITコンサル", "シンクタンク"],
    "広告・メディア": ["広告代理店", "出版", "放送", "エンタメ"],
    "建設・不動産": ["建設", "住宅", "不動産開発", "不動産仲介"],
    "運輸・物流": ["陸運", "海運", "空運", "倉庫・物流"],
    "医療・製薬": ["製薬", "医療機器", "ヘルスケア"],
    "エネルギー・インフラ": ["電力", "ガス", "石油", "鉄道"],
    "小売・流通": ["百貨店", "スーパー・コンビニ", "専門店", "EC"],
    "サービス": ["人材", "旅行・ホテル", "外食", "警備・メンテナンス"],
    "教育": ["学校法人", "教育サービス"],
    "公務・団体": ["官公庁", "地方自治体", "独立行政法人", "業界団体"],
}

JOB_CATEGORIES = [
    "ソフトウェアエンジニア", "データサイエンティスト", "機械学習エンジニア", "インフラ・SRE",
    "セキュリティ", "研究開発", "生産技術", "品質保証", "営業", "マーケティング", "企画・経営企画",
    "人事", "経理・財務", "法務", "コンサルタント", "デザイナー", "総合職", "事務職", "その他",
]


def slug(prefix: str, index: int) -> str:
    return f"{prefix}-{index:02d}"


def seed_masters(bind: Connection) -> None:
    industries = [
        {"id": i, "slug": slug("industry", i), "name": name, "sort_order": i, "is_active": True}
        for i, name in enumerate(INDUSTRY_SECTORS, 1)
    ]
    bind.execute(insert(Industry), industries)

    sectors = []
    sector_id = 1
    for industry_id, values in enumerate(INDUSTRY_SECTORS.values(), 1):
        for value in [*values, "その他"]:
            # AI was added after the initial release. Keep every existing ID
            # and slug stable so fresh databases match upgraded databases.
            is_ai = industry_id == 1 and value == "AI"
            stable_id = 71 if is_ai else sector_id
            sort_order = 6 if is_ai else 7 if industry_id == 1 and value == "その他" else stable_id
            sectors.append(
                {
                    "id": stable_id,
                    "slug": slug(f"sector-{industry_id}", stable_id),
                    "name": value,
                    "sort_order": sort_order,
                    "is_active": True,
                    "industry_id": industry_id,
                }
            )
            if not is_ai:
                sector_id += 1
    bind.execute(insert(Sector), sectors)

    groups = [
        (RecruitmentStatus, ["募集予定", "募集中", "締切", "通年募集", "不明"], "status"),
        (EventType, ["インターン", "本選考", "説明会・セミナー", "エントリー受付", "イベント", "その他"], "type"),
        (EventFormat, ["オンライン", "対面", "ハイブリッド", "不明"], "format"),
        (JobCategory, JOB_CATEGORIES, "job"),
        (GraduationYear, ["26卒", "27卒", "28卒", "29卒", "30卒", "学年不問"], "grad"),
        (Degree, ["学部", "修士", "博士", "高専", "専門", "不問"], "degree"),
    ]
    for model, values, prefix in groups:
        bind.execute(
            insert(model),
            [
                {"id": i, "slug": slug(prefix, i), "name": name, "sort_order": i, "is_active": True}
                for i, name in enumerate(values, 1)
            ],
        )
