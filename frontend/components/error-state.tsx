import Link from "next/link";

export function ErrorState() {
  return (
    <main className="shell error-state page-enter">
      <p className="eyebrow">TEMPORARILY UNAVAILABLE</p>
      <h1>情報を読み込めませんでした</h1>
      <p>閲覧サービスに一時的な問題が発生しています。少し時間をおいてから、もう一度お試しください。</p>
      <Link href="/">再読み込みする</Link>
    </main>
  );
}
