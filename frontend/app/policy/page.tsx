import type { Metadata } from "next";
import Link from "next/link";

import { ExternalLink } from "@/components/icons";
import { CONTACT_FORM_URL, POLICY_UPDATED_AT } from "@/lib/constants";

export const metadata: Metadata = {
  title: "掲載ポリシー — 権利者の方へ",
  description:
    "reluaが募集情報をどこから集め、何を掲載し、何を掲載しないかを説明します。企業・権利者からの訂正および削除のご依頼は、内容の当否を争わず速やかに対応します。",
  openGraph: {
    title: "掲載ポリシー — 権利者の方へ",
    description: "情報の収集方針、掲載しないもの、訂正・削除のご依頼について。",
  },
};

export default function Policy() {
  return (
    <main className="legal-page page-enter">
      <section className="legal-hero">
        <div className="hex-field" aria-hidden="true" />
        <div className="shell legal-hero-inner">
          <p className="eyebrow">PUBLICATION POLICY</p>
          <h1>掲載ポリシー</h1>
          <p className="legal-hero-lead">
            reluaは、企業の権利と関係する法令を尊重して運営しています。
            他者の権利を侵害する意図はなく、ご指摘をいただいた場合は速やかに対応します。
          </p>
        </div>
      </section>

      <div className="shell legal-body">
        <section className="legal-lead">
          <p>
            reluaは、各企業が自ら公開しているインターン・本選考の募集情報を、
            就職活動をする学生が探しやすい形に整理して掲載しているサービスです。
          </p>
          <p>
            掲載しているのは<strong>募集の事実に関する情報</strong>であり、
            出典サイトの文章そのものを転載する目的も、他社が構築したデータベースを再利用する目的もありません。
            このページでは、実際にどのような方針で運用しているかを具体的に説明します。
          </p>
        </section>

        <section className="legal-section">
          <h2>1. 情報の収集元</h2>
          <p>
            募集情報は、<strong>企業自身が公開している採用ページなどの一次情報</strong>のみを出典としています。
          </p>
          <p>
            求人サイト、就活情報サイト、企業口コミサイトの掲載ページを出典として登録することは、
            方針として避けているだけでなく、<strong>システム上そもそも登録できないよう制限しています</strong>。
            これらのサイトの掲載内容は各社が費用と労力をかけて構築したデータベースであり、
            その利用規約においても自動的な取得・再利用が認められていないためです。
          </p>
          <p>
            各募集の詳細ページには、必ず出典となったURLへのリンクと、
            その情報をreluaに取り込んだ日付を表示しています。
          </p>
        </section>

        <section className="legal-section">
          <h2>2. 掲載内容の作り方</h2>
          <p>
            掲載する文章は、出典ページの表現をそのまま複製したものではありません。
            実施期間、対象学年、応募締め切り、選考フロー、報酬といった
            <strong>事実にあたる情報のみを抽出し、reluaの側で要約して記載しています</strong>。
          </p>
          <p>
            企業のキャッチコピー、理念や社風を語る文章、募集要項の説明文といった、
            出典独自の創作的な表現は使用しません。
          </p>
        </section>

        <section className="legal-section">
          <h2>3. 掲載しないもの</h2>
          <ul className="legal-list">
            <li>
              <strong>企業のロゴ、写真、その他の画像</strong> —
              reluaは募集情報に画像を一切保存しない設計です。
            </li>
            <li>
              <strong>出典独自の文章</strong> — 前項のとおり、事実の要約のみを掲載します。
            </li>
            <li>
              <strong>個人情報</strong> —
              採用担当者名などの個人名、個人宛のメールアドレス・電話番号は掲載しません。
            </li>
            <li>
              <strong>企業の評価・格付け</strong> —
              reluaは企業を採点したり順位付けしたりしません。掲載するのは募集の事実に関する情報だけです。
            </li>
            <li>
              <strong>非公開の情報</strong> — 企業が一般に公開していない情報は取り扱いません。
            </li>
          </ul>
        </section>

        <section className="legal-section">
          <h2>4. 職業安定法上の位置づけ</h2>
          <p>
            reluaは、企業の募集情報を求職者に提供する募集情報等提供にあたるものとして、
            職業安定法および関係指針の趣旨に沿った運用を行います。
            掲載情報を正確かつ最新の内容に保つよう努め、
            虚偽の表示や誤解を生じさせる表示を行いません。
          </p>
          <p>
            reluaには会員登録の仕組みがなく、<strong>氏名やメールアドレスなど、求職者を直接特定する個人情報を収集・保有していません</strong>。
            保存した募集や閲覧履歴は、サーバーではなく利用者自身のブラウザ内にのみ保存されます。
          </p>
          <p>
            なお、アクセス状況の把握とサービス改善のため、Google アナリティクスを利用しています。
            Cookie を使用して閲覧状況、アクセス日時、端末やブラウザに関する情報などを収集する場合があります。
            詳細と無効化方法は、<Link href="/terms#analytics">利用規約の「アクセス解析ツールについて」</Link>をご確認ください。
          </p>
        </section>

        <section className="legal-section">
          <h2>5. 商標について</h2>
          <p>
            掲載している企業名・サービス名・イベント名は、各権利者の商標または登録商標です。
            reluaはこれらを、どの企業のどの募集であるかを示す事実の記載としてのみ使用しており、
            当該企業との提携、推薦、承認を示すものではありません。
          </p>
        </section>

        <section className="legal-section" id="removal">
          <h2>6. 訂正・削除のご依頼</h2>
          <p>
            掲載内容に誤りがある場合、掲載を望まれない場合、
            その他権利に関するご懸念がある場合は、お問い合わせフォームからご連絡ください。
          </p>
          <div className="legal-callout">
            <p>
              <strong>ご依頼にあたって、権利者であることの証明や、削除を求める理由の説明は必要ありません。</strong>
            </p>
            <p>
              当該企業の募集情報についてご連絡をいただいた場合、
              reluaは内容の当否を争うことなく、速やかに該当情報を修正または削除します。
              争いになる前に取り下げることを方針としています。
            </p>
          </div>
          <p>
            ご連絡の際に、対象となる募集の詳細ページのURLを添えていただけると、
            より速やかに対応できます。
          </p>
          <a className="legal-cta" href={CONTACT_FORM_URL} target="_blank" rel="noopener noreferrer">
            お問い合わせフォームを開く <ExternalLink size={16} />
          </a>
        </section>

        <section className="legal-section">
          <h2>7. 本ポリシーの位置づけ</h2>
          <p>
            本ポリシーは、reluaの運用方針を説明するものです。
            サービスのご利用条件および免責事項については、
            <Link href="/terms">利用規約</Link>をご確認ください。
          </p>
        </section>

        <p className="legal-meta">最終改定：{POLICY_UPDATED_AT}</p>
      </div>
    </main>
  );
}
