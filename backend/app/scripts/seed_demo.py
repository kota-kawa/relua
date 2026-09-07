from datetime import date, timedelta

from pydantic import ValidationError

from app.db import SessionLocal
from app.schemas import (
    COMPANY_PROFILE_FIELD_NAMES,
    CompanyProfileUpdateRequest,
    OpportunityInput,
)
from app.services.companies import (
    CompanyIdentityValidationError,
    find_company,
    update_company_profile,
)
from app.services.opportunities import DomainValidationError, write_opportunity

DEMO_ROWS = [
    ("株式会社青波テクノロジー", "プロダクト開発 3days Workshop", "IT・通信", "Webサービス", "インターン", ["ソフトウェアエンジニア"], ["28卒", "29卒"], ["React", "チーム開発"]),
    ("株式会社北極星データ", "データサイエンス実践プログラム", "IT・通信", "ソフトウェア", "インターン", ["データサイエンティスト"], ["28卒"], ["データ分析", "Python"]),
    ("暁フィナンシャル株式会社", "金融ビジネス オープンカンパニー", "金融", "銀行", "説明会・セミナー", ["総合職"], ["28卒", "29卒"], ["金融", "オンライン"]),
    ("株式会社森羅モビリティ", "次世代モビリティ技術職選考", "メーカー", "自動車・輸送機器", "本選考", ["研究開発", "生産技術"], ["28卒"], ["モビリティ", "研究開発"]),
    ("白樺ストラテジー株式会社", "戦略コンサルタント選考直結セミナー", "コンサル・シンクタンク", "戦略コンサル", "イベント", ["コンサルタント"], ["28卒", "29卒"], ["選考直結", "ケース面接"]),
    ("株式会社日輪メディア", "デジタルマーケティング仕事体験", "広告・メディア", "広告代理店", "インターン", ["マーケティング", "企画・経営企画"], ["28卒"], ["マーケティング", "企画"]),
]

#: Fictional company profiles, so a local environment shows the company pages with the amount of
#: text the real ones are required to carry. In production these are written through the
#: update_company_profile tool.
DEMO_PROFILES = [
    {
        "company_name": "株式会社青波テクノロジー",
        "business_summary": "産業機械向けの制御ソフトウェアと遠隔監視サービスを開発し、国内の製造業へ提供している架空企業です。",
        "description": (
            "工場設備の稼働データを集めて可視化する仕組みを、制御基板からクラウドまで一貫して開発しています。"
            "顧客は自動車部品、食品、化学の各業界の中堅メーカーで、既存設備への後付け導入が売上の中心です。"
            "導入実績は約350工場、売上のおよそ6割を遠隔監視サービスの月額利用料が占めています。\n\n"
            "受託開発では、設備メーカーの制御ソフトウェアを共同で設計する案件も扱います。"
            "組み込みソフトウェアとクラウド側の開発を同じチームが担当する体制をとっており、"
            "現場の制約を踏まえた仕様に落とし込めることを特徴として掲げています。"
            "検証用の設備を社内に持ち、納入前に実機で動作を確認する工程を標準の開発手順に含めています。\n\n"
            "拠点は東京本社と名古屋の技術センターの2か所で、社員約240名のうち技術職が約7割です。"
            "近年は蓄積した稼働データを使った故障予兆の検知機能の提供を始め、既存顧客への追加提案を進めています。"
        ),
        "business_areas": [
            {
                "name": "遠隔監視サービス事業",
                "description": (
                    "工場設備の稼働データを収集・可視化するクラウドサービスを月額で提供しています。"
                    "約350工場に導入され、売上の約6割を占める主力事業です。故障予兆の検知機能も提供しています。"
                ),
            },
            {
                "name": "制御機器事業",
                "description": (
                    "既存設備へ後付けできる制御基板とセンサーユニットを自社で設計・製造しています。"
                    "自動車部品・食品・化学業界の中堅メーカーへ販売し、遠隔監視サービスの導入口にもなっています。"
                ),
            },
            {
                "name": "受託開発事業",
                "description": (
                    "設備メーカーと共同で組み込み制御ソフトウェアを設計・開発します。"
                    "現場の制約を踏まえた仕様設計から、社内設備での実機検証、量産後の保守までを担当しています。"
                ),
            },
        ],
        "website_url": "https://aonami.example.com/",
    },
    {
        "company_name": "株式会社北極星データ",
        "business_summary": "小売・物流事業者向けに需要予測と異常検知の分析基盤を開発し、在庫と配送の計画業務を支援している架空企業です。",
        "description": (
            "小売チェーンと物流事業者に向けて、需要予測と異常検知を行う分析基盤をSaaSとして提供しています。"
            "販売実績、在庫、配送実績を取り込み、発注量と配送計画の立案を支援する仕組みが主力製品です。"
            "導入社数は約120社で、契約は年単位の従量課金が中心となっています。\n\n"
            "分析モデルの構築から本番環境での運用監視までを自社のチームが担当します。"
            "顧客ごとに扱う商品の性質が異なるため、標準モデルをそのまま渡すのではなく、"
            "個別に調整したモデルを運用し、精度の変化を監視して再学習する体制をとっています。"
            "導入時には既存の発注業務の手順を確認し、システムの出力をどう業務へ組み込むかまで一緒に設計します。\n\n"
            "社員は約90名で、そのうちデータサイエンティストとエンジニアが約7割を占めます。"
            "近年は在庫最適化に加えて、配送ルートの計画を扱う機能の提供を始めました。"
        ),
        "business_areas": [
            {
                "name": "需要予測プラットフォーム事業",
                "description": (
                    "販売実績と在庫データから発注量を提案するSaaSを提供しています。"
                    "小売チェーンを中心に約120社が利用しており、配送ルートの計画機能も追加しています。"
                ),
            },
            {
                "name": "分析運用支援事業",
                "description": (
                    "顧客ごとの分析モデルの構築、本番環境への組み込み、運用監視までを継続的に請け負っています。"
                    "精度の変化を監視してモデルを再学習し、発注業務への組み込み方も一緒に設計します。"
                ),
            },
        ],
        "website_url": "https://hokkyokusei.example.com/",
    },
    {
        "company_name": "暁フィナンシャル株式会社",
        "business_summary": "個人向けの預金・融資と、中小企業向けの資金調達支援を行っている架空の金融機関です。",
        "description": (
            "個人向けには預金、住宅ローン、カードローンを、法人向けには中小企業の運転資金と設備資金の融資を扱っています。"
            "店舗網は国内に42拠点で、口座開設と各種手続きはオンラインでも受け付けています。"
            "貸出金の残高はおよそ1兆2000億円で、そのうち中小企業向けが約6割を占めます。\n\n"
            "法人取引では、融資に加えて事業承継や販路開拓の相談も受け付けています。"
            "支店をまたいで取引先を紹介する仕組みを社内で運営しており、"
            "地域の取引先同士をつなぐ役割を法人営業の業務に含めています。"
            "審査では財務資料に加えて事業の内容を担当者が直接確認する手順をとっています。\n\n"
            "従業員は約2100名で、そのうち営業店勤務が約7割です。"
            "近年は決済サービスの開発に取り組み、加盟店向けの入金サイクルを短縮する仕組みを自社で構築しています。"
        ),
        "business_areas": [
            {
                "name": "個人向け金融事業",
                "description": (
                    "預金、住宅ローン、カードローンを42の店舗網とオンラインで提供しています。"
                    "口座開設から各種手続きまでオンラインで完結し、店舗では対面での相談も受け付けています。"
                ),
            },
            {
                "name": "法人向け金融事業",
                "description": (
                    "中小企業の運転資金・設備資金の融資を扱い、事業承継や販路開拓の相談にも対応しています。"
                    "貸出金残高の約6割を占め、支店をまたいで取引先を紹介する仕組みも運営しています。"
                ),
            },
            {
                "name": "決済サービス事業",
                "description": (
                    "加盟店向けの決済と入金の仕組みを自社で開発・運営しています。"
                    "入金サイクルの短縮を目的に近年立ち上げた事業で、既存の法人取引先への提供から始めています。"
                ),
            },
        ],
        "website_url": "https://akatsuki-fin.example.com/",
    },
]


