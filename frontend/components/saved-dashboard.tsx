"use client";

import Image from "next/image";
import Link from "next/link";
import QRCode from "qrcode";
import { ChangeEvent, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { Check, ClipboardPaste, Copy, Download, FileDown, FileUp, History, QrCode, Share2, Smartphone, Trash2, X } from "@/components/icons";
import { OpportunityCard } from "@/components/opportunity-card";
import { showToast } from "@/components/toast";
import { TransferLinkForm } from "@/components/transfer-link-form";
import { loadOpportunities, type LoadedOpportunities } from "@/lib/browser-api";
import { formatInstantDate } from "@/lib/format";
import {
  BOOKMARKS_KEY,
  LOCAL_DATA_EVENT,
  MAX_QR_URL_LENGTH,
  RECENTS_KEY,
  SHARE_CODE_KEY,
  TRANSFER_CODE_KEY,
  bookmarkCsv,
  bookmarkJson,
  buildCodeFragmentUrl,
  clearRecents,
  idsFromSnapshot,
  mergeBookmarks,
  parseBookmarkFile,
  readRecents,
  removeBookmarks,
  urlFitsTransferLimit,
} from "@/lib/local-data";
import { opportunityPath } from "@/lib/site";
import type { Opportunity } from "@/lib/types";

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LOCAL_DATA_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LOCAL_DATA_EVENT, callback);
  };
}

function bookmarksSnapshot() {
  try { return window.localStorage.getItem(BOOKMARKS_KEY) ?? "[]"; } catch { return "[]"; }
}
function recentsSnapshot() {
  try { return window.localStorage.getItem(RECENTS_KEY) ?? "[]"; } catch { return "[]"; }
}

/**
 * Saves a generated backup file.
 *
 * Firefox only dispatches the download for an anchor that is actually in the
 * document, and every browser needs the object URL to outlive the click: revoking
 * it in the same tick cancels the save before it starts. This backup is the only
 * escape hatch before localStorage is lost, so it must not fail quietly.
 * components/opportunity-actions.tsx uses the same delayed revoke for .ics files.
 */
function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

/**
 * Resolves ids against a shared in-memory cache, fetching only the ones not
 * already cached.
 *
 * A single bookmark toggle changes `ids` by one entry, but without a cache the
 * effect below refetched the whole saved list through loadOpportunities' 8-at-
 * a-time batching every time — with 200 saved items that is roughly 25
 * sequential round trips for one click, and the stale list just sat there
 * because nothing set `loading` back to true. Fetching only the new ids makes
 * the common case (one id added or removed) effectively instant instead.
 * Failed fetches are deliberately left out of the cache so the next run (the
 * next bookmark change) retries them rather than freezing a fetch error in
 * place forever.
 *
 * Entries expire after `CACHE_TTL_MS`. `loadOne` fetches `no-store` precisely
 * because a saved entry can close or be withdrawn while this page is open;
 * caching an id forever would mean a closed opening keeps rendering, never
 * lands in `missingIds`, and so is never dropped from localStorage or excluded
 * from a transfer link. The TTL keeps the one-click case cheap while bounding
 * how stale the list can get.
 */
const CACHE_TTL_MS = 5 * 60 * 1000;

type CacheEntry = { item: Opportunity; fetchedAt: number };

async function loadCached(
  cache: Map<string, CacheEntry>,
  ids: string[],
  now = Date.now(),
): Promise<LoadedOpportunities> {
  const isFresh = (entry: CacheEntry | undefined) => Boolean(entry) && now - entry!.fetchedAt < CACHE_TTL_MS;
  const stale = ids.filter((id) => !isFresh(cache.get(id)));
  const fetched = stale.length
    ? await loadOpportunities(stale)
    : { items: [], missingIds: [], failedIds: [] };
  fetched.items.forEach((item) => cache.set(item.id, { item, fetchedAt: now }));
  // A refetch that came back 404 has to drop the stale copy too, or the caller
  // would keep rendering an opening the API just said is gone.
  fetched.missingIds.forEach((id) => cache.delete(id));
  const items = ids
    .map((id) => cache.get(id)?.item)
    .filter((item): item is Opportunity => Boolean(item));
  return { items, missingIds: fetched.missingIds, failedIds: fetched.failedIds };
}

