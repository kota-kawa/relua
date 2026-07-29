"use client";

import { useEffect } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { showToast } from "@/components/toast";
import { recordRecent } from "@/lib/local-data";

export function RecentTracker({ id }: { id: string }) {
  useEffect(() => {
    try {
      recordRecent(window.localStorage, id);
      notifyLocalDataChanged();
    } catch {
      showToast("閲覧履歴をこのブラウザに保存できませんでした");
    }
  }, [id]);
  return null;
}
