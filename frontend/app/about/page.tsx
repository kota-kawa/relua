import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { ArrowRight, Search } from "@/components/icons";

export const metadata: Metadata = {
  title: "Why Relua? — 名前の由来",
  description:
    "Relua（レルア）は Relay と Reveal からの造語です。散らばった募集情報をつなぎ、まだ見えていなかった可能性を見えるようにする——サービス名とハニカムのシンボルに込めた意味を紹介します。",
  openGraph: {
    title: "Why Relua? — 名前の由来",
    description: "Relay information. Reveal possibilities. 名前とシンボルに込めた意味。",
  },
};

/** Two interlocking hexagons — the "relay" half of the mark, used as a section marker. */
function HexIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="hex-icon" aria-hidden="true">
      <svg viewBox="0 0 44 48" fill="none">
        <path d="M22 1.155 41.115 12.21v22.11L22 45.375 2.885 34.32V12.21z" fill="currentColor" fillOpacity=".1" stroke="currentColor" strokeWidth="1.6" />
      </svg>
      <i>{children}</i>
    </span>
  );
}

export default function About() {
  return (
    <main className="about-page">
      <section className="about-hero">
        <div className="hex-field" aria-hidden="true" />
        <div className="shell about-hero-inner">
          <p className="eyebrow">WHY RELUA?</p>
          <h1>
            Relay information.
            <span>Reveal possibilities.</span>
          </h1>
          <p className="about-hero-lead">
            <strong>Relua（レルア）</strong>という名前は、<b>Relay</b> と <b>Reveal</b> という
            2つの言葉から着想を得た造語です。
          </p>
        </div>
      </section>

      <div className="shell about-body">
        <section className="about-intro">
          <p>世の中には、まだ知られていない機会がたくさんあります。</p>
          <p>
            企業の採用ページ、イベントページ、お知らせ、募集要項。
            必要な情報は存在していても、それぞれ別の場所に散らばり、更新され、
            時には見つけられないまま埋もれていきます。
          </p>
          <p>Reluaは、そんな散らばった情報をつなぎ、見つけられるものにしたいという思いから生まれました。</p>
        </section>

        <section className="concept-pair">
          <article className="concept-card">
            <HexIcon><ArrowRight size={17} /></HexIcon>
            <p className="concept-word">Relay</p>
            <h2>情報をつなぐ</h2>
            <p>
              <b>Relay</b> は、「受け渡す」「つなぐ」という意味を持つ言葉です。
            </p>
            <p>さまざまな場所に存在する情報を拾い、一つの場所へつなぐ。</p>
            <p>
              人から人へバトンを渡すように、Web上に散らばる情報を受け取り、整理し、
              必要とする人へ届ける。
            </p>
            <p className="concept-close">Reluaの第一の役割です。</p>
          </article>

          <article className="concept-card">
            <HexIcon><Search size={16} /></HexIcon>
            <p className="concept-word">Reveal</p>
            <h2>可能性を見えるようにする</h2>
            <p>情報は、存在しているだけでは役に立ちません。</p>
            <p>見つけられて初めて、選択肢になります。</p>
            <p>
              <b>Reveal</b> には、「隠れていたものを明らかにする」という意味があります。
            </p>
            <ul className="concept-list">
              <li>知らなかった企業。</li>
              <li>知らなかったインターン。</li>
              <li>まだ考えたことのなかった仕事。</li>
            </ul>
            <p>
              散らばった情報を整理することで、それまで見えていなかった可能性を見えるようにする。
            </p>
            <p className="concept-close">それが、Reluaのもう一つの役割です。</p>
          </article>
        </section>

        <section className="honeycomb-section">
          <div className="honeycomb-figure">
            <Image src="/favicon.png" width={211} height={204} alt="reluaのハニカムシンボル" />
          </div>
          <div className="honeycomb-copy">
            <h2>なぜ蜂の巣なのか</h2>
            <p>
              Reluaのシンボルには、<strong>蜂の巣（ハニカム）</strong>をモチーフにしています。
            </p>
            <p>蜂は、一つの場所だけから蜜を集めるわけではありません。</p>
            <p>さまざまな花を巡り、小さな蜜を少しずつ持ち帰り、巣へ集めます。</p>
            <p>
              一つひとつは離れた場所にある小さな情報でも、集まり、整理されることで大きな価値になる。
              この構造は、Reluaが目指すものとよく似ています。
            </p>
            <p>
              六角形が連なるハニカムは、<strong>多くの情報がつながり、一つの知識になること</strong>を
              表しています。そして、その中から生まれる新しい一歩を表すために、
              アクセントには温かいアンバーを使っています。
            </p>
          </div>
        </section>

        <section className="about-closing">
          <div className="hex-field" aria-hidden="true" />
          <div className="about-closing-inner">
            <h2>Find what&rsquo;s next.</h2>
            <p>Reluaが届けたいのは、求人情報そのものではありません。</p>
            <p>その情報の先にある、</p>
            <p className="closing-quote">「こんな選択肢もあったんだ」</p>
            <p>という発見です。</p>
            <p className="closing-motto">
              Relay information.
              <span>Reveal possibilities.</span>
            </p>
            <p>散らばった情報をつなぎ、次の可能性を見えるようにする。</p>
            <Link className="closing-cta" href="/#listings">
              募集を探してみる <ArrowRight size={17} />
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
