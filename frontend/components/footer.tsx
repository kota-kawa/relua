import Link from "next/link";

const apiUrl = process.env.NEXT_PUBLIC_API_URL;

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="shell footer-inner">
        <div>
          <p className="footer-brand">relua</p>
          <p className="footer-tagline">Relay information. Reveal possibilities.</p>
          <p>散らばった募集情報をつなぎ、次の可能性を見えるようにする。</p>
        </div>
        <div className="footer-links">
          <Link href="/">募集を探す</Link>
          <Link href="/about">Why Relua?</Link>
          {apiUrl && <a href={`${apiUrl}/docs`} target="_blank" rel="noreferrer">API Docs</a>}
          <span>掲載情報は必ず公式サイトでご確認ください</span>
        </div>
      </div>
    </footer>
  );
}
