# ADR-0011: 募集の重複判定をexact／probableの2段階にする

- Status: Accepted
- Scope: 募集情報の新規登録における重複検出（`add_opportunity`／`upsert_opportunity`／`validate_opportunity`）

## Context

`find_exact_duplicates` は「同じ企業＋正規化した同名イベント」だけで重複を判定していた。これは新卒採用の実態と食い違う。企業の公式ページでは、対象学年（28卒／29卒）、開催地（東京／大阪）、実施ターム（第1ターム／第2ターム）、コース（SWE／ML）が違っても、イベント名そのものは同じ文言を使い回すことが多い。

この結果、「YCP Solidiance + 新卒・インターン採用エントリー」のように、企業＋イベント名だけが一致する新規登録が `add_opportunity` で拒否され、`upsert_opportunity` では既存の（実際には別学年・別コースの）登録をそのまま返してしまう。呼び出し側のMCPクライアント（LLM）が「もう存在している」と誤判定すると、別年度・別コースの募集が登録されずに落ちる。`allow_duplicate=true` という回避策はあるが、それを使うべきかどうかの判断をクライアント側の推測に委ねてしまっていた。

## Decision

- 募集の重複候補は「同じ企業＋正規化した同名イベント」で抽出したうえで、対象卒業年（`graduation_years`）・実施開始日（`event_start_date`）・対象職種（`job_categories`）のいずれかが両側で明確に食い違えば `probable`、そうでなければ `exact` に分類する（`classify_duplicate_candidates`）。片側にしか値がない項目（例: どちらかが実施日未定）は差異の根拠にしない。
- `exact` 重複だけを従来どおり書き込み拒否の対象にする。`add_opportunity` はエラーを返し、`upsert_opportunity` は既存を返す。`allow_duplicate=true` は `exact` 重複を意図的に複数登録する場合にだけ使う。
- `probable` 重複は書き込みを拒否しない。新規登録として保存したうえで、`warnings` に既存候補を含めて返し、運営者・呼び出し側が誤って別募集を作っていないか確認できるようにする。
- `validate_opportunity` は `duplicates`（exact候補、一次情報URL一致を含む）と `warnings`（probable候補を含む）を分けて返す。
- 「企業は一致するがイベント名が一致しない」候補（probably separate）は従来どおり `find_similar_opportunities` の緩い部分一致で個別に確認する対象とし、本ADRの自動判定には含めない。

## Consequences

同じイベント名を学年・拠点・タームで使い回す企業でも、別募集として正しく登録できるようになる。`upsert_opportunity` が誤って別募集を握りつぶすことがなくなる。反面、対象学年・実施日・対象職種のいずれも一致しない紛らわしい重複（例: 本当に同じ募集を違う卒業年で二重登録してしまった場合）は自動拒否されず、`warnings` を見て運営者が判断する必要がある。

## Code anchors

- `backend/app/services/opportunities.py` の `classify_duplicate_candidates` / `_distinguishes_same_named_postings` / `find_probable_duplicates` / `probable_duplicate_warning`
- `backend/app/mcp_server.py` の `add_opportunity` / `upsert_opportunity` / `validate_opportunity` / `_write_warnings`
- `backend/tests/test_opportunities.py`、`backend/tests/test_mcp_tools.py`
