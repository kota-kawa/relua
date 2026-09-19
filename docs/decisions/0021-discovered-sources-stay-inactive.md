# ADR-0021: 確認記録で見つかった収集元は無効状態で登録する

- Status: Accepted
- Scope: `backend/app/services/collection_targets.py` の `record_collection_check`
- Amends: [ADR-0013](./0013-official-source-allowlist-and-check-evidence.md)

## Context

ADR-0013 は、企業公式の収集元を allowlist で保護し、新しい公式ホストを使う場合は**先に収集元を追加する明示操作**を必要とすると定めた。

しかし `record_collection_check` の `discovered_sources` パラメータは、確認記録の副作用として `CollectionSource` を有効状態で作成していた。結果、確認を1件記録するだけで allowlist が広がり、直後の `add_opportunity` が `_ensure_company_source_allowed` を通過してしまう。`create_collection_source` のような独立した監査アクションも残らず、確認記録の `after` に埋もれるだけだった。ADR-0013 が意図した「明示操作」が、実質的に迂回できる状態だった。

## Decision

`discovered_sources` の登録自体は残す。収集中に見つけた候補URLを記録できることには価値があり、運営者が後から確認して採用する流れを壊さないためである。ただし次の2点を変える。

- 登録は `is_active=False` で行う。有効化は明示操作のままとし、allowlist は確認記録の副作用では広がらない。
- 登録時に独立した監査ログ（`collection_source_create`）を残す。確認記録の payload に埋もれない形で追跡できるようにする。

## Consequences

確認記録で見つけた収集元を実際に使うには、運営者による有効化が1ステップ必要になる。ADR-0013 の意図どおり、公式判定の拡大は常に明示操作を経由する。

既存の「確認記録で見つけた採用ページがそのまま使える」挙動に依存していたフローは、有効化の操作を挟む必要がある。該当するテストは新しい意図へ更新済みである。
