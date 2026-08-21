# ADR-0001: Next.jsを公開BFF、FastAPIを内部APIにする

- Status: Accepted
- Scope: 公開閲覧、REST API、デプロイ境界

## Context

公開サイトは未ログインで閲覧できる一方、募集データの管理操作は運営者用MCPに限定する必要がある。ブラウザからDB APIを直接呼ぶと、内部トークン、APIの詳細、将来の認証境界をクライアントへ露出しやすい。公開画面にはSSRとSEOも必要である。

## Decision

- Next.js Server Components が FastAPI の `/api/v1` を呼ぶ。
- RESTは `X-Internal-API-Token` を要求し、リバースプロキシで `/api/v1` を公開しない。
- ブラウザから追加取得が必要な保存リストだけ、Next.jsの同一オリジン route handler を経由する。
- FastAPIのMCPとOAuthは、RESTとは別の公開・認証境界として扱う。

## Consequences

公開画面とAPIを独立して検証・デプロイでき、内部トークンをブラウザへ渡さずに済む。反面、Next.jsのserver/runtime環境変数、APIの到達性、BFFのキャッシュ設定を両方管理する必要がある。具体的な経路は [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §2、§3、§5 を参照する。

## Code anchors

- `frontend/lib/api.ts`
- `frontend/app/api/opportunities/[id]/route.ts`
- `backend/app/main.py`
- `relua.conf`
- `docker-compose.yml`
