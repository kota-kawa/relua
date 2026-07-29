"use client";

import { useRef, useState, type FormEvent } from "react";

import { ClipboardPaste } from "@/components/icons";
import { validateTransferLink, type TransferLinkError } from "@/lib/local-data";

const ERROR_MESSAGES: Record<TransferLinkError, string> = {
  empty: "引き継ぎリンクを貼り付けてください。",
  invalid: "正しいURL形式の引き継ぎリンクを貼り付けてください。",
  "wrong-origin": "このサービスで作成された引き継ぎリンクだけを利用できます。",
  "wrong-path": "募集リストではなく、保存データの引き継ぎリンクを貼り付けてください。",
  "too-long": "リンクが長すぎます。送信元の端末からJSONバックアップで引き継いでください。",
  "no-data": "リンクに保存データが含まれていません。途中で切れていないか確認してください。",
};

export function TransferLinkForm({ onSubmit }: { onSubmit: (href: string) => void }) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");

  async function pasteFromClipboard() {
    try {
      if (!navigator.clipboard?.readText) throw new Error("Clipboard API unavailable");
      const pasted = await navigator.clipboard.readText();
      if (!pasted.trim()) {
        setError("クリップボードにリンクがありません。入力欄へ手動で貼り付けてください。");
        inputRef.current?.focus();
        return;
      }
      setValue(pasted.trim());
      setError("");
      inputRef.current?.focus();
    } catch {
      setError("クリップボードを読み取れませんでした。入力欄へ手動で貼り付けてください。");
      inputRef.current?.focus();
    }
  }

  function confirmLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = validateTransferLink(value, window.location.origin);
    if (!result.ok) {
      setError(ERROR_MESSAGES[result.error]);
      inputRef.current?.focus();
      return;
    }
    setError("");
    onSubmit(result.href);
  }

  return (
    <form className="transfer-paste-form" onSubmit={confirmLink} noValidate>
      <label htmlFor="transfer-link-input">引き継ぎリンク</label>
      <textarea
        ref={inputRef}
        id="transfer-link-input"
        value={value}
        rows={3}
        placeholder="https://…/import#b=…"
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => { setValue(event.target.value); setError(""); }}
      />
      {error && <p className="transfer-paste-error" role="alert">{error}</p>}
      <div className="transfer-paste-actions">
        <button type="button" className="paste-from-clipboard" onClick={pasteFromClipboard}><ClipboardPaste size={17} /> クリップボードから貼り付け</button>
        <button type="submit" className="confirm-transfer-link" disabled={!value.trim()}>内容を確認</button>
      </div>
      <small>この操作だけでは保存されません。次の画面で追加内容を確認できます。</small>
    </form>
  );
}
