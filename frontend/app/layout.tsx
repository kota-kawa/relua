import type { Metadata } from "next";

import { Footer } from "@/components/footer";
import { Header } from "@/components/header";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100"),
  title: {
    default: "JOB HARBOR | インターン・本選考情報を横断検索",
    template: "%s | JOB HARBOR",
  },
  description: "主要企業のインターン・本選考・説明会情報を、ログインなしで検索できる就活情報データベース。",
  openGraph: {
    title: "JOB HARBOR",
    description: "次の一歩が見つかる、就活情報の港。",
    type: "website",
    locale: "ja_JP",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>
        <Header />
        {children}
        <Footer />
      </body>
    </html>
  );
}
