"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { Check, Smartphone } from "@/components/icons";
import { loadOpportunities } from "@/lib/browser-api";
import { mergeBookmarks, parseFragmentIds } from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

export function ImportBookmarks() {
  const [requested, setRequested] = useState<string[]>([]);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [missing, setMissing] = useState(0);
  const [loading, setLoading] = useState(true);
  const [imported, setImported] = useState(false);

  useEffect(() => {
    const ids = parseFragmentIds(window.location.hash, "b");
    loadOpportunities(ids).then((result) => {
      setRequested(ids);
      setItems(result.items);
      setMissing(result.missingIds.length);
      setLoading(false);
    });
  }, []);

  return (
    <main className="confirm-page">
      <section className="confirm-card">
        <div className="confirm-icon"><Smartphone size={28} /></div>
        <p className="eyebrow">DEVICE TRANSFER</p>
        {loading ? <><h1>保存データを確認しています</h1><p>有効な募集情報だけを取り込み対象にします。</p></> : imported ? (
          <><h1>{items.length}件を追加しました</h1><p>この端末の既存ブックマークと統合しました。</p><Link className="primary-link" href="/saved"><Check size={17} /> 保存した募集を見る</Link></>
        ) : requested.length ? (
          <>
            <h1>{items.length}件の保存データがあります。</h1>
            <p>この端末のブックマークへ追加しますか？既存の保存内容は削除されません。</p>
            {missing > 0 && <small>存在しない{missing}件は除外されます。</small>}
            <div className="confirm-actions">
              <button type="button" disabled={!items.length} onClick={() => { mergeBookmarks(window.localStorage, items.map((item) => item.id)); notifyLocalDataChanged(); setImported(true); }}>追加する</button>
              <Link href="/">キャンセル</Link>
            </div>
          </>
        ) : <><h1>保存データが見つかりません</h1><p>URLが途中で切れていないか確認してください。</p><Link className="primary-link" href="/">募集一覧へ戻る</Link></>}
      </section>
    </main>
  );
}
