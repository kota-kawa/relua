import type { Metadata } from "next";

import { SavedDashboard } from "@/components/saved-dashboard";

export const metadata: Metadata = { title: "保存した募集", robots: { index: false, follow: false } };

export default function SavedPage() { return <SavedDashboard />; }
