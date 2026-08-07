import type { Metadata } from "next";
import Link from "next/link";

import { ExternalLink } from "@/components/icons";
import { CONTACT_FORM_URL, OPERATOR_NAME, POLICY_UPDATED_AT } from "@/lib/constants";

export const metadata: Metadata = {
  title: "利用規約・免責事項",
  description:
    "reluaの利用条件と免責事項です。掲載情報は各企業の公開情報をもとにした参考情報であり、応募の前には必ず企業の公式ページで最新の内容をご確認ください。",
  openGraph: {
    title: "利用規約・免責事項",
    description: "reluaの利用条件、掲載情報の位置づけ、免責事項について。",
  },
};

export default function Terms() {
  return (
    <main className="legal-page">
      <section className="legal-hero">
        <div className="hex-field" aria-hidden="true" />
        <div className="shell legal-hero-inner">
          <p className="eyebrow">TERMS OF USE</p>
          <h1>利用規約・免責事項</h1>
          <p className="legal-hero-lead">
            reluaは、関係する法令と第三者の権利を尊重して運営しています。
            ご利用の前に、本規約と掲載情報の位置づけをご確認ください。
          </p>
        </div>
      </section>

      <div className="shell legal-body">
        <section className="legal-lead">
          <p>
            本規約は、relua（以下「本サービス」）の利用条件を定めるものです。
            本サービスを利用された方は、本規約に同意したものとみなします。
          </p>
        </section>

        <section className="legal-section">
          <h2>1. 本サービスの位置づけ</h2>
          <p>
            本サービスは、各企業が自ら公開しているインターンシップ・本選考等の募集情報を収集し、
            検索できる形に整理して提供する情報サービスです。
          </p>
          <p>
            本サービスは、職業紹介事業ではありません。
            利用者と企業との間の応募、選考、採用の過程に関与せず、
            これらを仲介または斡旋するものではありません。
          </p>
          <p>
            本サービスは、掲載している企業との提携関係にあるものではなく、
            掲載は当該企業からの依頼または承認に基づくものではありません。
          </p>
        </section>

        <section className="legal-section">
          <h2>2. 利用条件</h2>
          <p>
            本サービスは、会員登録なしに、どなたでも無償でご利用いただけます。
            氏名やメールアドレスなど、利用者を直接特定する個人情報を収集・保有することはありません。
          </p>
          <p>
            保存した募集、閲覧履歴、共有用のデータは、
            本サービスのサーバーではなく<strong>利用者ご自身のブラウザ内にのみ保存されます</strong>。
            そのため、ブラウザのデータを消去した場合や別の端末をご利用の場合、
            これらの情報は引き継がれません。
          </p>
          <p>
            なお、アクセス状況の把握とサービス改善のため、Google アナリティクスを利用しています。
            収集する情報と利用目的については、次項をご確認ください。
          </p>
        </section>

        <section className="legal-section" id="analytics">
          <h2>3. アクセス解析ツールについて</h2>
          <p>
            本サービスでは、利用状況を把握し、機能や利便性を改善するため、Google LLC が提供する
            Google アナリティクスを利用しています。
          </p>
          <p>
            Google アナリティクスは Cookie を使用し、ページの閲覧状況、アクセス日時、端末やブラウザに関する情報などを収集します。
            これらの情報は
            <a href="https://policies.google.com/privacy?hl=ja" target="_blank" rel="noopener noreferrer">
              Google のプライバシーポリシー
            </a>
            に基づいて管理されます。
            Google アナリティクスによるデータ収集は、Cookie を無効にするか、
            <a href="https://tools.google.com/dlpage/gaoptout?hl=ja" target="_blank" rel="noopener noreferrer">
              Google アナリティクス オプトアウト アドオン
            </a>
            を利用することで無効にできます。
          </p>
        </section>

        <section className="legal-section">
          <h2>4. 掲載情報について</h2>
          <p>
            掲載情報は、各企業の公開情報をもとに本サービスが要約した<strong>参考情報</strong>です。
            正確かつ最新の内容に保つよう努めていますが、
            その正確性、完全性、最新性を保証するものではありません。
          </p>
          <p>
            募集内容は企業側の判断により予告なく変更または終了される場合があり、
            本サービスの掲載内容が実際の募集内容と一致しない可能性があります。
          </p>
          <div className="legal-callout">
            <p>
              <strong>応募をご検討の際は、必ず企業の公式ページで最新の募集内容をご確認ください。</strong>
            </p>
            <p>
              各募集の詳細ページには、出典となったURLへのリンクと、
              その情報を取り込んだ日付を表示しています。
            </p>
          </div>
        </section>

        <section className="legal-section">
          <h2>5. 免責事項</h2>
          <p>本サービスは、次の事項について責任を負いません。</p>
          <ul className="legal-list">
            <li>掲載情報の誤り、記載漏れ、更新の遅れによって利用者に生じた損害</li>
            <li>掲載情報にもとづく応募、選考、採用に関して生じた結果および損害</li>
            <li>募集内容の変更、募集の終了、応募機会の逸失によって生じた損害</li>
            <li>本サービスの提供の中断、停止、終了、内容の変更によって生じた損害</li>
            <li>リンク先の外部サイトの内容および利用によって生じた損害</li>
            <li>ブラウザ内に保存されたデータの消失によって生じた損害</li>
          </ul>
          <p>
            ただし、本サービスの故意または重大な過失による場合は、この限りではありません。
          </p>
        </section>

        <section className="legal-section">
          <h2>6. 禁止事項</h2>
          <p>本サービスのご利用にあたり、次の行為はご遠慮ください。</p>
          <ul className="legal-list">
            <li>法令または公序良俗に反する行為</li>
            <li>本サービスの運営を妨害する行為、および過度な負荷を与える行為</li>
            <li>本サービスの掲載情報を自動的に大量取得し、再配布または再掲載する行為</li>
            <li>第三者または本サービスの権利、利益、名誉を侵害する行為</li>
          </ul>
        </section>

        <section className="legal-section">
          <h2>7. 知的財産</h2>
          <p>
            掲載している企業名、サービス名、イベント名は、各権利者の商標または登録商標です。
            本サービスは、これらをどの企業のどの募集であるかを示す事実の記載として使用しています。
          </p>
          <p>
            本サービスが情報を収集し、掲載内容を作成するにあたっての方針は、
            <Link href="/policy">掲載ポリシー</Link>に定めています。
            権利に関するご懸念がある場合の対応についても、あわせて記載しています。
          </p>
        </section>

        <section className="legal-section">
          <h2>8. 掲載内容に関するご連絡</h2>
          <p>
            掲載内容の誤り、掲載の停止のご希望、その他権利に関するご懸念については、
            お問い合わせフォームからご連絡ください。
            <strong>内容の当否を争うことなく、速やかに修正または削除いたします。</strong>
          </p>
          <a className="legal-cta" href={CONTACT_FORM_URL} target="_blank" rel="noopener noreferrer">
            お問い合わせフォームを開く <ExternalLink size={16} />
          </a>
        </section>

        <section className="legal-section">
          <h2>9. サービスの変更・終了</h2>
          <p>
            本サービスは、利用者への事前の通知なく、
            内容の変更、提供の中断、または終了を行う場合があります。
          </p>
        </section>

        <section className="legal-section">
          <h2>10. 本規約の変更</h2>
          <p>
            本規約は、必要に応じて変更する場合があります。
            変更後の規約は、本ページに掲載した時点から効力を生じます。
          </p>
        </section>

        <section className="legal-section">
          <h2>11. 準拠法・裁判管轄</h2>
          <p>
            本規約は日本法に準拠し、日本法にしたがって解釈されます。
            本サービスに関して紛争が生じた場合は、
            東京地方裁判所を第一審の専属的合意管轄裁判所とします。
          </p>
        </section>

        <section className="legal-section">
          <h2>12. 運営者</h2>
          <p>
            本サービスは、{OPERATOR_NAME}が個人として運営しています。
            ご連絡はお問い合わせフォームにて承ります。
          </p>
        </section>

        <p className="legal-meta">最終改定：{POLICY_UPDATED_AT}</p>
      </div>
    </main>
  );
}
