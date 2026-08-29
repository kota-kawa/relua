"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { Bookmark, Check, Share2 } from "@/components/icons";
import { OpportunityCard } from "@/components/opportunity-card";
import { loadOpportunities } from "@/lib/browser-api";
import {
  SHARE_CODE_KEY,
  SHARE_LEGACY_KEY,
  mergeBookmarks,
  newBookmarkIds,
  parseFragmentCodes,
  parseFragmentIds,
  readBookmarks,
} from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

export function SharedOpportunityList() {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const codes = parseFragmentCodes(window.location.hash, SHARE_CODE_KEY);
    const refs = codes.length ? codes : parseFragmentIds(window.location.hash, SHARE_LEGACY_KEY);
    loadOpportunities(refs).then((result) => {
      setItems(result.items);
      setLoading(false);
      if (result.missingIds.length) setNotice(`公開が終了した${result.missingIds.length}件は除外しました。`);
    });
  }, []);
  return (
    <main className="local-page shared-page page-enter">
      <div className="shell">
        <header className="local-page-header">
          <p className="eyebrow"><Share2 size={15} /> SHARED LIST</p>
          <h1>共有された募集</h1>
          <p>共有者や閲覧者を識別する情報は含まれていません。</p>
        </header>
        {items.length > 0 && (
          <div className="shared-list-action">
            <button type="button" onClick={() => {
              try {
                const newIds = newBookmarkIds(items.map((item) => item.id), readBookmarks(window.localStorage));
                mergeBookmarks(window.localStorage, newIds);
                notifyLocalDataChanged();
                setNotice(newIds.length ? `${newIds.length}件をブックマークへ追加しました。` : "すべて保存済みです。");
              } catch {
                setNotice("このブラウザに保存できませんでした。保存設定を確認してください。");
              }
            }}><Bookmark size={17} /> すべて保存</button>
          </div>
        )}
        {notice && <p className="local-notice"><Check size={16} /> {notice}</p>}
        {loading ? <p className="local-empty">読み込み中…</p> : items.length ? <div className="card-grid">{items.map((item, index) => <OpportunityCard key={item.id} item={item} index={index} />)}</div> : <div className="local-empty"><p>表示できる募集がありません。</p><Link href="/">募集を探す</Link></div>}
      </div>
    </main>
  );
}
