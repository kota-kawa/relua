# ADR-0003: 保存データをブラウザに保持し、公開コードで共有する

- Status: Accepted
- Scope: ブックマーク、最近見た募集、端末間引き継ぎ、共有リスト

## Context

MVPではユーザーアカウントを作らず、ログインなしの閲覧体験を維持する。サーバー側に個人の保存履歴を持つと、認証・個人情報・削除要求・同期競合の責務が増える。UUIDを多数含むURLはQRや共有シートに不向きである。

## Decision

- ブックマークと最近見た募集は `localStorage` に保存する。
- 共有・引き継ぎはURLフラグメントを使い、サーバーに保存データを送らない。
- 新形式は募集ごとの8文字 `public_code` を連結する。旧UUID形式も後方互換で読み込む。
- インポート時にサーバーの現在データを再取得し、存在する募集だけを既存localStorageへマージする。
- URL長の上限を超える場合はJSON/CSVバックアップを使う。

## Consequences

アカウントなしで個人データを扱え、共有リンクの内容がサーバーログに現れにくい。反面、端末間の自動同期、サーバーからの一括削除、ブラウザストレージ消失からの復元は提供しない。`public_code` は公開参照用であり、書き込みの対象識別を置き換えるものではない。

## Code anchors

- `frontend/lib/local-data.ts`
- `frontend/lib/constants.ts`
- `frontend/components/saved-dashboard.tsx`
- `frontend/components/import-bookmarks.tsx`
- `backend/app/models.py` の `public_code`
- `backend/app/services/opportunities.py` の公開参照解決
