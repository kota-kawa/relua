import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";

import { BackLink } from "@/components/back-link";
import { ExternalLink, Flag } from "@/components/icons";
import { JsonLd } from "@/components/json-ld";
import { OpportunityCard } from "@/components/opportunity-card";
import { CONTACT_FORM_URL } from "@/lib/constants";
import { formatInstantDate } from "@/lib/format";
import { companyMetadata } from "@/lib/seo";
import { loadCompanySnapshot } from "@/lib/seo-data";
import { companyPath } from "@/lib/site";
import { companyStructuredData } from "@/lib/structured-data";

type Props = { params: Promise<{ code: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const snapshot = await loadCompanySnapshot((await params).code);
  if (!snapshot.company) notFound();
  return companyMetadata(snapshot.company);
}

/**
 * The profile body is stored as one text field with blank lines between
 * paragraphs, so the page has to restore those breaks. Rendering it as a single
 * block would produce the wall of text the field exists to avoid.
 */
function paragraphs(text: string) {
  return text
    .split(/\n\s*\n|\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export default async function CompanyPage({ params }: Props) {
  const code = (await params).code;
  const snapshot = await loadCompanySnapshot(code);
  if (!snapshot.company) notFound();
  const company = snapshot.company;

  // The API accepts a lowercase code so a hand-typed or hand-edited link still
  // resolves, but only one casing is the canonical URL.
  if (code !== company.public_code) permanentRedirect(companyPath(company.public_code));

  const categories = company.industries.map((entry) => ({
    id: entry.industry.id,
    label: entry.sector ? `${entry.industry.name} / ${entry.sector.name}` : entry.industry.name,
    isPrimary: entry.is_primary,
  }));
  const body = company.description ? paragraphs(company.description) : [];

  return (
    <main className="detail-page company-page page-enter">
      <JsonLd data={companyStructuredData(company)} />
      <div className="shell">
        <BackLink>募集一覧に戻る</BackLink>
        <article>
          <header className="detail-hero company-hero">
            <div className="detail-hero-main">
              <p className="eyebrow">COMPANY</p>
              <h1>{company.name}</h1>
              {/* The one-sentence answer to "what is this company" sits in the hero,
                  so it is read before anything else on the page. */}
              {company.business_summary && <p className="company-lead">{company.business_summary}</p>}
              {categories.length > 0 && (
                <div className="detail-tags tag-list">
                  {categories.map((category) => (
                    <span key={category.id} className={category.isPrimary ? "primary-tag" : undefined}>
                      {category.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <aside className="company-summary-box">
              <span>掲載中の募集</span>
              <strong>{company.current_opportunity_count}件</strong>
              {company.website_url && (
                <a className="entry-button" href={company.website_url} target="_blank" rel="noopener noreferrer">
                  公式サイト <ExternalLink size={17} />
                </a>
              )}
            </aside>
          </header>

          <div className="company-body">
            {body.length > 0 && (
              <section className="prose-section company-about" aria-labelledby="about-heading">
                <h2 id="about-heading">事業内容</h2>
                {body.map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
              </section>
            )}

            {/* Named businesses are what a reader scans before committing to the body,
                so they get their own headings rather than living inside a paragraph. */}
            {company.business_areas.length > 0 && (
              <section className="prose-section company-areas" aria-labelledby="areas-heading">
                <h2 id="areas-heading">主な事業</h2>
                <ol className="business-area-list">
                  {company.business_areas.map((area) => (
                    <li key={area.name}>
                      <h3>{area.name}</h3>
                      <p>{area.description}</p>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section className="prose-section company-openings" aria-labelledby="current-openings-heading">
              <h2 id="current-openings-heading">現在の募集</h2>
              {company.current_opportunities.length > 0 ? (
                <div className="card-grid">
                  {company.current_opportunities.map((opportunity, index) => (
                    <OpportunityCard key={opportunity.id} item={opportunity} index={index} />
                  ))}
                </div>
              ) : (
                <p className="company-empty">
                  現在、この企業の募集は掲載していません。公式サイトで最新の募集をご確認ください。
                </p>
              )}
            </section>

            {/* Finished postings are context for what this company usually runs,
                so they are listed but kept visually secondary. */}
            {company.past_opportunities.length > 0 && (
              <section className="prose-section company-openings" aria-labelledby="past-openings-heading">
                <h2 id="past-openings-heading">過去の募集</h2>
                <p className="company-openings-note">
                  募集は終了しています。次回の募集時期を知る手がかりとして掲載しています。
                </p>
                <div className="card-grid">
                  {company.past_opportunities.map((opportunity, index) => (
                    <OpportunityCard key={opportunity.id} item={opportunity} index={index} />
                  ))}
                </div>
              </section>
            )}
          </div>

          <footer className="company-footer">
            <p className="updated-note">企業情報の更新：{formatInstantDate(company.updated_at)}</p>
            <a className="correction-link" href={CONTACT_FORM_URL} target="_blank" rel="noopener noreferrer">
              <Flag size={13} /> 掲載内容の訂正・削除を依頼する
            </a>
          </footer>
        </article>
      </div>
    </main>
  );
}
