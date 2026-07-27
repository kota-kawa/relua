"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Check } from "@/components/icons";

const TOAST_EVENT = "relua:toast";

type ToastDetail = { message: string; actionLabel?: string; actionHref?: string };
type Toast = ToastDetail & { id: number };

/** Fire-and-forget: any client component can announce a result without wiring state up the tree. */
export function showToast(message: string, action?: { label: string; href: string }) {
  if (!message) return;
  window.dispatchEvent(new CustomEvent<ToastDetail>(TOAST_EVENT, {
    detail: { message, actionLabel: action?.label, actionHref: action?.href },
  }));
}

export function Toaster() {
  const [toast, setToast] = useState<Toast | null>(null);

  useEffect(() => {
    let counter = 0;
    let timer: number | undefined;
    function handleToast(event: Event) {
      const detail = (event as CustomEvent<ToastDetail>).detail;
      counter += 1;
      setToast({ id: counter, ...detail });
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setToast(null), 3600);
    }
    window.addEventListener(TOAST_EVENT, handleToast);
    return () => {
      window.removeEventListener(TOAST_EVENT, handleToast);
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && (
        /* Keyed by id so repeated toasts restart the entrance animation. */
        <div key={toast.id} className="toast">
          <Check size={16} aria-hidden="true" />
          <span>{toast.message}</span>
          {toast.actionLabel && toast.actionHref && (
            <Link href={toast.actionHref} onClick={() => setToast(null)}>{toast.actionLabel}</Link>
          )}
        </div>
      )}
    </div>
  );
}
