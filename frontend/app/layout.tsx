import type { Metadata } from "next";
import Script from "next/script";

import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import { JsonLd } from "@/components/json-ld";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toast";
import { siteOrigin } from "@/lib/site";
import { siteStructuredData } from "@/lib/structured-data";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin()),
  title: {
    default: "relua | インターン・本選考情報を横断検索",
    template: "%s | relua",
  },
  description: "主要企業のインターン・本選考・説明会情報を、ログインなしで検索できる就活情報データベース。散らばった募集情報をつなぎ、次の可能性を見えるようにします。",
  applicationName: "relua",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.png", type: "image/png", sizes: "211x204" },
    ],
    apple: "/favicon.png",
  },
  openGraph: {
    title: "relua — Find what's next.",
    description: "Relay information. Reveal possibilities. 散らばった募集情報をつなぎ、次の可能性を見えるようにする就活情報データベース。",
    siteName: "relua",
    images: ["/relua-logo.png"],
    type: "website",
    locale: "ja_JP",
  },
  twitter: {
    card: "summary_large_image",
    title: "relua — Find what's next.",
    description: "散らばった募集情報をつなぎ、次の可能性を見えるようにする就活情報データベース。",
    images: ["/relua-logo.png"],
  },
  formatDetection: { email: false, address: false, telephone: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>
        <JsonLd data={siteStructuredData()} />
        {/* Analytics is non-critical for the first paint; wait until the page is
            idle so it cannot compete with the listing's LCP or block interaction. */}
        <Script src="https://www.googletagmanager.com/gtag/js?id=G-M4K571GKCX" strategy="lazyOnload" />
        <Script id="google-analytics" strategy="lazyOnload">
          {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-M4K571GKCX');`}
        </Script>
        <RouteProgress />
        <Header />
        {children}
        <Footer />
        <Toaster />
      </body>
    </html>
  );
}
