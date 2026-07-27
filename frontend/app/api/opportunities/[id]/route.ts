import { NextResponse } from "next/server";

import { ApiError, getOpportunity } from "@/lib/api";

type Context = { params: Promise<{ id: string }> };

export async function GET(_: Request, { params }: Context) {
  try {
    const item = await getOpportunity((await params).id);
    return NextResponse.json(item, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return NextResponse.json({ detail: "募集情報が見つかりません" }, { status: 404 });
    }
    return NextResponse.json({ detail: "募集情報を取得できません" }, { status: 502 });
  }
}
