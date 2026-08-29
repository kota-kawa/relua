import { ArrowRight, CalendarDays, MapPin } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { deadlineIsRelative, deadlineLabel } from "@/lib/format";
import { stagger } from "@/lib/motion";
import type { Opportunity } from "@/lib/types";

const monthFormatter = new Intl.DateTimeFormat("ja-JP", { year: "numeric", month: "long", timeZone: "Asia/Tokyo" });
const dayFormatter = new Intl.DateTimeFormat("ja-JP", { day: "numeric", timeZone: "Asia/Tokyo" });
const weekdayFormatter = new Intl.DateTimeFormat("ja-JP", { weekday: "short", timeZone: "Asia/Tokyo" });

function asDate(value: string) {
  return new Date(`${value}T00:00:00+09:00`);
}

export function DeadlineCalendar({ items }: { items: Opportunity[] }) {
  const dated = items.filter((item): item is Opportunity & { deadline: string } => Boolean(item.deadline));
  const undated = items.filter((item) => !item.deadline);
  const groups = new Map<string, typeof dated>();
  dated.forEach((item) => {
    const key = item.deadline.slice(0, 7);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  });

  return (
    <div className="deadline-calendar">
      <div className="calendar-intro">
        <span><CalendarDays size={18} /> 締切を見逃さない</span>
        <p>応募締切が近い順にまとめています。日付を確認したら、必ず公式サイトで最新情報をご確認ください。</p>
      </div>
      {[...groups.entries()].map(([month, monthItems]) => (
        <section className="calendar-month" key={month}>
          <div className="calendar-month-title">
            <span>{month.slice(0, 4)}</span>
            <h3>{monthFormatter.format(asDate(`${month}-01`)).replace(`${month.slice(0, 4)}年`, "")}</h3>
            <small>{monthItems.length}件</small>
          </div>
          <div className="calendar-items">
            {monthItems.map((item, index) => {
              const date = asDate(item.deadline);
              return (
                <article className="calendar-item" key={item.id} style={stagger(index)}>
                  <div className="calendar-date">
                    <strong>{dayFormatter.format(date).replace("日", "")}</strong>
                    <span>{weekdayFormatter.format(date)}</span>
                  </div>
                  <div className="calendar-content">
                    <div className="calendar-badges">
                      <span className={`status ${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span>
                      <span>{item.event_type.name}</span>
                      {/* The date column already states the date; only the
                          urgency phrasing adds anything here. */}
                      {deadlineIsRelative(item.deadline) && <b>{deadlineLabel(item.deadline)}</b>}
                    </div>
                    <p>{item.company.name}</p>
                    <h3><NavLink href={`/opportunities/${item.id}`}>{item.event_name}</NavLink></h3>
                    <small><MapPin size={13} /> {item.event_format.name}{item.location ? `・${item.location}` : ""}</small>
                  </div>
                  <NavLink className="calendar-arrow" href={`/opportunities/${item.id}`} aria-label={`${item.event_name}の詳細を見る`}><ArrowRight size={18} /></NavLink>
                </article>
              );
            })}
          </div>
        </section>
      ))}
      {undated.length > 0 && (
        <section className="calendar-month undated">
          <div className="calendar-month-title"><span>DATE</span><h3>締切未定</h3><small>{undated.length}件</small></div>
          <div className="calendar-items">
            {undated.map((item, index) => (
              <article className="calendar-item" key={item.id} style={stagger(index)}>
                <div className="calendar-date"><strong>—</strong><span>未定</span></div>
                <div className="calendar-content">
                  <div className="calendar-badges"><span className={`status ${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span><span>{item.event_type.name}</span></div>
                  <p>{item.company.name}</p>
                  <h3><NavLink href={`/opportunities/${item.id}`}>{item.event_name}</NavLink></h3>
                </div>
                <NavLink className="calendar-arrow" href={`/opportunities/${item.id}`} aria-label={`${item.event_name}の詳細を見る`}><ArrowRight size={18} /></NavLink>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
