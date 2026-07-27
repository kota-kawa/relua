import type { Opportunity } from "@/lib/types";

export type LoadedOpportunities = { items: Opportunity[]; missingIds: string[]; failedIds: string[] };

async function loadOne(id: string): Promise<{ id: string; item?: Opportunity; status: "ok" | "missing" | "failed" }> {
  try {
    const response = await fetch(`/api/opportunities/${encodeURIComponent(id)}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (response.status === 404) return { id, status: "missing" };
    if (!response.ok) return { id, status: "failed" };
    return { id, item: await response.json() as Opportunity, status: "ok" };
  } catch {
    return { id, status: "failed" };
  }
}

export async function loadOpportunities(ids: string[]): Promise<LoadedOpportunities> {
  const items: Opportunity[] = [];
  const missingIds: string[] = [];
  const failedIds: string[] = [];
  for (let offset = 0; offset < ids.length; offset += 8) {
    const batch = await Promise.all(ids.slice(offset, offset + 8).map(loadOne));
    batch.forEach((result) => {
      if (result.item) items.push(result.item);
      else if (result.status === "missing") missingIds.push(result.id);
      else failedIds.push(result.id);
    });
  }
  return { items, missingIds, failedIds };
}
