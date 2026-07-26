import Link from "next/link";

import { Search } from "@/components/icons";

export function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Search size={28} /></div>
      <h2>条件に合う募集が見つかりませんでした</h2>
      <p>キーワードを短くするか、絞り込み条件を減らしてみてください。</p>
      <Link href="/">すべての募集を見る</Link>
    </div>
  );
}