async function copyText(value: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Some embedded browsers expose Clipboard API but reject access to it.
  }
  const input = document.createElement("textarea");
  input.value = value;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  try { return document.execCommand("copy"); } catch { return false; } finally { input.remove(); }
}

async function shareOrCopy(url: string, title: string): Promise<"shared" | "copied" | "cancelled" | "failed"> {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return "cancelled";
    }
  }
  return await copyText(url) ? "copied" : "failed";
}

/*
 * All three dialogs below share one pattern: the interactive close paths
 * (the X button, a backdrop click, a copy-success auto-close) call
 * `dialogRef.current?.close()` rather than the `onClose` prop directly. A
 * native <dialog> only restores focus to whatever opened it when it is
 * actually closed via close()/Escape; calling `onClose` straight away just
 * unmounts the still-"open" <dialog> out from under the browser, so focus
 * fell back to <body> on every path except Escape. `onClose` itself stays
 * wired to the dialog's native "close" event, which both close() and Escape
 * fire, so state teardown happens exactly once regardless of how it closed.
 */
function LinkDialog({ url, onClose }: { url: string; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    inputRef.current?.select();
  }, []);
  return (
    <dialog ref={dialogRef} className="qr-dialog" aria-labelledby="transfer-link-title" onClose={onClose} onPointerDown={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close(); }}>
      <div className="qr-panel link-panel">
        <button type="button" className="panel-close" onClick={() => dialogRef.current?.close()} aria-label="閉じる"><X size={18} /></button>
        <p className="eyebrow">保存データの引き継ぎ</p>
        <h2 id="transfer-link-title">リンクを手動でコピー</h2>
        <p>下のリンクを選択してコピーし、別の端末で開いてください。</p>
        <input ref={inputRef} className="transfer-url-field" value={url} readOnly aria-label="引き継ぎリンク" onFocus={(event) => event.currentTarget.select()} />
        <button type="button" className="dialog-copy-button" onClick={async () => { if (await copyText(url)) { showToast("引き継ぎリンクをコピーしました"); dialogRef.current?.close(); } }}><Copy size={17} /> コピーする</button>
      </div>
    </dialog>
  );
}

function QrDialog({ url, onClose, onManualCopy }: { url: string; onClose: () => void; onManualCopy: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [dataUrl, setDataUrl] = useState("");
  const [error, setError] = useState(false);
  /* Native <dialog>: Escape, focus trap and the backdrop come for free. */
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);
  useEffect(() => {
    let active = true;
    QRCode.toDataURL(url, { width: 320, margin: 2, errorCorrectionLevel: "L" })
      .then((value) => { if (active) setDataUrl(value); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [url]);
  return (
    <dialog
      ref={dialogRef}
      className="qr-dialog"
      aria-labelledby="qr-dialog-title"
      onClose={onClose}
      onPointerDown={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close(); }}
    >
      <div className="qr-panel">
        <button type="button" className="panel-close" onClick={() => dialogRef.current?.close()} aria-label="閉じる"><X size={18} /></button>
        <p className="eyebrow">保存データの引き継ぎ</p>
        <h2 id="qr-dialog-title">QRコードを読み取る</h2>
        <p>別の端末で読み取ると、追加前の確認画面が開きます。</p>
        {dataUrl ? <Image src={dataUrl} width={320} height={320} unoptimized alt="端末間移行用QRコード" /> : <div className="qr-placeholder">{error ? "QRコードを生成できませんでした。引き継ぎリンクをご利用ください。" : "生成中…"}</div>}
        <button type="button" className="qr-copy-button" onClick={async () => { if (await copyText(url)) showToast("引き継ぎリンクをコピーしました"); else { dialogRef.current?.close(); onManualCopy(); } }}><Copy size={16} /> リンクをコピー</button>
      </div>
    </dialog>
  );
}

function PasteLinkDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);
  return (
    <dialog ref={dialogRef} className="qr-dialog" aria-labelledby="paste-link-title" onClose={onClose} onPointerDown={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close(); }}>
      <div className="qr-panel paste-link-panel">
        <button type="button" className="panel-close" onClick={() => dialogRef.current?.close()} aria-label="閉じる"><X size={18} /></button>
        <p className="eyebrow">保存データの引き継ぎ</p>
        <h2 id="paste-link-title">受け取ったリンクを貼り付ける</h2>
        <p>別の端末でコピーした引き継ぎリンクを貼り付けてください。</p>
        <TransferLinkForm onSubmit={(href) => window.location.assign(href)} />
      </div>
    </dialog>
  );
}

