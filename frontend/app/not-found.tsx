import Link from "next/link";

export default function NotFound() {
  return (
    <main className="shell error-state not-found page-enter">
      <p className="eyebrow">404 — NOT FOUND</p>
      <h1>お探しのページは見つかりません</h1>
      <p>募集情報が更新または削除された可能性があります。</p>
      <Link href="/">募集一覧へ戻る</Link>
    </main>
  );
}
