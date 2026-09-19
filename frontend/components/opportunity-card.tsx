import { BookmarkButton } from "@/components/bookmark-button";
import { ArrowRight, CalendarDays, MapPin } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { daysUntil, deadlineChipLabel, formatDate, formatInstantDate } from "@/lib/format";
import { stagger } from "@/lib/motion";
import { opportunityPath } from "@/lib/site";
import type { Opportunity } from "@/lib/types";

function urgencyClass(deadline: string | null) {
  const days = daysUntil(deadline);
  if (days !== null && days >= 0 && days <= 3) return "deadline-hot";
  if (days !== null && days >= 0 && days <= 10) return "deadline-warm";
  return "";
}

/** `index` is the card's position in its grid, which sets its place in the
    entrance cascade. */
export function OpportunityCard({ item, index = 0 }: { item: Opportunity; index?: number }) {
  const sourceCheckedAt = item.source_checked_at ?? item.updated_at;

  return (
    <article className="opportunity-card" style={stagger(index)}>
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
      <h2><NavLink className="card-link" href={opportunityPath(item.public_code)}>{item.event_name}</NavLink></h2>

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
        <span>公式確認 {formatInstantDate(sourceCheckedAt, "")}</span>
        <span className="card-cta">詳細を見る <ArrowRight size={16} /></span>
      </div>
    </article>
  );
}
