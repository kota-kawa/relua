import Link from "next/link";

import { ArrowRight, CalendarDays, MapPin } from "@/components/icons";
import { daysUntil, deadlineLabel, formatDate } from "@/lib/format";
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
      <div className="card-topline">
        <div className="card-badges">
          <span className={`status status-${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span>
          <span className="type-badge">{item.event_type.name}</span>
        </div>
        <span className={`deadline-chip ${urgencyClass(item.deadline)}`}>{deadlineLabel(item.deadline)}</span>
      </div>

      <p className="company-name">{item.company.name}</p>
      <h2><Link href={`/opportunities/${item.id}`}>{item.event_name}</Link></h2>

      <div className="card-facts">
        <span><CalendarDays size={16} /> {item.period_note || (item.event_start_date ? `${formatDate(item.event_start_date, "")}〜` : "開催日程は公式サイトを確認")}</span>
        <span><MapPin size={16} /> {item.event_format.name}{item.location ? `・${item.location}` : ""}</span>
      </div>

      <p className="card-description">{item.description}</p>

      <div className="tag-list">
        {item.graduation_years.map((value) => <span key={value.id} className="primary-tag">{value.name}</span>)}
        <span>{item.industry.name}</span>
        {item.job_categories.slice(0, 2).map((value) => <span key={value.id}>{value.name}</span>)}
      </div>

      <div className="card-footer">
        <span>更新 {formatDate(item.updated_at.slice(0, 10), "")}</span>
        <Link href={`/opportunities/${item.id}`}>詳細を見る <ArrowRight size={16} /></Link>
      </div>
    </article>
  );
}
