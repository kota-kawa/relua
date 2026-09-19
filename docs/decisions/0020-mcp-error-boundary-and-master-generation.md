# ADR-0020: MCPツールの失敗を一箇所で処理し、マスタキャッシュをスキーマ世代で回す

- Status: Accepted
- Scope: `backend/app/mcp_server.py`、`backend/app/services/master_cache.py`、`backend/app/services/oauth.py`
- Amends: [ADR-0002](./0002-mcp-write-safety.md)

## Context

ADR-0002 は MCP 書き込みを「検証・冪等化・監査・楽観ロック」で守ると定めた。その実装が37ツールへ手書きで展開された結果、3つのずれが生まれていた。

第一に、`mcp_server.py` には例外境界が1つも無かった。FastMCP の下位層は捕捉されなかった例外を `str(e)` としてツール結果に載せ、`main.py` の包括ハンドラは MCP のツール呼び出しには効かない。未認証で叩ける `search_opportunity` の `query` には長さ上限も無かったため、巨大な入力で `OperationalError` を誘発すると、テーブル・カラム構成を含むSQL全文とバインド値がそのまま返った。

第二に、失敗記録が12箇所に手書きされ、ほぼ同型の `except DomainValidationError:` が7回複製されていた。`patch_opportunity` だけが楽観ロック競合・固定値エラー・差分なしの3分岐で記録を取りこぼしており、ADR-0002 が要求する「失敗も監査に残す」が守られていなかった。複製されたコードでは、レビューで欠けた分岐に気づけない。

第三に、`invalidate_master_cache()` はどこからも呼ばれていなかった。呼べる場所が無かったからである。マスタ行は Alembic マイグレーション以外から変更されない。そのためマイグレーション直後の最大1時間、`get_master_values` が広告する値を `add_opportunity` が拒否し、新しく追加されたマスタは見えないままだった。

加えて、広告していた OAuth スコープ（`scopes: ["mcp"]`）は発行時にも検証時にも参照されていなかった。

## Decision

- ツールを個別に直すのではなく、**登録後に一括して例外境界をかぶせる**。意図的な `ToolError` は素通しし、それ以外は traceback 付きでサーバー側に記録して固定文だけを返す。後から追加されるツールも自動的に保護される。
- 失敗記録を1つのヘルパーに集約し、`patch_opportunity` を含む全分岐をそこへ通す。`request_id` / `client_name` は共有の注釈型に統一する。インライン再宣言では `strip_whitespace` が効かず、`"req-1 "` と `"req-1"` が別操作として二重書き込みになっていた。
- 匿名ツールの文字列引数にも、認証必須ツールと同じ長さ上限を課す。
- マスタキャッシュのキーに**適用済みスキーマリビジョン**を含める。マスタ行が変わり得るのはマイグレーションのときだけなので、データが変わるのと同じ手順でキーが回る。到達不能だった `invalidate_master_cache()` は削除する。
- `preview_opportunity_patch` と `validate_opportunity` は `readOnlyHint` の宣言どおり**監査行を書かない**。どちらも正しいpayloadに収束するまで再試行される前提の道具であり、試行ごとに `audit_logs` が伸びるのは不適切である。連続失敗の検知はRedisカウンタで足りる。
- OAuth スコープは発行時に `DEFAULT_SCOPE` へallowlistし、`authenticate_access_token` が保存済みスコープを照合する。強制点はミドルウェアが通る認証関数に置き、ツール定義側には置かない。

## Consequences

内部エラーの詳細はクライアントから見えなくなる。運用時の切り分けはサーバー側ログが正本になる。

マイグレーションを含むデプロイのたびにマスタキャッシュのキーが回るため、デプロイ直後に1回だけ再取得が走る。固定値を最大1時間配り続けるより安い。

`preview`/`validate` の失敗は `audit_logs` に残らなくなる。書き込みを伴うツールの失敗記録は従来どおり残るため、ADR-0002 の監査要件は満たされる。

ツール単位のデコレータではなく登録後のラップに依存するため、将来 FastMCP の登録APIが変わった場合はこの境界の再確認が必要である。
