import Image from "next/image";
import Link from "next/link";

export function Header() {
  return (
    <header className="site-header">
      <div className="shell header-inner">
        <Link href="/" className="brand" aria-label="relua トップへ">
          <Image src="/relua-logo.png" width={570} height={204} alt="relua" priority />
          <small>就活情報データベース</small>
        </Link>
        <nav className="header-nav" aria-label="メインナビゲーション">
          <Link href="/#listings">募集を探す</Link>
          <Link href="/about">Reluaについて</Link>
          <span className="public-badge"><i /> ログイン不要</span>
        </nav>
      </div>
    </header>
  );
}
