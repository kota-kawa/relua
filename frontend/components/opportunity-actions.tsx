"use client";

import { useState } from "react";

import { BookmarkButton } from "@/components/bookmark-button";
import { CalendarPlus, Check, Download, ExternalLink, Share2 } from "@/components/icons";
import { calendarDetails } from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

function downloadText(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function OpportunityActions({ item }: { item: Opportunity }) {
  const [notice, setNotice] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);

  async function share() {
    const data = { title: `${item.company.name} ${item.event_name}`, url: window.location.href };
    try {
      if (navigator.share) await navigator.share(data);
      else {
        await navigator.clipboard.writeText(data.url);
        setNotice("URLをコピーしました");
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setNotice("共有できませんでした");
    }
  }

  const calendar = calendarOpen && typeof window !== "undefined" ? calendarDetails(item, window.location.href) : null;
  const hasCalendarDate = Boolean(item.event_start_date || item.deadline);

  return (
    <div className="detail-actions">
      <BookmarkButton id={item.id} />
      <button type="button" className="secondary-action" onClick={share}><Share2 size={18} /> 共有</button>
      <div className="calendar-action-wrap">
        <button type="button" className="secondary-action" onClick={() => setCalendarOpen((open) => !open)} disabled={!hasCalendarDate}>
          <CalendarPlus size={18} /> カレンダーに追加
        </button>
        {calendarOpen && calendar && (
          <div className="calendar-menu">
            <a href={calendar.googleUrl} target="_blank" rel="noreferrer"><ExternalLink size={16} /> Googleカレンダー</a>
            <button type="button" onClick={() => downloadText(`relua-${item.id}.ics`, calendar.ics, "text/calendar;charset=utf-8")}>
              <Download size={16} /> .icsをダウンロード
            </button>
          </div>
        )}
      </div>
      {notice && <span className="action-notice"><Check size={14} /> {notice}</span>}
    </div>
  );
}
