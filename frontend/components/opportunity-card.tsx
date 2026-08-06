import Link from "next/link";

import { BookmarkButton } from "@/components/bookmark-button";
import { ArrowRight, CalendarDays, MapPin } from "@/components/icons";
import { daysUntil, deadlineChipLabel, formatDate } from "@/lib/format";
import type { Opportunity } from "@/lib/types";

function urgencyClass(deadline: string | null) {
  const days = daysUntil(deadline);
  if (days !== null && days >= 0 && days <= 3) return "deadline-hot";
  if (days !== null && days >= 0 && days <= 10) return "deadline-warm";
  return "";
}

export function OpportunityCard({ item }: { item: Opportunity }) {
  return (
    <article className="opportunity-card">
      <div className="card-bookmark"><BookmarkButton id={item.id} compact /></div>
      <div className="card-topline">
        <div className="card-badges">
          <span className={`status ${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span>
          <span className="type-badge">{item.event_type.name}</span>
        </div>
        <span className={`deadline-chip ${urgencyClass(item.deadline)}`}>{deadlineChipLabel(item.deadline)}</span>
      </div>

      {/* Visually the company leads the card — students scan by employer — while
          the event name stays the heading the page outline and search rely on. */}
      <p className="company-name">{item.company.name}</p>
      {/* The link is stretched over the whole card, so the card itself is the target. */}
      <h2><Link className="card-link" href={`/opportunities/${item.id}`}>{item.event_name}</Link></h2>

      {/* Eligibility is the first thing a student checks, so it sits with the title. */}
      <div className="card-audience">
        {item.graduation_years.map((value) => <span key={value.id} className="primary-tag">{value.name}</span>)}
      </div>

      <div className="card-facts">
        <span><CalendarDays size={16} /> {item.period_note || (item.event_start_date ? `${formatDate(item.event_start_date, "")}〜` : "開催日程は公式サイトを確認")}</span>
        <span><MapPin size={16} /> {item.event_format.name}{item.location ? `・${item.location}` : ""}</span>
      </div>

      <p className="card-description">{item.description}</p>

      <div className="tag-list">
        <span>{item.industry.name}</span>
        {item.job_categories.slice(0, 2).map((value) => <span key={value.id}>{value.name}</span>)}
      </div>

      <div className="card-footer">
        <span>更新 {formatDate(item.updated_at.slice(0, 10), "")}</span>
        <span className="card-cta">詳細を見る <ArrowRight size={16} /></span>
      </div>
    </article>
  );
}
