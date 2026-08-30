import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BackLink } from "@/components/back-link";
import { BookmarkButton } from "@/components/bookmark-button";
import { ArrowRight, CalendarDays, ExternalLink, Flag, MapPin } from "@/components/icons";
import { OpportunityActions } from "@/components/opportunity-actions";
import { OpportunityCard } from "@/components/opportunity-card";
import { RecentTracker } from "@/components/recent-tracker";
import { ApiError, getOpportunity, getSameCompanyOpportunities } from "@/lib/api";
import { CONTACT_FORM_URL } from "@/lib/constants";
import { deadlineCompactLabel, deadlineIsRelative, deadlineLabel, formatDate } from "@/lib/format";

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
  let sameCompanyOpportunities;
  const id = (await params).id;
  try {
    [item, sameCompanyOpportunities] = await Promise.all([
      getOpportunity(id),
      // This secondary path must never take the primary detail page down.
      getSameCompanyOpportunities(id).catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const entryHref = item.entry_url ?? item.homepage_url ?? item.source_url;
  const sourceCheckedAt = item.source_checked_at ?? item.updated_at;

  return (
    <main className="detail-page page-enter">
      <RecentTracker id={item.id} />
      <div className="shell">
        <BackLink>募集一覧に戻る</BackLink>
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

          <OpportunityActions item={item} />

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
                    {item.selection_process
                      .split("→")
                      .map((step) => step.trim())
                      .filter(Boolean)
                      .map((step, index) => (
                        <div className="process-node" key={`${step}-${index}`}>
                          {index > 0 && <ArrowRight className="process-arrow" size={18} strokeWidth={2.5} />}
                          <span className="process-step"><i>{index + 1}</i>{step}</span>
                        </div>
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
              <p className="updated-note">公式情報確認：{formatDate(sourceCheckedAt.slice(0, 10))}</p>
              <a className="correction-link" href={CONTACT_FORM_URL} target="_blank" rel="noopener noreferrer">
                <Flag size={13} /> 掲載内容の訂正・削除を依頼する
              </a>
            </aside>
          </div>

          {sameCompanyOpportunities.length > 0 && (
            <section className="same-company-opportunities" aria-labelledby="same-company-heading">
              <div className="same-company-heading">
                <div>
                  <p className="eyebrow">MORE FROM THIS COMPANY</p>
                  <h2 id="same-company-heading">同じ企業の他の募集</h2>
                </div>
                <p>{item.company.name}が現在掲載している、その他の募集です。</p>
              </div>
              <div className="card-grid same-company-grid">
                {sameCompanyOpportunities.map((opportunity, index) => (
                  <OpportunityCard key={opportunity.id} item={opportunity} index={index} />
                ))}
              </div>
            </section>
          )}
        </article>
      </div>

      {/* Mobile-only sticky bar: the entry CTA stays reachable however far the page is scrolled. */}
      <div className="detail-cta-bar">
        <div className="cta-deadline">
          <span>締切</span>
          <strong>{deadlineCompactLabel(item.deadline)}</strong>
        </div>
        <BookmarkButton id={item.id} compact />
        <a className="entry-button" href={entryHref} target="_blank" rel="noopener noreferrer">
          {item.entry_url ? "エントリー" : "募集ページ"} <ExternalLink size={16} />
        </a>
      </div>
    </main>
  );
}
