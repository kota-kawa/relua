import type { Metadata } from "next";

import { SharedOpportunityList } from "@/components/shared-opportunity-list";

export const metadata: Metadata = { title: "共有された募集", robots: { index: false, follow: true } };

export default function SharedListPage() { return <SharedOpportunityList />; }
