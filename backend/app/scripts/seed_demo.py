from datetime import date, timedelta

from app.db import SessionLocal
from app.schemas import OpportunityInput
from app.services.opportunities import DomainValidationError, write_opportunity

DEMO_ROWS = [
    ("株式会社青波テクノロジー", "プロダクト開発 3days Workshop", "IT・通信", "Webサービス", "インターン", ["ソフトウェアエンジニア"], ["28卒", "29卒"], ["React", "チーム開発"]),
    ("株式会社北極星データ", "データサイエンス実践プログラム", "IT・通信", "ソフトウェア", "インターン", ["データサイエンティスト"], ["28卒"], ["データ分析", "Python"]),
    ("暁フィナンシャル株式会社", "金融ビジネス オープンカンパニー", "金融", "銀行", "説明会・セミナー", ["総合職"], ["28卒", "29卒"], ["金融", "オンライン"]),
    ("株式会社森羅モビリティ", "次世代モビリティ技術職選考", "メーカー", "自動車・輸送機器", "本選考", ["研究開発", "生産技術"], ["28卒"], ["モビリティ", "研究開発"]),
    ("白樺ストラテジー株式会社", "戦略コンサルタント選考直結セミナー", "コンサル・シンクタンク", "戦略コンサル", "イベント", ["コンサルタント"], ["28卒", "29卒"], ["選考直結", "ケース面接"]),
    ("株式会社日輪メディア", "デジタルマーケティング仕事体験", "広告・メディア", "広告代理店", "インターン", ["マーケティング", "企画・経営企画"], ["28卒"], ["マーケティング", "企画"]),
]


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
    print("Demo data is ready. All company names and listings are fictional.")


if __name__ == "__main__":
    run()
