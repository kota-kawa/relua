import { absoluteUrl, companyPath, opportunityPath, siteOrigin } from "@/lib/site";
import type { CompanyDetail, CompanySummary, Opportunity } from "@/lib/types";

function latestTimestamp(item: Opportunity) {
  return [item.updated_at, item.source_checked_at]
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? item.updated_at;
}

export function siteStructuredData() {
  const origin = siteOrigin();
  const organizationId = `${origin}/#organization`;
  const websiteId = `${origin}/#website`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": organizationId,
        name: "relua",
        url: origin,
        logo: {
          "@type": "ImageObject",
          url: absoluteUrl("/relua-logo.png"),
        },
      },
      {
        "@type": "WebSite",
        "@id": websiteId,
        name: "relua",
        alternateName: "レルア",
        url: origin,
        publisher: { "@id": organizationId },
        inLanguage: "ja-JP",
      },
    ],
  };
}

export function listingStructuredData(items: Opportunity[], page: number, perPage: number) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "インターン・本選考・イベント募集一覧",
    itemListOrder: "https://schema.org/ItemListOrderAscending",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: (page - 1) * perPage + index + 1,
      name: `${item.company.name} ${item.event_name}`,
      url: absoluteUrl(opportunityPath(item.public_code)),
    })),
  };
}

export function companyDirectoryStructuredData(companies: CompanySummary[], page: number, perPage: number) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "掲載企業一覧",
    itemListOrder: "https://schema.org/ItemListOrderAscending",
    itemListElement: companies.map((company, index) => ({
      "@type": "ListItem",
      position: (page - 1) * perPage + index + 1,
      name: company.name,
      url: absoluteUrl(companyPath(company.public_code)),
    })),
  };
}

/**
 * Every detail page can truthfully expose WebPage and breadcrumb entities.
 * Rich-result types such as JobPosting/Event are deliberately not guessed:
 * existing records do not always have the location, apply flow, or exact
 * schedule those Google policies require.
 */
export function opportunityStructuredData(item: Opportunity) {
  const origin = siteOrigin();
  const path = opportunityPath(item.public_code);
  const url = absoluteUrl(path);
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "BreadcrumbList",
        "@id": `${url}#breadcrumb`,
        itemListElement: [
          {
            "@type": "ListItem",
            position: 1,
            name: "募集一覧",
            item: origin,
          },
          {
            "@type": "ListItem",
            position: 2,
            name: `${item.company.name} ${item.event_name}`,
            item: url,
          },
        ],
      },
      {
        "@type": "WebPage",
        "@id": `${url}#webpage`,
        url,
        name: `${item.company.name} ${item.event_name}`,
        description: item.description,
        datePublished: item.created_at,
        dateModified: latestTimestamp(item),
        isPartOf: { "@id": `${origin}/#website` },
        breadcrumb: { "@id": `${url}#breadcrumb` },
        about: {
          "@type": "Organization",
          name: item.company.name,
          ...(item.homepage_url ? { url: item.homepage_url } : {}),
        },
        inLanguage: "ja-JP",
      },
    ],
  };
}


/**
 * WebPage and breadcrumb only, matching the opportunity detail: an Organization
 * entity is stated as the page's subject rather than claimed as a rich result,
 * because a description and a homepage are not the identifiers Google's
 * Organization guidance expects.
 */
export function companyStructuredData(company: CompanyDetail) {
  const origin = siteOrigin();
  const url = absoluteUrl(companyPath(company.public_code));
  const dateModified = [company.updated_at, company.openings_updated_at]
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? company.updated_at;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "BreadcrumbList",
        "@id": `${url}#breadcrumb`,
        itemListElement: [
          {
            "@type": "ListItem",
            position: 1,
            name: "募集一覧",
            item: origin,
          },
          {
            "@type": "ListItem",
            position: 2,
            name: company.name,
            item: url,
          },
        ],
      },
      {
        "@type": "WebPage",
        "@id": `${url}#webpage`,
        url,
        name: `${company.name}のインターン・本選考情報`,
        ...(company.business_summary ? { description: company.business_summary } : {}),
        datePublished: company.created_at,
        dateModified,
        isPartOf: { "@id": `${origin}/#website` },
        breadcrumb: { "@id": `${url}#breadcrumb` },
        about: {
          "@type": "Organization",
          name: company.name,
          ...(company.website_url ? { url: company.website_url } : {}),
          ...(company.description ? { description: company.description } : {}),
          // The business areas are the company's own segmentation of what it does,
          // which is what knowsAbout is for.
          ...(company.business_areas?.length
            ? { knowsAbout: company.business_areas.map((area) => area.name) }
            : {}),
        },
        inLanguage: "ja-JP",
      },
    ],
  };
}
