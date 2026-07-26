import Link from "next/link";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="shell footer-inner">
        <div>
          <p className="footer-brand">JOB HARBOR</p>
          <p>出典と更新履歴を大切にする、オープンな就活情報データベース。</p>
        </div>
        <div className="footer-links">
          <Link href="/">募集を探す</Link>
          <a href="http://localhost:8000/docs">API Docs</a>
          <span>掲載情報は必ず公式サイトでご確認ください</span>
        </div>
      </div>
    </footer>
  );
}
