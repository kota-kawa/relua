import { ArrowRight, MapPin } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { deadlineIsRelative, deadlineLabel, formatDate } from "@/lib/format";
import { stagger } from "@/lib/motion";
import { opportunityPath } from "@/lib/site";
import type { Opportunity } from "@/lib/types";

export function OpportunityTable({ items }: { items: Opportunity[] }) {
  return (
    <div className="table-shell">
      <table className="opportunity-table">
        <thead>
          <tr>
            <th>募集状況</th>
            <th>企業・募集名</th>
            <th>締切</th>
            <th>種別・開催形式</th>
            <th>対象・職種</th>
            <th><span className="sr-only">詳細</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={item.id} style={stagger(index)}>
              <td data-label="状況">
                <span className={`status ${item.recruitment_status.slug}`}>{item.recruitment_status.name}</span>
              </td>
              <td className="table-opportunity" data-label="募集">
                <span>{item.company.name}</span>
                <NavLink href={opportunityPath(item.public_code)}>{item.event_name}</NavLink>
                <small>{item.industry.name}・{item.sector.name}</small>
              </td>
              <td className="table-deadline" data-label="締切">
                <strong>{deadlineLabel(item.deadline)}</strong>
                {/* Only add the date when the label above is a relative phrase. */}
                {deadlineIsRelative(item.deadline) && <small>{formatDate(item.deadline, "")}</small>}
              </td>
              <td data-label="形式">
                <strong className="table-type">{item.event_type.name}</strong>
                <small className="table-location"><MapPin size={13} /> {item.event_format.name}{item.location ? `・${item.location}` : ""}</small>
              </td>
              <td className="table-target" data-label="対象・職種">
                <div>{item.graduation_years.map((value) => <span key={value.id}>{value.name}</span>)}</div>
                <small>{item.job_categories.map((value) => value.name).join("、") || "職種不問"}</small>
                {!!item.tags.length && <small className="table-tech">{item.tags.slice(0, 3).join(" / ")}</small>}
              </td>
              <td className="table-action">
                <NavLink href={opportunityPath(item.public_code)} aria-label={`${item.event_name}の詳細を見る`}><ArrowRight size={17} /></NavLink>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
