import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArrowLeft, CalendarDays, ExternalLink, MapPin } from "@/components/icons";
import { ApiError, getOpportunity } from "@/lib/api";
import { deadlineIsRelative, deadlineLabel, formatDate } from "@/lib/format";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const item = await getOpportunity((await params).id);
    return { title: `${item.company.name} ${item.event_name}`, description: item.description.slice(0, 120) };
  } catch {
    return { title: "募集情報" };
  }
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default async function OpportunityDetail({ params }: Props) {
  let item;
  try {
    item = await getOpportunity((await params).id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <main className="detail-page">
      <div className="shell">
        <Link className="back-link" href="/"><ArrowLeft size={17} /> 募集一覧に戻る</Link>
        <article>
          <header className="detail-hero">
            <div className="detail-hero-main">
              <div className="card-badges">
                <span className={`status ${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span>
                <span className="type-badge">{item.event_type.name}</span>
              </div>
              <p className="company-name">{item.company.name}</p>
              <h1>{item.event_name}</h1>
              <div className="detail-tags tag-list">
                {item.graduation_years.map((value) => <span key={value.id} className="primary-tag">{value.name}</span>)}
                <span>{item.industry.name} / {item.sector.name}</span>
                {item.job_categories.map((value) => <span key={value.id}>{value.name}</span>)}
              </div>
            </div>
            <aside className="deadline-box">
              <span>応募締め切り</span>
              <strong>{deadlineLabel(item.deadline)}</strong>
              {deadlineIsRelative(item.deadline) && <small>{formatDate(item.deadline)}</small>}
              {/* Without an entry URL there would otherwise be no call to action at all. */}
              {item.entry_url ? (
                <a className="entry-button" href={item.entry_url} target="_blank" rel="noopener noreferrer">
                  エントリーする <ExternalLink size={17} />
                </a>
              ) : (
                <a className="entry-button entry-button-secondary" href={item.homepage_url ?? item.source_url} target="_blank" rel="noopener noreferrer">
                  募集ページを開く <ExternalLink size={17} />
                </a>
              )}
            </aside>
          </header>

          <div className="detail-layout">
            <div className="detail-content">
              <section className="prose-section">
                <h2>募集内容</h2>
                <p>{item.description}</p>
              </section>

              {item.selection_process && (
                <section className="prose-section">
                  <h2>選考フロー</h2>
                  <div className="process-flow">
                    {item.selection_process.split("→").map((step, index) => (
                      <span key={`${step}-${index}`}><i>{index + 1}</i>{step}</span>
                    ))}
                  </div>
                </section>
              )}

              {item.requirements && (
                <section className="prose-section">
                  <h2>募集要件</h2>
                  <p>{item.requirements}</p>
                  {item.audience_note && <p className="note-box">{item.audience_note}</p>}
                </section>
              )}

              {item.compensation && (
                <section className="prose-section">
                  <h2>待遇・サポート</h2>
                  <p>{item.compensation}</p>
                </section>
              )}
            </div>

            <aside className="detail-sidebar">
              <h2>開催概要</h2>
              <dl>
                <DetailRow label="開催形式"><span><MapPin size={16} /> {item.event_format.name}{item.location ? ` / ${item.location}` : ""}</span></DetailRow>
                <DetailRow label="実施期間"><span><CalendarDays size={16} /> {item.event_start_date ? formatDate(item.event_start_date) : item.period_note}</span>{item.event_end_date && <small>〜 {formatDate(item.event_end_date)}</small>}</DetailRow>
                <DetailRow label="対象学位">{item.degrees.map((value) => value.name).join("、")}</DetailRow>
                <DetailRow label="募集開始日">{item.recruitment_start_date ? formatDate(item.recruitment_start_date) : null}</DetailRow>
              </dl>
              <div className="source-links">
                {item.homepage_url && <a href={item.homepage_url} target="_blank" rel="noopener noreferrer">公式ページ <ExternalLink size={15} /></a>}
                <a href={item.source_url} target="_blank" rel="noopener noreferrer">情報源を確認 <ExternalLink size={15} /></a>
              </div>
              <p className="updated-note">最終更新：{formatDate(item.updated_at.slice(0, 10))}</p>
            </aside>
          </div>
        </article>
      </div>
    </main>
  );
}
