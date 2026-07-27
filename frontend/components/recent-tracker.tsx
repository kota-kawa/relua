"use client";

import { useEffect } from "react";

import { notifyLocalDataChanged } from "@/components/bookmark-button";
import { recordRecent } from "@/lib/local-data";

export function RecentTracker({ id }: { id: string }) {
  useEffect(() => {
    recordRecent(window.localStorage, id);
    notifyLocalDataChanged();
  }, [id]);
  return null;
}