export function SavedDashboard() {
  const rawBookmarks = useSyncExternalStore(subscribe, bookmarksSnapshot, () => "[]");
  const rawRecents = useSyncExternalStore(subscribe, recentsSnapshot, () => "[]");
  const ids = useMemo(() => idsFromSnapshot(rawBookmarks), [rawBookmarks]);
  const recentEntries = useMemo(() => {
    const storage = { getItem: () => rawRecents, setItem: () => undefined, removeItem: () => undefined };
    return readRecents(storage);
  }, [rawRecents]);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [recentItems, setRecentItems] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [failedIds, setFailedIds] = useState<string[]>([]);
  const [showQr, setShowQr] = useState(false);
  const [showPasteLink, setShowPasteLink] = useState(false);
  const [manualCopyUrl, setManualCopyUrl] = useState("");
  /* Shared by both effects below so viewing then bookmarking the same item (or
     the reverse) never triggers a second fetch for it. */
  const cacheRef = useRef<Map<string, CacheEntry>>(new Map());
  const hasLoadFailures = failedIds.length > 0;

  const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  /* Links carry the server's short code, so they are only ready once the bookmarks have loaded. */
  const codes = useMemo(() => items.map((item) => item.public_code), [items]);
  const importUrl = buildCodeFragmentUrl(origin, "/import", TRANSFER_CODE_KEY, codes);
  const listUrl = buildCodeFragmentUrl(origin, "/list", SHARE_CODE_KEY, codes);
  const transferLinkAvailable = urlFitsTransferLimit(importUrl);
  const qrAvailable = urlFitsTransferLimit(importUrl, MAX_QR_URL_LENGTH);
  const sharedListAvailable = urlFitsTransferLimit(listUrl);

  useEffect(() => {
    let active = true;
    loadCached(cacheRef.current, ids).then((result) => {
      if (!active) return;
      setItems(result.items);
      setFailedIds(result.failedIds);
      setLoading(false);
      /* missingIds (404, published items that ended or were deleted) and
         failedIds (transient errors) get separate notices: removal is
         permanent and silent otherwise, while a failure is worth explaining
         even though nothing was removed. Both can happen in the same batch. */
      const notices: string[] = [];
      if (result.missingIds.length) {
        try {
          removeBookmarks(window.localStorage, result.missingIds);
          notifyLocalDataChanged();
          notices.push(`公開終了などにより${result.missingIds.length}件を保存一覧から削除しました。`);
        } catch {
          notices.push("公開終了した募集を保存一覧から削除できませんでした。ブラウザの保存設定を確認してください。");
        }
      }
      if (result.failedIds.length) notices.push(`${result.failedIds.length}件を読み込めませんでした。時間をおいて再度お試しください。`);
      if (notices.length) setNotice(notices.join(" "));
    });
    return () => { active = false; };
  }, [ids]);

  useEffect(() => {
    let active = true;
    loadCached(cacheRef.current, recentEntries.map((entry) => entry.id)).then((result) => {
      if (active) setRecentItems(result.items);
    });
    return () => { active = false; };
  }, [recentEntries]);

  async function handleImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    let imported: string[];
    try {
      imported = parseBookmarkFile(await file.text(), file.name);
    } catch {
      setNotice("ファイルを読み込めませんでした。もう一度選択してください。");
      return;
    }
    if (!imported.length) {
      setNotice("対応していない形式、または有効な募集情報IDがありません。");
      return;
    }
    setNotice("ファイルを確認しています…");
    const result = await loadOpportunities(imported);
    try {
      const before = new Set(ids);
      const added = result.items.filter((item) => !before.has(item.id)).length;
      mergeBookmarks(window.localStorage, result.items.map((item) => item.id));
      notifyLocalDataChanged();
      const details = [result.missingIds.length ? `終了・削除済み${result.missingIds.length}件を除外` : "", result.failedIds.length ? `${result.failedIds.length}件を確認できませんでした` : ""].filter(Boolean).join("、");
      setNotice(`${added}件を追加しました${details ? `（${details}）` : ""}。`);
    } catch {
      setNotice("このブラウザに保存できませんでした。サイトデータの保存設定と空き容量を確認してください。");
    }
  }

  async function handleShare(url: string, title: string) {
    const result = await shareOrCopy(url, title);
    if (result === "shared") showToast("共有しました");
    if (result === "copied") showToast("リンクをコピーしました");
    if (result === "failed") setManualCopyUrl(url);
  }

  async function handleCopyTransferLink() {
    if (await copyText(importUrl)) showToast("引き継ぎリンクをコピーしました");
    else setManualCopyUrl(importUrl);
  }

  return (
    <main className="local-page page-enter">
      <div className="shell">
        <header className="local-page-header">
          <p className="eyebrow">LOCAL BOOKMARKS</p>
          <h1>保存した募集</h1>
          <p>保存内容はこのブラウザ内だけに保持され、自動同期はされません。ログインは不要です。</p>
          <p className="storage-caution">ブラウザのサイトデータを削除すると保存内容も消えます。必要に応じてバックアップしてください。</p>
        </header>

        <section className="local-tools" aria-label="保存データの操作">
          <article className="local-tool-card">
            <div className="local-tool-card-heading"><Smartphone size={21} /><div><h2>保存データを引き継ぐ</h2><p>別の端末のブックマークへ、現在の保存内容を追加します。</p></div></div>
            <div className="local-tool-actions">
              <button type="button" disabled={!codes.length || !qrAvailable || hasLoadFailures} onClick={() => setShowQr(true)}><QrCode size={18} /> QRコードで読み取る</button>
              <button type="button" disabled={!codes.length || !transferLinkAvailable || hasLoadFailures} onClick={() => handleShare(importUrl, "reluaの保存データ")}><Share2 size={18} /> 引き継ぎリンクを共有</button>
              <button type="button" disabled={!codes.length || !transferLinkAvailable || hasLoadFailures} onClick={handleCopyTransferLink}><Copy size={18} /> 引き継ぎリンクをコピー</button>
            </div>
            <div className="local-tool-receive"><span>リンクを受け取った場合</span><button type="button" onClick={() => setShowPasteLink(true)}><ClipboardPaste size={18} /> 引き継ぎリンクを貼り付ける</button></div>
            {!!codes.length && !transferLinkAvailable && <p className="tool-limit-note">保存件数が多いため、リンクとQRコードは利用できません。下の「バックアップと復元」からJSONファイルで引き継いでください。</p>}
            {!!codes.length && transferLinkAvailable && !qrAvailable && <p className="tool-limit-note">QRコードには収まらないため、引き継ぎリンクをご利用ください。</p>}
            {/* codes only ever holds successfully fetched items (see loadCached), so a
                failure here means the link would silently omit those entries and the
                receiving device would report a smaller list as a complete success. */}
            {hasLoadFailures && <p className="tool-limit-note">{failedIds.length}件を読み込めなかったため、リンクとQRコードを一時的に無効にしています。時間をおいて再度お試しください。</p>}
          </article>

          <article className="local-tool-card">
            <div className="local-tool-card-heading"><Share2 size={21} /><div><h2>募集リストを共有する</h2><p>現在保存している募集のスナップショットを、ほかの人に共有します。</p></div></div>
            <div className="local-tool-actions">
              <button type="button" disabled={!codes.length || !sharedListAvailable || hasLoadFailures} onClick={() => handleShare(listUrl, "reluaの共有リスト")}><Share2 size={18} /> 募集リストを共有</button>
            </div>
            {!!codes.length && !sharedListAvailable && <p className="tool-limit-note">共有リンクの上限を超えています。保存件数を減らしてから作成してください。</p>}
            {hasLoadFailures && <p className="tool-limit-note">{failedIds.length}件を読み込めなかったため、共有リンクを一時的に無効にしています。時間をおいて再度お試しください。</p>}
          </article>

          {/* Backup and restore matter but are rare; folding them keeps the primary actions scannable. */}
          <details className="local-tools-more">
            <summary><Download size={18} /> バックアップと復元</summary>
            <div className="local-tools-more-body">
              <button type="button" disabled={!ids.length} onClick={() => download("relua-bookmarks.json", bookmarkJson(ids, items), "application/json;charset=utf-8")}><FileDown size={18} /> JSONでバックアップ</button>
              <button type="button" disabled={!ids.length} onClick={() => download("relua-bookmarks.csv", bookmarkCsv(ids), "text/csv;charset=utf-8")}><FileDown size={18} /> CSVでバックアップ</button>
              <label className="file-import"><FileUp size={18} /> バックアップを読込<input type="file" accept=".json,.csv,application/json,text/csv" onChange={handleImport} /></label>
            </div>
          </details>
        </section>

        {notice && <p className="local-notice"><Check size={16} /> {notice}</p>}

        <section className="saved-section">
          <div className="section-heading"><h2>ブックマーク</h2><span>{ids.length}件</span></div>
          {loading ? <p className="local-empty">読み込み中…</p> : items.length ? (
            <div className="card-grid">{items.map((item, index) => <OpportunityCard key={item.id} item={item} index={index} />)}</div>
          ) : (
            <div className="local-empty"><p>保存した募集はまだありません。</p><Link href="/">募集を探す</Link></div>
          )}
        </section>

        <section className="recent-section">
          <div className="section-heading">
            <h2><History size={20} /> 最近見た募集</h2>
            {!!recentEntries.length && <button type="button" onClick={() => {
              try { clearRecents(window.localStorage); notifyLocalDataChanged(); }
              catch { setNotice("閲覧履歴を削除できませんでした。ブラウザの保存設定を確認してください。"); }
            }}><Trash2 size={15} /> 履歴を削除</button>}
          </div>
          {recentItems.length ? (
            <ul className="recent-list">
              {recentItems.map((item) => {
                const entry = recentEntries.find((recent) => recent.id === item.id);
                /* lib/format.ts pins every other timestamp on the site to Asia/Tokyo;
                   toLocaleString without a timeZone used the browser's local zone
                   instead, which drifted from the JST convention outside Japan. */
                return <li key={item.id}><Link href={opportunityPath(item.public_code)}><span>{item.company.name}</span><strong>{item.event_name}</strong></Link><time>{entry ? formatInstantDate(entry.viewedAt) : ""}</time></li>;
              })}
            </ul>
          ) : <p className="local-empty">閲覧履歴はありません。</p>}
        </section>
      </div>
      {showQr && <QrDialog url={importUrl} onClose={() => setShowQr(false)} onManualCopy={() => setManualCopyUrl(importUrl)} />}
      {showPasteLink && <PasteLinkDialog onClose={() => setShowPasteLink(false)} />}
      {manualCopyUrl && <LinkDialog url={manualCopyUrl} onClose={() => setManualCopyUrl("")} />}
    </main>
  );
}
