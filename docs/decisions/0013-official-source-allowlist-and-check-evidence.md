# ADR-0013: 企業公式sourceをallowlistと確認証跡で保護する

- Status: Accepted
- Scope: 募集の一次情報URL、企業収集元、収集確認記録
- Amends: [ADR-0010](./0010-write-verification-separation.md)

## Context

求人集約・口コミサイトのdenylistだけでは、未知の第三者サイトや非公式ページを一次情報として拒否できない。また `record_collection_check` が任意URLやURLなしで成功すると、実際の募集ページを確認しなくても `source_checked_at` を進められる。

## Decision

- 企業に収集対象がある場合、その有効な `collection_sources` を企業別の公式source allowlistとして扱う。収集対象自体を無効化しても、既知の公式sourceという判断は維持する。
- 募集の新規登録と一次情報URL変更は、登録済みsourceと同一URL、同一ホスト、またはその子ホストに限る。親・兄弟を含む別ホストは、公式性を確認して `add_collection_source` で明示登録してから使う。
- `record_collection_check.source_url` を必須にする。`found` は `opportunity_id` も必須とし、確認URLが募集の正規化済み `source_url` と一致するときだけ `source_checked_at` を進める。
- `no_opening`、`unreachable`、`needs_review` は、登録済みかつ有効なsource URLへの確認としてだけ記録する。
- denylistは既知の集約サイトを早期拒否する補助として残す。収集対象が未作成の企業はallowlistの信頼点がないため、従来どおりdenylist検証までとする。

## Consequences

監視対象企業では、未知の第三者ホストを募集書き込み経由で紛れ込ませにくくなり、確認日時が指す証拠URLも一意になる。新しい公式ホストを使う場合は、先に収集元を追加する明示操作が必要になる。未監視企業も同じ保護を得るには、先に企業の収集対象を作成する。

## Code anchors

- `backend/app/services/normalization.py`
- `backend/app/services/opportunities.py`
- `backend/app/services/collection_targets.py`
- `backend/app/schemas.py` の `CollectionCheckRequest`
- `backend/tests/test_collection_targets.py`
