"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { Check, Smartphone } from "@/components/icons";
import { TransferLinkForm } from "@/components/transfer-link-form";
import { loadOpportunities } from "@/lib/browser-api";
import {
  TRANSFER_CODE_KEY,
  TRANSFER_LEGACY_KEY,
  mergeBookmarks,
  newBookmarkIds,
  parseFragmentCodes,
  parseFragmentIds,
  readBookmarks,
} from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

type ImportStatus = "loading" | "ready" | "imported" | "storage-error";

export function ImportBookmarks() {
  const [requested, setRequested] = useState<string[]>([]);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [existingIds, setExistingIds] = useState<string[]>([]);
  const [missing, setMissing] = useState(0);
  const [failed, setFailed] = useState(0);
  const [status, setStatus] = useState<ImportStatus>("loading");
  const [attempt, setAttempt] = useState(0);
  const [importedCount, setImportedCount] = useState(0);

  useEffect(() => {
    let active = true;
    const codes = parseFragmentCodes(window.location.hash, TRANSFER_CODE_KEY);
    const refs = codes.length ? codes : parseFragmentIds(window.location.hash, TRANSFER_LEGACY_KEY);
    loadOpportunities(refs).then((result) => {
      if (!active) return;
      setRequested(refs);
      setExistingIds(readBookmarks(window.localStorage));
      setItems(result.items);
      setMissing(result.missingIds.length);
      setFailed(result.failedIds.length);
      setStatus("ready");
    });
    return () => { active = false; };
  }, [attempt]);

  const newIds = useMemo(
    () => newBookmarkIds(items.map((item) => item.id), existingIds),
    [items, existingIds],
  );
  const newIdSet = useMemo(() => new Set(newIds), [newIds]);
  const newItems = useMemo(() => items.filter((item) => newIdSet.has(item.id)), [items, newIdSet]);
  const duplicateCount = items.length - newItems.length;

  function importBookmarks() {
    try {
      mergeBookmarks(window.localStorage, newIds);
      notifyLocalDataChanged();
      setImportedCount(newIds.length);
      setStatus("imported");
    } catch {
      setStatus("storage-error");
    }
  }

  function retryImport() {
    setStatus("loading");
    setAttempt((value) => value + 1);
  }

  const retryButton = failed > 0 && (
    <button type="button" className="text-button" onClick={retryImport}>再読み込み</button>
  );

  return (
    <main className="confirm-page page-enter">
      <section className="confirm-card" aria-live="polite">
        <div className="confirm-icon"><Smartphone size={28} /></div>
        <p className="eyebrow">保存データの引き継ぎ</p>

        {status === "loading" ? (
          <><h1>保存データを確認しています</h1><p>有効な募集情報と、この端末の保存状況を確認します。</p></>
        ) : status === "imported" ? (
          <><h1>{importedCount}件を追加しました</h1><p>この端末の既存ブックマークはそのまま残っています。</p><Link className="primary-link" href="/saved"><Check size={17} /> 保存した募集を見る</Link></>
        ) : status === "storage-error" ? (
          <><h1>この端末に保存できませんでした</h1><p>ブラウザのサイトデータ保存が無効になっていないか、空き容量があるかを確認してください。</p><div className="confirm-actions"><button type="button" onClick={() => setStatus("ready")}>もう一度試す</button><Link href="/saved">戻る</Link></div></>
        ) : !requested.length ? (
          <>
            <h1>引き継ぎリンクを貼り付ける</h1>
            <p>別の端末でコピーしたリンクを貼り付けると、追加内容を確認できます。</p>
            <TransferLinkForm onSubmit={(href) => window.location.assign(href)} />
            <Link className="import-back-link" href="/saved">保存した募集へ戻る</Link>
          </>
        ) : !items.length && failed > 0 ? (
          <><h1>保存データを確認できませんでした</h1><p>通信状態を確認して、もう一度お試しください。</p><div className="confirm-actions">{retryButton}<Link href="/saved">キャンセル</Link></div></>
        ) : (
          <>
            <h1>{newItems.length ? `${newItems.length}件を追加できます` : "新しく追加する募集はありません"}</h1>
            <p>{newItems.length ? "内容を確認して、この端末のブックマークへ追加してください。" : "共有された募集は、すでに保存済みか公開が終了しています。"}</p>

            <dl className="import-summary">
              <div><dt>新しく追加</dt><dd>{newItems.length}件</dd></div>
              <div><dt>保存済み</dt><dd>{duplicateCount}件</dd></div>
              <div><dt>終了・削除済み</dt><dd>{missing}件</dd></div>
            </dl>

            {newItems.length > 0 && (
              <div className="import-preview">
                <h2>追加する募集</h2>
                <ul>
                  {newItems.slice(0, 5).map((item) => <li key={item.id}><span>{item.company.name}</span><strong>{item.event_name}</strong></li>)}
                </ul>
                {newItems.length > 5 && <small>ほか{newItems.length - 5}件</small>}
              </div>
            )}

            {failed > 0 && <p className="import-warning">{failed}件を確認できませんでした。{retryButton}</p>}
            <div className="confirm-actions">
              {newItems.length > 0 ? <button type="button" onClick={importBookmarks}>{newItems.length}件を追加</button> : <Link className="confirm-primary-link" href="/saved">保存した募集を見る</Link>}
              <Link href="/saved">キャンセル</Link>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
