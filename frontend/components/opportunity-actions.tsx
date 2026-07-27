"use client";

import { BookmarkButton } from "@/components/bookmark-button";
import { CalendarPlus, Share2 } from "@/components/icons";
import { showToast } from "@/components/toast";
import { calendarDetails } from "@/lib/local-data";
import type { Opportunity } from "@/lib/types";

function openCalendarFile(name: string, content: string) {
  const url = URL.createObjectURL(new File([content], name, { type: "text/calendar;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function OpportunityActions({ item }: { item: Opportunity }) {
  async function share() {
    const data = { title: `${item.company.name} ${item.event_name}`, url: window.location.href };
    try {
      if (navigator.share) await navigator.share(data);
      else {
        await navigator.clipboard.writeText(data.url);
        showToast("URLをコピーしました");
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      showToast("共有できませんでした");
    }
  }

  const hasCalendarDate = Boolean(item.event_start_date || item.deadline);

  function addToDeviceCalendar() {
    const calendar = calendarDetails(item, window.location.href);
    if (!calendar) return;
    openCalendarFile(`relua-${item.id}.ics`, calendar.ics);
    showToast("カレンダーファイルを開いて追加してください");
  }

  return (
    <div className="detail-actions">
      <BookmarkButton id={item.id} />
      <button type="button" className="secondary-action" onClick={share}><Share2 size={18} /> 共有</button>
      <button type="button" className="secondary-action" onClick={addToDeviceCalendar} disabled={!hasCalendarDate}>
        <CalendarPlus size={18} /> デバイスのカレンダーに追加
      </button>
    </div>
  );
}