def seed_company_profiles() -> None:
    for index, profile in enumerate(DEMO_PROFILES, 1):
        company_name = profile["company_name"]
        website_url = profile["website_url"]
        try:
            with SessionLocal() as db:
                company = find_company(db, company_name)
                if company is None:
                    print(f"skip profile {company_name}: company was not created")
                    continue
                # Validated through the same request model the MCP tool uses, so the demo data
                # cannot drift below the minimum lengths the tool enforces.
                request = CompanyProfileUpdateRequest.model_validate(
                    {
                        "company_id": company.id,
                        "business_summary": profile["business_summary"],
                        "description": profile["description"],
                        "business_areas": profile["business_areas"],
                        "website_url": website_url,
                        "source_url": f"{website_url}company/",
                        "request_id": f"demo-seed-profile-20260907-{index:03d}",
                        "client_name": "demo-seeder",
                    }
                )
                update_company_profile(
                    db,
                    company_id=request.company_id,
                    changes=request.model_dump(include=COMPANY_PROFILE_FIELD_NAMES, exclude_unset=True),
                    source_url=request.source_url,
                    request_id=request.request_id,
                    client_name=request.client_name,
                )
        except (CompanyIdentityValidationError, ValidationError) as exc:
            print(f"skip profile {company_name}: {exc}")


def run() -> None:
    today = date.today()
    for index, (company, title, industry, sector, event_type, jobs, grads, tags) in enumerate(DEMO_ROWS, 1):
        data = OpportunityInput(
            recruitment_status="募集中",
            company_name=company,
            industry=industry,
            sector=sector,
            event_name=title,
            deadline=today + timedelta(days=7 + index * 5),
            event_type=event_type,
            description="事業理解と実務に近いワークを通して、仕事の進め方やチームの雰囲気を体験できるプログラムです。社員からのフィードバックと座談会も予定しています。",
            event_format="ハイブリッド" if index % 2 else "オンライン",
            location="東京都千代田区" if index % 2 else None,
            selection_process="エントリー→書類選考→参加確定",
            homepage_url=None,
            job_categories=jobs,
            tags=tags,
            event_start_date=today + timedelta(days=30 + index * 4),
            event_end_date=today + timedelta(days=32 + index * 4),
            period_note="複数日程から選択",
            requirements="大学・大学院等に在籍し、プログラムの全日程に参加できる方。",
            compensation="交通費支給（当社規定による）",
            graduation_years=grads,
            degrees=["学部", "修士"],
            audience_note=None,
            recruitment_start_date=today - timedelta(days=5),
            entry_url=None,
            source_url="https://example.com/demo-source",
        )
        try:
            with SessionLocal() as db:
                write_opportunity(
                    db,
                    data=data,
                    request_id=f"demo-seed-20260726-{index:03d}",
                    client_name="demo-seeder",
                )
        except DomainValidationError as exc:
            print(f"skip {company}: {exc.errors}")
    seed_company_profiles()
    print("Demo data is ready. All company names, listings and profiles are fictional.")


if __name__ == "__main__":
    run()
