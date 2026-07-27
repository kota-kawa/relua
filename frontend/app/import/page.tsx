import type { Metadata } from "next";

import { ImportBookmarks } from "@/components/import-bookmarks";

export const metadata: Metadata = { title: "保存データを取り込む", robots: { index: false, follow: false } };

export default function ImportPage() { return <ImportBookmarks />; }
