import Link from "next/link";

import { CONTACT_FORM_URL } from "@/lib/constants";

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
          <Link href="/saved">保存した募集</Link>
          <Link href="/about">Why Relua?</Link>
          <Link href="/terms">利用規約・免責事項</Link>
          <Link href="/policy">掲載ポリシー</Link>
          <a href={CONTACT_FORM_URL} target="_blank" rel="noopener noreferrer">
            お問い合わせ・掲載内容の訂正依頼
          </a>
          <span className="footer-caution">掲載情報は必ず公式サイトでご確認ください</span>
        </div>
      </div>
    </footer>
  );
}
