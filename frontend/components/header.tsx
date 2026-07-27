import Image from "next/image";
import Link from "next/link";

import { SavedNavigation } from "@/components/saved-navigation";

export function Header() {
  return (
    <header className="site-header">
      <div className="shell header-inner">
        <Link href="/" className="brand" aria-label="relua トップへ">
          <Image src="/relua-logo.png" width={570} height={204} alt="relua" priority />
          <small>Relay, then reveal.</small>
        </Link>
        <nav className="header-navigation" aria-label="主要メニュー">
          <Link href="/">募集を探す</Link>
          <SavedNavigation />
        </nav>
      </div>
    </header>
  );
}
