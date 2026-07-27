"use client";

import Image from "next/image";
import Link from "next/link";
import QRCode from "qrcode";
import { ChangeEvent, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { Check, FileDown, FileUp, History, QrCode, Share2, Smartphone, Trash2, X } from "@/components/icons";
import { OpportunityCard } from "@/components/opportunity-card";
import { loadOpportunities } from "@/lib/browser-api";
import {
  BOOKMARKS_KEY,
  LOCAL_DATA_EVENT,
  RECENTS_KEY,
  bookmarkCsv,
  bookmarkJson,
  buildFragmentUrl,
  clearRecents,
  mergeBookmarks,
  normalizeIds,
  parseBookmarkFile,
  readRecents,
  removeBookmarks,
} from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LOCAL_DATA_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LOCAL_DATA_EVENT, callback);
  };
}

function bookmarksSnapshot() { return window.localStorage.getItem(BOOKMARKS_KEY) ?? "[]"; }
function recentsSnapshot() { return window.localStorage.getItem(RECENTS_KEY) ?? "[]"; }

function parseIds(raw: string) {
  try { return normalizeIds(JSON.parse(raw)); } catch { return []; }
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function shareOrCopy(url: string, title: string) {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return "共有しました";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return "";
    }
  }
  await navigator.clipboard.writeText(url);
  return "URLをコピーしました";
}

function QrPanel({ url, onClose }: { url: string; onClose: () => void }) {
  const [dataUrl, setDataUrl] = useState("");
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    QRCode.toDataURL(url, { width: 320, margin: 2, errorCorrectionLevel: "L" })
      .then((value) => { if (active) setDataUrl(value); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [url]);
  return (
    <div className="qr-panel" role="dialog" aria-modal="true" aria-label="端末間移行用QRコード">
      <button type="button" className="panel-close" onClick={onClose} aria-label="閉じる"><X size={18} /></button>
      <p className="eyebrow">DEVICE TRANSFER</p>
      <h2>QRコードを読み取る</h2>
      <p>別の端末で読み取ると、追加前の確認画面が開きます。</p>
      {dataUrl ? <Image src={dataUrl} width={320} height={320} unoptimized alt="端末間移行用QRコード" /> : <div className="qr-placeholder">{error ? "保存件数が多いためQRコードに収まりません。「他の端末へ送る」でURLを共有してください。" : "生成中…"}</div>}
      <small>{url}</small>
    </div>
  );
}

export function SavedDashboard() {
  const rawBookmarks = useSyncExternalStore(subscribe, bookmarksSnapshot, () => "[]");
  const rawRecents = useSyncExternalStore(subscribe, recentsSnapshot, () => "[]");
  const ids = useMemo(() => parseIds(rawBookmarks), [rawBookmarks]);
  const recentEntries = useMemo(() => {
    const storage = { getItem: () => rawRecents, setItem: () => undefined, removeItem: () => undefined };
    return readRecents(storage);
  }, [rawRecents]);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [recentItems, setRecentItems] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [showQr, setShowQr] = useState(false);

  const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  const importUrl = buildFragmentUrl(origin, "/import", "b", ids);
  const listUrl = buildFragmentUrl(origin, "/list", "jobs", ids);

  useEffect(() => {
    let active = true;
    loadOpportunities(ids).then((result) => {
      if (!active) return;
      setItems(result.items);
      setLoading(false);
      if (result.missingIds.length) {
        removeBookmarks(window.localStorage, result.missingIds);
        notifyLocalDataChanged();
      }
      if (result.failedIds.length) setNotice(`${result.failedIds.length}件を読み込めませんでした。時間をおいて再度お試しください。`);
    });
    return () => { active = false; };
  }, [ids]);

  useEffect(() => {
    let active = true;
    loadOpportunities(recentEntries.map((entry) => entry.id)).then((result) => {
      if (active) setRecentItems(result.items);
    });
    return () => { active = false; };
  }, [recentEntries]);

  async function handleImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const imported = parseBookmarkFile(await file.text(), file.name);
    if (!imported.length) {
      setNotice("対応していない形式、または有効な募集情報IDがありません。");
      return;
    }
    setNotice("ファイルを確認しています…");
    const result = await loadOpportunities(imported);
    mergeBookmarks(window.localStorage, result.items.map((item) => item.id));
    notifyLocalDataChanged();
    setNotice(`${result.items.length}件を追加しました${result.missingIds.length ? `（存在しない${result.missingIds.length}件は除外）` : ""}。`);
  }

  return (
    <main className="local-page">
      <div className="shell">
        <header className="local-page-header">
          <p className="eyebrow">LOCAL BOOKMARKS</p>
          <h1>保存した募集</h1>
          <p>保存内容はこのブラウザ内だけに保持されます。ログインは不要です。</p>
        </header>

        <section className="local-tools" aria-label="保存データの操作">
          <button type="button" disabled={!ids.length} onClick={async () => setNotice(await shareOrCopy(importUrl, "reluaの保存データ"))}><Smartphone size={18} /> 他の端末へ送る</button>
          <button type="button" disabled={!ids.length} onClick={() => setShowQr(true)}><QrCode size={18} /> QRコードを表示</button>
          <button type="button" disabled={!ids.length} onClick={async () => setNotice(await shareOrCopy(listUrl, "reluaの共有リスト"))}><Share2 size={18} /> 共有リストを作成</button>
          <button type="button" disabled={!ids.length} onClick={() => download("relua-bookmarks.json", bookmarkJson(ids), "application/json;charset=utf-8")}><FileDown size={18} /> JSONでバックアップ</button>
          <button type="button" disabled={!ids.length} onClick={() => download("relua-bookmarks.csv", bookmarkCsv(ids), "text/csv;charset=utf-8")}><FileDown size={18} /> CSVでバックアップ</button>
          <label className="file-import"><FileUp size={18} /> バックアップを読込<input type="file" accept=".json,.csv,application/json,text/csv" onChange={handleImport} /></label>
        </section>

        {notice && <p className="local-notice"><Check size={16} /> {notice}</p>}

        <section className="saved-section">
          <div className="section-heading"><h2>ブックマーク</h2><span>{ids.length}件</span></div>
          {loading ? <p className="local-empty">読み込み中…</p> : items.length ? (
            <div className="card-grid">{items.map((item) => <OpportunityCard key={item.id} item={item} />)}</div>
          ) : (
            <div className="local-empty"><p>保存した募集はまだありません。</p><Link href="/">募集を探す</Link></div>
          )}
        </section>

        <section className="recent-section">
          <div className="section-heading">
            <h2><History size={20} /> 最近見た募集</h2>
            {!!recentEntries.length && <button type="button" onClick={() => { clearRecents(window.localStorage); notifyLocalDataChanged(); }}><Trash2 size={15} /> 履歴を削除</button>}
          </div>
          {recentItems.length ? (
            <ul className="recent-list">
              {recentItems.map((item) => {
                const entry = recentEntries.find((recent) => recent.id === item.id);
                return <li key={item.id}><Link href={`/opportunities/${item.id}`}><span>{item.company.name}</span><strong>{item.event_name}</strong></Link><time>{entry ? new Date(entry.viewedAt).toLocaleString("ja-JP") : ""}</time></li>;
              })}
            </ul>
          ) : <p className="local-empty">閲覧履歴はありません。</p>}
        </section>
      </div>
      {showQr && <div className="panel-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowQr(false); }}><QrPanel url={importUrl} onClose={() => setShowQr(false)} /></div>}
    </main>
  );
}
