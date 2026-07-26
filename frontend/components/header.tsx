import Image from "next/image";
import Link from "next/link";

export function Header() {
  return (
    <header className="site-header">
      <div className="shell header-inner">
        <Link href="/" className="brand" aria-label="JOB HARBOR トップへ">
          <Image src="/mark.svg" width={42} height={42} alt="" priority />
          <span>
            <strong>JOB HARBOR</strong>
            <small>就活情報データベース</small>
          </span>
        </Link>
        <nav className="header-nav" aria-label="メインナビゲーション">
          <Link href="/#listings">募集を探す</Link>
          <a href="https://github.com/modelcontextprotocol" target="_blank" rel="noreferrer">
            MCPについて
          </a>
          <span className="public-badge"><i /> ログイン不要</span>
        </nav>
      </div>
    </header>
  );
}
