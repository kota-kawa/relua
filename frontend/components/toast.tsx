"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Check } from "@/components/icons";

const TOAST_EVENT = "relua:toast";

type ToastDetail = { message: string; actionLabel?: string; actionHref?: string };
type Toast = ToastDetail & { id: number; leaving?: boolean };

/** How long the confirmation stays put before it starts to go. */
const VISIBLE_MS = 3600;
/** Matches the leaving transition in globals.css. */
const LEAVE_MS = 220;

/** Fire-and-forget: any client component can announce a result without wiring state up the tree. */
export function showToast(message: string, action?: { label: string; href: string }) {
  if (!message) return;
  window.dispatchEvent(new CustomEvent<ToastDetail>(TOAST_EVENT, {
    detail: { message, actionLabel: action?.label, actionHref: action?.href },
  }));
}

export function Toaster() {
  const [toast, setToast] = useState<Toast | null>(null);
  /* A toast can carry an action link. Dismissing it on a timer while someone is
     reaching for that link takes the link away mid-gesture, and if they already
     focused it, focus falls back to <body>. So the countdown is suspended while
     the toast is hovered or holds focus, and starts over when it is released. */
  const [held, setHeld] = useState(false);
  const counterRef = useRef(0);

  useEffect(() => {
    function handleToast(event: Event) {
      const detail = (event as CustomEvent<ToastDetail>).detail;
      counterRef.current += 1;
      setToast({ id: counterRef.current, ...detail });
      setHeld(false);
    }
    window.addEventListener(TOAST_EVENT, handleToast);
    return () => window.removeEventListener(TOAST_EVENT, handleToast);
  }, []);

  const id = toast?.id;
  const leaving = Boolean(toast?.leaving);

  /* Two steps rather than one: the toast is marked as leaving, plays its exit,
     and only then leaves the tree. Each step is its own effect keyed on the
     toast id, so a newer toast is never cut short by the previous one's timer. */
  useEffect(() => {
    if (id === undefined || leaving || held) return;
    const timer = window.setTimeout(
      () => setToast((current) => (current?.id === id ? { ...current, leaving: true } : current)),
      VISIBLE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [id, leaving, held]);

  useEffect(() => {
    if (id === undefined || !leaving) return;
    const timer = window.setTimeout(() => setToast((current) => (current?.id === id ? null : current)), LEAVE_MS);
    return () => window.clearTimeout(timer);
  }, [id, leaving]);

  function hold() {
    setHeld(true);
    /* Catching a toast that has already begun its exit brings it back rather
       than leaving the user chasing a fading link. */
    setToast((current) => (current?.leaving ? { ...current, leaving: false } : current));
  }

  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && (
        /* Keyed by id so repeated toasts restart the entrance animation. */
        <div
          key={toast.id}
          className={`toast${toast.leaving ? " leaving" : ""}`}
          onPointerEnter={hold}
          onPointerLeave={() => setHeld(false)}
          /* React's onFocus/onBlur map to focusin/focusout, so they fire for the
             action link inside as well as the container. */
          onFocus={hold}
          onBlur={() => setHeld(false)}
        >
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
