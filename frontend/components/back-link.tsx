"use client";

import { useRouter } from "next/navigation";

import { ArrowLeft } from "@/components/icons";

/**
 * Goes back through history when possible so search words, filters and scroll
 * position survive; the plain href is the no-JS / direct-visit fallback.
 */
export function BackLink({ fallback = "/", children }: { fallback?: string; children: React.ReactNode }) {
  const router = useRouter();
  return (
    <a
      className="back-link"
      href={fallback}
      onClick={(event) => {
        if (window.history.length <= 1) return;
        event.preventDefault();
        router.back();
      }}
    >
      <ArrowLeft size={17} /> {children}
    </a>
  );
}
