# 利用・運用ガイド

relua をローカルで起動する手順、MCP クライアントの接続設定、MCP ツールの契約、内部 REST API、日次運用、本番公開前の設定をまとめた手順書です。サービスの概要と設計の見どころは [`../README.md`](../README.md)、内部構造は [`../ARCHITECTURE.md`](../ARCHITECTURE.md) を参照してください。

依存ライブラリは実装時点の最新安定版を固定しています。TypeScriptとESLintだけは、Next.js 16.2.12が実際にビルド・lintできる最新互換版（TypeScript 6.0.3 / ESLint 9.39.5）です。TypeScript 7とESLint 10は現行Next.jsの利用するAPIに未対応のため採用していません。

## 起動

必要なものは Docker と Docker Compose だけです。

```bash
cp .env.example .env
docker compose up --build
```

- Web: <http://localhost:3100>
- 運営者用MCP（ローカルホスト限定）: `http://localhost:8000/mcp`

PostgreSQLとRedisはホストへポートを公開しません。FastAPIも`127.0.0.1`だけにバインドされ、REST APIは内部トークン、MCPは運営者用Bearerトークンがなければ利用できません。

初回起動時にAlembicが固定値マスタまで投入します。本番用の募集情報は空の状態です。

### UI確認用デモデータ

```bash
docker compose exec api python -m app.scripts.seed_demo
```

投入される企業・募集はすべて架空です。実在情報と混同しないよう、本番環境では実行しないでください。同じコマンドを再実行してもrequest IDにより重複しません。

## MCPクライアント設定

接続方法は2通りあります。手元の端末から使うだけなら固定トークン、ChatGPTやClaudeのWeb版から使うならOAuthです。

### 固定トークン接続（既定）

MCPクライアントに次のURLとヘッダーをStreamable HTTPサーバーとして登録します。

```text
http://localhost:8000/mcp
```

```text
Authorization: Bearer <MCP_API_TOKENの値>
```

既定ではAPIポートがループバック限定のため、別端末やインターネットからは直接接続できません。リモートサーバー上で運用する場合は、SSHポートフォワードまたは運営者専用VPNを通して接続してください。

### OAuth接続（ChatGPT・Claude）

ChatGPTやClaudeのWeb版は任意のヘッダーを設定できないため、固定トークンでは接続できません。代わりに、MCPのURLだけを登録し、ブラウザでreluaのログイン画面に遷移してパスワードを入力する方式を用意しています。

有効化するには `.env` に次を設定します。

```bash
MCP_OAUTH_ENABLED=true
MCP_PUBLIC_URL=https://<公開ホスト名>
MCP_OPERATOR_PASSWORD=<12文字以上の固有パスワード>
```

クライアントには次のURLだけを登録します。認証情報の入力欄は空のままにしてください。

```text
https://<公開ホスト名>/mcp
```

接続時の流れは次のとおりです。

1. クライアントが認証なしでMCPを初期化し、ツール一覧と各ツールの認証要否を取得する
2. 読み取り系ツール（`search_opportunity`、`get_opportunity`、`get_master_values`、`get_sectors`、`find_similar_opportunities`）はそのまま利用できる
3. 書き込み系ツールを呼ぶと、401の `WWW-Authenticate` を受けてOAuthフローを開始する
4. `/.well-known/oauth-protected-resource/mcp` と `/.well-known/oauth-authorization-server` を読み、`/oauth/register` に自分自身を登録する
5. ブラウザが `/oauth/authorize` へ遷移し、reluaの接続許可画面が開く
6. `MCP_OPERATOR_PASSWORD` を入力すると、クライアントが `/oauth/token` でアクセストークンとリフレッシュトークンを受け取る

リフレッシュトークンは既定で無期限（`MCP_REFRESH_TOKEN_TTL_DAYS=0`）です。アクセストークンは1時間で切れますが、クライアントがリフレッシュトークンで自動更新するため、**一度接続すれば再ログインは不要**です。使うたびにトークンは入れ替わり、古いトークンが再利用された場合はその接続全体を失効させます。

この方式ではMCPエンドポイントをインターネットへ公開します。公開する場合は、前段にTLS終端のリバースプロキシを置き、`FORWARDED_ALLOW_IPS` にそのプロキシの**コンテナから見た接続元**を設定してください。composeのユーザランドプロキシ経由では接続元がdocker bridgeのゲートウェイになるため、既定値は `127.0.0.1,172.16.0.0/12` です。

`FORWARDED_ALLOW_IPS=*` は設定しないでください。`*` を指定するとuvicornが `X-Forwarded-For` の先頭を無条件に信頼するため、ヘッダを差し替えるだけでログイン回数制限を回避できます。ログイン回数制限は接続元IP・client_id・全体の3段で数えるため、接続元IPが解決できない構成でも総当たりは全体上限で止まります。

登録自体は誰でも行えますが、登録しただけでは何も取得できません。トークンを発行できるのは運営者パスワードを入力したときだけです。

## MCPツール

| ツール | 認証 | 用途 |
| --- | --- | --- |
| `search_opportunity` | 不要 | キーワード・固定値・登録日時・最終編集日時で絞り込んだ概要をカーソル方式で返す |
| `get_opportunity` | 不要 | IDまたは公開コードで1件を全項目取得する |
| `get_master_values` | 不要 | 選択可能な固定値マスタを全件返す |
| `get_sectors` | 不要 | 指定した業界に属する業種だけを返す |
| `find_similar_opportunities` | 不要 | 同じ企業の登録済み募集を探し、二重登録を防ぐ |
| `find_opportunities_by_source_url` | 不要 | 計測パラメータ等を除いた一次情報URLで既存募集を探す |
| `resolve_company` | 必要 | 正式名・別名の完全一致を優先し、部分一致・タイプミスの企業候補を確認用に返す |
| `add_company_alias` | 必要 | 公式情報で同一企業と確認した略称・英語名・旧社名を登録する |
| `set_company_industries` | 必要 | 既存企業の業界・業種カテゴリを複数件まとめて設定する（収集対象の有無を問わない） |
| `update_company_profile` | 必要 | 企業の一言説明・事業内容の本文・主な事業・公式サイトURLを設定する。企業ページに表示される |
| `update_company_profiles` | 必要 | 最大50社のプロフィールを1回で更新し、各社の保存成功・拒否・結果未確認と集計を返す |
| `list_companies_missing_profile` | 必要 | 一言説明または事業内容本文が未登録・空欄の企業を、収集対象の有無を問わず一覧する |
| `list_company_profile_history` | 必要 | 企業IDを指定し、DB内のプロフィール変更履歴を取得する。DB保持は90日、古い記録は運用アーカイブに保存 |
| `merge_company` | 必要 | 公式情報で同一と確認した重複企業を、募集・別名・分類・収集対象ごと統合する |
| `delete_company_alias` | 必要 | 誤登録された企業別名を削除する |
| `validate_opportunity` | 必要 | 保存せずに検証し、固定値の誤りと重複の疑いを返す |
| `add_opportunity` | 必要 | 募集情報を1件追加する |
| `update_opportunity` | 必要 | 既存の募集情報を全項目置換で更新する |
| `preview_opportunity_patch` | 必要 | 部分更新を保存せず検証し、変更差分と警告を返す |
| `patch_opportunity` | 必要 | 楽観ロック付きで指定項目だけを更新する |
| `update_recruitment_status` | 必要 | 楽観ロック付きで募集状況と締め切りだけを更新する |
| `verify_opportunity` | 必要 | 一次情報に変更がないことを記録し、公式情報確認日時と日付矛盾の再確認スケジュールを更新する |
| `preview_delete_opportunity` | 必要 | 削除対象と公開表示・関連履歴への影響を保存せず確認する |
| `delete_opportunity` | 必要 | 楽観ロック付きで募集情報を公開データから論理削除する |
| `restore_opportunity` | 必要 | 論理削除した募集を同じID・公開コードのまま復元する |
| `list_recent_writes` | 必要 | DB内の監査履歴を絞り込み、成功・拒否・結果未確認件数と個別結果を取得する。DB保持は90日でアーカイブは集計しない |
| `list_stale_opportunities` | 必要 | 未確認の日付矛盾を最優先に取得する。明示的な確認後は `days` 経過まで待機。`exclude_expired=true` で期限超過を除外できる |
| `list_collection_targets` | 必要 | 情報収集対象の企業を検索・一覧し、採用ページ未登録や現在の確認状況で絞り込む |
| `list_unmonitored_companies` | 必要 | 企業マスタにあり、まだ情報収集対象を持たない企業を一覧する |
| `get_collection_target` | 必要 | 収集対象、公式ページ、登録済み募集を1件取得する |
| `get_company_maintenance_context` | 必要 | 企業の全募集、公式URL、各募集の最終確認日時をまとめて取得する |
| `get_collection_queue` | 必要 | 未確認または再確認期限を過ぎた企業を優先度順に返す。少数社ずつ確認と保存を完了する |
| `list_undercovered_companies` | 必要 | 未確認または再確認期限を過ぎた企業を、定期再確認対象の募集が少ない順で返す |
| `list_collection_checks` | 必要 | DB内の企業ごとの確認履歴を新しい順に返す。DB保持は90日、古い記録は運用アーカイブに保存 |
| `add_collection_target` | 必要 | 既存CompanyのIDまたは新規企業名、所属業界、優先度、確認間隔、公式ページを収集対象へ追加する |
| `update_collection_target` | 必要 | 収集対象を部分更新または無効化する |
| `add_collection_source` | 必要 | 収集対象へ企業公式ページを追加する |
| `update_collection_source` | 必要 | 公式ページのURL・種類・有効状態を部分更新する |
| `record_collection_check` | 必要 | 個別募集と企業ページの確認を区別し、結果と次回確認日を記録する。確認不能・要確認が続く場合は再確認間隔を延ばす |

`search_opportunity` の登録日時・最終編集日時は `created_at_after`／`created_at_before` と `updated_at_after`／`updated_at_before` で絞り込みます。境界は両端を含み、64文字以内のISO 8601日時で指定します。タイムゾーンを省略した値はUTCとして扱います。応答の `created_at` と `updated_at` で登録・編集時刻を確認できます。

続きを取得するときは、応答の `next_cursor` を検索条件を変えずに次の呼び出しの `cursor` へ渡します。日時範囲を含むすべての条件がカーソルに結び付くため、条件を変えたカーソルは拒否されます。`next_cursor` が `null` になれば終端です。カーソルは検索開始時点と並び順を保持するため、取得済みの募集を途中で削除してもページ境界がずれません。

企業ページのプロフィールを整備するときは、`list_companies_missing_profile` で一言説明または本文が未登録・空欄の企業を探します。一覧には企業ID、現在のプロフィール、公式サイトURL、`updated_at` が含まれるため、取得済みのIDを `resolve_company` で再取得する必要はありません。過去の変更理由や出典を確認する必要がある企業には `list_company_profile_history` を使います。プロフィール整備だけなら、募集用の固定値・重複・収集対象の確認は不要です。

複数社には `update_company_profiles` を使います。`updates` に1〜50件を渡し、各社の `company_id`、一覧から取得した `expected_updated_at`、更新項目、公式ページの `source_url`、固有の `request_id` を指定します。各社を個別に検証・保存するため、一部の拒否で成功分は取り消されません。古い `expected_updated_at` はその企業だけ拒否します。応答は入力順の `items` と次の集計を返し、説明文の全文を再送しません。

| 集計 | 意味 |
| --- | --- |
| `succeeded_count` | 保存成功数。変更なし・処理済みの再試行も含む |
| `changed_count` | 今回実際に変更した数 |
| `replayed_count` | 同じ内容・`request_id` による処理済みの再試行数 |
| `failed_count` | 入力不備・更新競合・対象不明などで拒否した数 |
| `unknown_count` | 内部エラーで保存結果の確認が必要な数。各項目の `success` は `null` |

通信失敗や結果未確認の場合は、同じ内容・各社の `request_id` で再送できます。入力を直す場合は新しい `request_id` を使います。公式情報の確認が済んだ少数社から保存しても構いません。未保存の説明が次の定期実行へ引き継がれると仮定せず、Reluaの保存状態を基準に再開してください。一覧の対象は更新によって減るため、更新後は `page=1` から残りを取得します。

一括更新はプロフィールの書き込み呼び出しを減らしますが、外部AIクライアントによる公式ページの調査や実行の上限を変更するものではありません。1社だけの更新には従来の `update_company_profile` も使えます。

書き込みツールは運営者本人の認証済み接続だけが呼べるため、1分あたりの操作上限は設けていません。大量登録・一括更新でも各操作の入力検証、request IDによる冪等化、監査ログは通常どおり適用されます。OAuthのログイン試行と動的クライアント登録には、公開エンドポイントを保護するための回数制限を引き続き適用します。

同じ内容・`request_id` の再送保証期間は90日です。90日より前の再送防止記録は日次でアーカイブへ移すため、古いIDの再送は再実行される場合があります。古い実行を再開するときは現在の保存状態を確認して、新しい操作のIDを発行してください。

各ツールは `title`、`annotations`（`readOnlyHint` など）、`outputSchema` を公開します。読み取り専用かどうかがクライアント側で判別できるため、ChatGPTやClaudeは読み取りツールの自動承認を判断できます。

### 実行単位の書き込み照合

定期実行や会話の作業を始めるときに、UUIDなどを含む `run_id`（8〜100文字）を生成し、同じ実行のすべての書き込みツールにトップレベル引数として指定します。`payload` や一括更新の `updates` 内には入れません。`request_id` は従来どおり操作ごとに固有の値です。`run_id` は任意で、冪等性の判定には含まれません。処理済みの操作を別の実行から再試行しても、元の監査記録の `run_id` は書き換わらず、新たな保存実績には数えません。

報告前に `list_recent_writes(run_id="実行ID")` で実績と拒否された理由を照合します。`client_name` と `entity_type` も併用できます。`limit` は1ページの件数（最大100）、`page` は1から始まるページ番号で、`has_more=true` なら次のページを取得します。処理中に履歴が増えるとページ位置も変わるため、全件の照合は書き込みを終えてから行います。

応答の `total_count`、`succeeded_count`、`failed_count`、`unknown_count` は、絞り込み条件に一致する**全監査記録**を集計し、取得ページの件数には依存しません。企業数・募集数・ツール呼び出し数ではなく、募集登録に付随する確認記録も別の成功記録です。個別の `outcome` は `succeeded`（保存成功）、`rejected`（拒否）、`unknown`（記録された内部エラーで保存結果未確認）です。結果未確認は拒否数に含みません。保存後の応答エラーでは、同じ操作について成功記録と結果未確認の記録が残る場合もあります。

未実行の操作、通信失敗、ツールの引数検証や内部エラーなどで監査記録が作られなかった操作は集計に含まれません。履歴がないことだけで未保存と断定せず、通信失敗や結果未確認は同じ内容・同じ `request_id` で再試行します。入力を直す場合は新しい `request_id` を使います。`run_id` を省略した操作や移行前の記録には `run_id=null` が残り、実行IDから過去の履歴を推測して補いません。

すべての募集情報には詳細ページのURL（`url`）が含まれます。組み立てには `NEXT_PUBLIC_SITE_URL`（APIコンテナには `SITE_URL`）を使うため、公開環境では実際のサイトURLを設定してください。

推奨操作順は次のとおりです。

1. `get_master_values` で選択可能な固定値を取得し、業種は `get_sectors` で業界配下に絞る
2. 企業名が略称・英語名・誤記の可能性がある場合は `resolve_company` で候補を取得する
3. 部分一致・曖昧一致の候補を公式情報で同一企業と確認できた場合だけ `add_company_alias` で別名を登録する
4. `find_similar_opportunities` と `find_opportunities_by_source_url` で同じ募集が登録済みでないか確認する
5. 内容に自信がない場合は `validate_opportunity` で先に検証する
6. `add_opportunity` または `update_opportunity` を呼ぶ
7. 検証エラーでは、返された項目をすべて修正し、同じ `request_id` で再試行する

企業の自動的な同一視に使うのは、正規化した正式名または登録済み別名の完全一致だけです。部分一致と
PostgreSQL `pg_trgm` によるタイプミス検索は候補提示に限られ、MCPが勝手に企業を統合することはありません。
別名の追加・削除は監査ログへ記録され、`request_id` により安全に再試行できます。

企業の業界・業種カテゴリは `set_company_industries` で複数指定できます。例えば小売・流通/ECと
IT・通信/Webサービスを同じ企業へ登録できます。指定した一覧は全置換で、先頭が代表カテゴリです。
追加時は既存カテゴリも一覧に含め、`request_id` は同じ内容の再試行にだけ再利用してください。

企業の事業内容は `update_company_profile` で登録します。就活生が企業ページだけでその企業を理解できる分量を
前提にしており、次の4項目を指定できます。

| 項目 | 制約 | 役割 |
| --- | --- | --- |
| `business_summary` | 30〜200文字 | 何をしている会社かを言い切る1〜2文。企業ページの冒頭と検索結果の説明文になる |
| `description` | 300〜4000文字 | 事業内容の本文。空行で区切った段落がそのまま段落として表示される |
| `business_areas` | 1〜6件（各`name` 2〜60文字、`description` 60〜400文字） | 主な事業。事業ごとの見出し付きブロックとして表示される |
| `website_url` | https必須 | 公式サイトへのリンク |

各項目には最小文字数があり、一言だけの登録は入口で拒否されます。呼ぶ前に公式サイトの会社概要・事業紹介・IR資料を
読み、確認できた事実をまとめてください。`description` には「主力事業と収益の源泉」「主な製品・サービスと提供先」
「顧客・市場」「事業の規模」「技術や体制の特徴」「近年の事業展開」のうち確認できた情報をできるだけ多く含めます。
将来性・成長性・働きやすさなどの評価や見通しは登録できません。

カテゴリ設定と違い部分更新で、省略した項目は現在の値を維持し、`null` を明示した項目だけ削除されます。
`business_areas` だけは指定した内容で全置換します。`source_url` には、その内容を確認した企業自身のページを
必ず渡してください。保存されるのは上の4項目だけで、確認したページは監査ログに残ります。

登録した内容は `/companies/{公開コード}` の企業ページと、募集詳細の企業名リンク先に表示されます。
企業ページが検索対象になるのは `business_summary` と `description` の両方がある場合です。現在の募集の有無は件数として表示するだけで、index可否には使いません（ADR-0023）。

`add_opportunity` と `update_opportunity` の `payload` では、日付を `YYYY-MM-DD`、URLを `https` で指定します。更新は部分更新ではなく全項目置換のため、`get_opportunity` で現在値を取得してから送ってください。状況や締め切りだけを直す場合も、`get_opportunity` の `updated_at` を `expected_updated_at` として `update_recruitment_status` へ渡します。公式ページを再確認して内容が変わっていない場合は、登録済みの一次情報URLと確認日時を `verify_opportunity` へ渡してください。これは `source_checked_at` のみを更新し、監査ログでは状況更新と区別されます。status更新自体は一次情報確認とは見なさず、`source_checked_at` を変更しません。

書き込み・更新の応答に `warnings` が含まれる場合、保存自体は成功していますが公式情報を再確認してください。`締切` なのに締め切りまたは実施開始日が未来、`募集中` なのに締め切りまたは実施終了日が過去、といった日付と募集状況の矛盾を検出します。締切延長・追加募集・中止があり得るため、Reluaは警告だけを返し、状態を自動変更しません。

定期的な公式情報の再確認対象は `募集予定`、`募集中`、`通年募集` です。`募集中` のまま締め切り日または実施終了日を過ぎた募集は `list_stale_opportunities` で必ず確認し、公式情報に従って `締切` へ更新してください。すでに `締切`、`不明`、その他の終了状態になっている募集は、要確認キューと企業単位の保守コンテキストから除外します。`get_collection_queue` は新しい募集の発見が必要な企業も返すため、その企業の募集一覧が空になる場合があります。

その他の一部項目だけを直す場合は、`get_opportunity` が返す `updated_at` と変更項目を `preview_opportunity_patch` へ渡し、差分を確認してから同じ内容を `patch_opportunity` へ渡します。サーバー側で現在値とマージした後に全項目を検証します。取得後に別の更新があった場合は `expected_updated_at` の不一致として拒否されるため、古い値で上書きしません。

誤登録などを公開データから削除する場合は、`preview_delete_opportunity` で対象と影響を確認し、返された `id` と `expected_updated_at` を `delete_opportunity` へ渡します。取得後に更新された募集は削除を拒否します。削除は論理削除で、検索、詳細ページ、収集対象の登録済み募集一覧から隠れますが、募集情報、収集確認履歴との関連付け、監査ログは保持されます。

誤って削除した場合は、削除結果または `list_recent_writes` で確認できる募集情報IDを `restore_opportunity` へ渡します。元のUUIDと公開コードを維持するため、復元後は既存のブックマークと共有リンクも再び利用できます。削除と復元はいずれも `request_id` で冪等化されます。

`source_url` には企業自身の採用ページなど一次情報を指定します。求人サイト・就活情報サイト・口コミサイトのURLは拒否されます。さらに収集対象が登録済みの企業では、有効な `collection_sources` が企業別の公式source allowlistになります。同一URLまたは同じ公式ホスト配下以外のURLは拒否されるため、新しい公式ホストを使う場合は、確認後に `add_collection_source` で先に登録してください。未監視企業にも同じ保護を適用するには、募集登録より先に収集対象を作成します。自由記述の項目には出典の文章を転記せず、日程・対象・報酬などの事実だけを要約して記載し、担当者名などの個人名と個人宛の連絡先は含めません。

同じ企業・同名イベントでも、対象卒業年・実施開始日・対象職種のいずれかが明確に異なる場合は別募集として保存し、確認用warningを返します。これらも一致するexact重複だけを拒否します。全く同じ日程・コースを意図的に複数登録する場合に限り、`add_opportunity` の `allow_duplicate` を `true` にしてください。復元も同じ2段階判定を使います。

一次情報URLは、ホスト名の大文字小文字、末尾スラッシュ、フラグメント、既知の計測パラメータを除いて照合します。同じ公式ページに複数募集が掲載される場合があるため、URL一致は一律の登録拒否ではなく、既存募集を確認するための警告として扱います。

### 企業単位の情報収集キュー

運営者用MCPでは、募集がまだ登録されていない企業も収集対象として管理できます。収集優先度は企業の評価や公開ランキングではなく、公式ページを確認する内部の作業順です。収集対象の読み取りを含め、これらのツールはすべて認証を必要とします。

収集対象は**1企業につき1件**です。事業が複数業界にまたがる企業は、収集対象を分けるのではなく `industries` に複数の業界・業種を指定します（例: Ubie株式会社は IT・通信/AI と 医療・製薬/ヘルスケア）。先頭が代表の業界として扱われ、`industry` での絞り込みはそのいずれかに一致すれば該当します。収集対象の件数がそのまま企業数になり、同じ採用ページを二重に巡回することもありません。募集情報を登録すると、その募集の業界・業種も企業の分類へ自動的に加わります。

収集対象を作らずに既存企業のカテゴリだけを整備する場合は、`resolve_company` で企業IDを確認してから
`set_company_industries` を使います。ここでも複数カテゴリを一度に指定でき、企業の分類を収集対象の有無から独立して管理できます。

推奨操作順は次のとおりです。

1. 既存の企業は `list_unmonitored_companies` でIDを確認し、`add_collection_target` の `company_id` で、所属業界、優先度、確認間隔、1件以上の企業公式ページを登録する。新規企業だけは `company_name` を指定する（両方は指定しない）
2. `get_collection_queue` で未確認または次回確認期限を過ぎた企業を取得し、1社または少数社ずつ手順3〜5を完了してから次へ進む。全社の調査完了まで保存を待たず、未保存の調査結果が次の実行へ引き継がれると仮定しない
3. 公式ページを確認し、`find_similar_opportunities` と `find_opportunities_by_source_url` を経て募集を追加または更新する（定期再確認対象は `募集予定`、`募集中`、`通年募集` のみ）
4. 募集を新規追加する場合は `collection_target_id` を渡し、募集と確認結果 `found` を同じトランザクションで記録する。既存募集の更新はこのIDを受け付けないため、確認結果を手順5で別途記録する
5. `record_collection_check` へ実際に確認した `source_url` を必ず渡す。`found` では募集の `opportunity_id` とその募集自身の `source_url`、募集がない場合等では登録済みの有効な収集元URLと `no_opening`、`unreachable`、`needs_review` のいずれかを記録する

`found` は登録済みの個別募集の一次情報を確認した場合だけ使います。企業の採用トップページを見たことだけでは、別の一次情報URLを持つ募集を確認済みにできません。新しい募集は先に登録し、企業ページだけの確認は `opportunity_id` を省略します。受付状況や個別募集を確定できない場合は `needs_review` として記録します。`no_opening` 等の企業単位の確認記録は、既存募集の状態や公式情報確認日時を変更しません。URL不一致エラーの `expected` に合わせるだけで確認済みにせず、案内されたURLを実際に確認する必要があります。

「期限・実施終了日が過去の募集を操作しない」という指示では、`list_stale_opportunities(exclude_expired=true)` を使います。東京時間の当日より前の締め切りまたは実施終了日を持つ募集を、取得件数の制限前に除外します。当日の募集と日付が未設定の募集は対象に残り、実際の受付状況は公式ページで確認します。既定の `false` では従来どおり日付と「募集中」の矛盾を最優先で返します。企業単位の収集キューは、新しい募集の発見のために継続して利用します。

収集対象の更新は部分更新です。省略した項目は維持され、`selection_reason` は明示的に `null` を指定すると解除されます。`industries` だけは例外で、指定した内容で分類を全置換します（業界を追加する場合は既存の業界も併せて送ります）。収集を止める場合はデータを削除せず、`update_collection_target` で `is_active` を `false` にします。公式ページも同様に `update_collection_source` で無効化できます。すべての書き込みは `request_id` で冪等化され、監査ログに記録されます。

企業トップページしか登録されていない収集対象は、巡回しても新しい募集が現れないため `has_primary_source: false` として報告されます。`list_collection_targets` に `source_gap=true` を渡すとその対象だけを取り出せ、`missing_source_types` が未登録の公式ページ種別（`recruit`、`internship`、`event`、`news`）を示します。確認中に採用ページを見つけた場合は、`record_collection_check` の `discovered_sources` へ渡すと確認結果の記録と同時に情報源として追加されます。

同ツールの `check_statuses` は現在の確認状況でOR絞り込みを行います。値は `unreviewed`（未確認）、`found`（募集あり）、`no_active_opportunity`（募集なし）、`source_unavailable`（情報源を確認できない）、`needs_review`（要確認）です。`due_only` と併用すると、選んだ確認状況のうち次回確認期限を過ぎた対象だけを取得できます。

募集の少ない企業を優先する `list_undercovered_companies` も、未確認または次回確認期限を過ぎた企業だけを返します。`unreachable`・`needs_review` が続く企業の間隔は、設定間隔から2倍・4倍と延び、90日または元の設定間隔の大きい方が上限です。`found`・`no_opening` を記録すると通常間隔へ戻ります。確認不能が続いても自動では収集対象を無効化しません。

## 内部REST API

REST APIは公開せず、Next.jsサーバーと運用コマンドだけが`X-Internal-API-Token`ヘッダーを付けて利用します。ブラウザはrelua APIへ直接接続せず、必要な公開情報だけをNext.jsの同一オリジン経由で取得します。

```text
GET /api/v1/health
GET /api/v1/masters
GET /api/v1/opportunities
GET /api/v1/opportunities/{id}
GET /api/v1/companies
GET /api/v1/companies/{public_code}
```

一覧では `q`、`status`、`industry`、`sector`、`event_type`、`event_format`、`job_category`、`graduation_year`、`degree`、`sort`、`page`、`per_page` を利用できます。複数選択する条件は同じクエリ名を繰り返します。

企業一覧は `indexable=true`（既定）で、一言説明と本文の両方が登録済みの企業だけを `page`、`per_page` 付きで返します（現在の募集件数は含まれますが、条件にはしません）。サイトマップがこの一覧を使うため、企業ページのindex可否と収録範囲が食い違いません。企業詳細は8文字の公開コードで取得し、現在の募集と過去の募集を分けて返します。

## ローカル保存と共有

募集カードまたは詳細画面の「保存」から、募集情報IDだけをブラウザの `localStorage` に保存します。保存・解除時にIDをサーバーへ送信せず、個人識別情報とも紐付けません。

- `/saved`: ブックマーク、最近見た募集、QR移行、共有URL、JSON・CSVバックアップ
- `/import#c=...`: 別端末の保存データを確認後にマージ
- `/import`: 受け取った引き継ぎリンクを貼り付けて、内容確認画面を開く
- `/list#l=...`: ログイン不要の共有リスト

引き継ぎリンクと共有リンクは、募集情報のUUIDではなく8文字の公開コード（`public_code`）を並べて表現します。固定長のため区切り文字を必要とせず、2,000バイトのリンクにおよそ240件が収まります。以前のUUID形式（`#b=`、`#jobs=`）のリンクも引き続き読み込めます。

QRコードはブラウザ内で生成します。URLフラグメントはサーバーへ送信されず、インポート時は存在する募集IDだけを既存データへ追加します。

これはリアルタイム同期ではなく、その時点の保存内容を別端末へマージする「引き継ぎ」です。引き継ぎ前には新規・保存済み・終了済みの件数と追加対象を確認できます。URLやQRコードの安定動作範囲を超える場合は、JSONバックアップを利用します。

## 運用

運営者は毎日 `list_stale_opportunities` を確認してください。定期再確認対象は「募集予定」「募集中」「通年募集」に限られ、東京基準で `deadline < today` または `event_end_date < today` なのに募集状況が「募集中」の募集を最優先で返します。締切延長や追加募集の可能性があるため、Reluaはこの矛盾を自動で「締切」に変更しません。公式ページを確認し、変更がなければ `verify_opportunity`、変更があれば適切な更新ツールを実行してください。すでに「締切」などの終了状態になった募集は、この定期キューには戻りません。

矛盾が残っていても `verify_opportunity` または個別募集の `found` を記録すると、同じ矛盾は `days`（既定7日）経過まで要確認キューから外れます。募集状況・締め切り・実施終了日・一次情報URL・企業を変更した場合と復元した場合は再確認対象に戻ります。本文やタグだけの編集では待機を維持します。

default branchでは [Daily Maintenance](../.github/workflows/maintenance.yml) が毎日02:15（JST）にSSH経由で次のコマンドを実行します。これはすでに論理削除した募集を、削除から30日後に完全削除します。ただし、再送防止記録が残る間は完全削除を保留し、90日経過後のアーカイブ完了を待ちます。期限超過だけで募集を論理削除することはありません。完全削除後は復元できません。収集確認履歴は残りますが、削除済み募集への参照は解除されます。

```bash
docker compose exec api python -m app.scripts.archive_history
docker compose exec api python -m app.scripts.close_expired
docker compose exec api python -m app.scripts.mcp_connections purge
```

workflowはdeployと同じ `SERVER_HOST`、`SERVER_USER`、`SERVER_SSH_KEY`、`SERVER_PORT`（任意）、`DEPLOY_PATH` Secretsを使います。導入時はActions画面から `workflow_dispatch` で手動実行し、`purged=<件数>` と `purged_authorization_codes=<件数>`、アーカイブの完了markerが記録されることを確認してください。SSH、Compose、DB接続、完了markerのいずれかに問題があればworkflowが失敗します。GitHubのActions失敗通知を有効にし、Daily Maintenanceの履歴を実行監視の正本にします。サーバー側cronを重ねて設定する必要はありません。

同じworkflowで、作成から90日より前の監査ログ・確認履歴・再送防止記録をJSONL gzipへ移します。`archived_audit=<件数> archived_checks=<件数> ...` が完了markerです。圧縮ファイルの永続化と読戻し検証に成功してからDB行を削除し、保存に失敗した行はDBに残します。履歴一覧の `retention_days=90` と件数はDB内の記録だけを対象とし、アーカイブ内の記録は一覧・集計に含みません。

保存先は `HISTORY_ARCHIVE_DIR`（既定 `/var/lib/relua/history-archive`）で、Composeの専用 `history_archive` ボリュームに無期限保存します。**DBバックアップに加えて、このボリュームをバックアップ対象に追加してください。** 既定の保存先はイメージ内で `appuser` 所有に初期化します。保存先を変更する場合は、移動先ボリュームを同じ実行ユーザーが書き込める所有権に初期化してください。テーブル名ごとのディレクトリに、ID範囲と内容ハッシュを含む `.jsonl.gz` が保存されます。古い履歴はサーバー上で `gzip -cd <ファイル>` 等を使って確認できます。アーカイブには変更前後の本文やエラー等が含まれるため、公開用ディレクトリには配置しません。

OAuthは期限切れ認可コードを日次で削除し、期限切れaccess tokenと接続終了後の古いtokenをアーカイブへ移します。有効grantの使用済みrefresh tokenは不正な再利用を検知するためDBに残し、登録済みclientと有効な接続は維持します。

OAuthで接続中のクライアントを確認し、不要になった接続を切ります。

```bash
docker compose exec api python -m app.scripts.mcp_connections list
docker compose exec api python -m app.scripts.mcp_connections revoke <grant_id>
docker compose exec api python -m app.scripts.mcp_connections purge
```

`revoke` は1回のログインで発行されたトークンをまとめて失効させ、そのクライアントを切断します。パスワードが漏れた疑いがあるときは、`MCP_OPERATOR_PASSWORD` の変更に加えて既存の接続も失効させてください。

監査記録は `audit_logs`、冪等性レコードは `idempotency_records` に保存されます。MVPでは監査ログ閲覧画面と自動ロールバックを実装していません。

## 開発時の検証

```bash
cd backend
pip install -r requirements-dev.txt
DATABASE_URL=sqlite:// pytest
ruff check .

cd ../frontend
npm ci
npm run lint
npm run typecheck
npm test
# next build がこの値を静的ページへ焼き込むため、ビルドには公開originの指定が必要です
NEXT_PUBLIC_SITE_URL=http://localhost:3100 npm run build

cd ..
python3 scripts/check_doc_paths.py
python3 scripts/check_env_documentation.py
```

Dockerを含む一括起動は `make up`、ログ確認は `make logs`、停止は `make down` です。

## 本番公開前の設定

- `.env` のDBパスワードを本番固有値へ変更する
- `API_INTERNAL_TOKEN`と`MCP_API_TOKEN`に、それぞれ異なる十分に長いランダム値を設定する
- `ENVIRONMENT`に`development`か`production`のいずれかを設定する（未設定・綴り違い・`staging`のような未知の値は起動失敗になる。`development`を明示したときだけ開発用の既定シークレットが許される）
- `API_INTERNAL_TOKEN`・`MCP_API_TOKEN`・`NEXT_PUBLIC_SITE_URL`、およびOAuth利用時の`MCP_OPERATOR_PASSWORD`は**未設定だとcomposeが起動しない**（`${VAR:?}`形式）。既定値へ縮退して公開済みの値で動き続けることはない
- `NEXT_PUBLIC_SITE_URL`をcanonicalのapex origin（本番は`https://relua.net`、末尾pathなし）にする
- PostgreSQLとRedisの公開ポートを追加しない
- FastAPIとNext.jsの前段でTLS、CDN、リクエストサイズ制限を設定する
- `relua.conf`をNginxへ反映して`nginx -t`後にreloadし、通常URLは`www`とHTTPから同じpath/queryを保ったapex HTTPSへ308になることを確認する。旧UUID詳細はNextへ渡し、queryを除去して公開コード詳細へ1回の308で到達することを確認する
- SEO用の一覧・詳細データは最後の正常取得から最大1時間だけ再利用する。1時間を超えたキャッシュは返さず最新データの取得を待つため、長く訪問のないURLの初回応答はAPI応答時間ぶん遅くなる。API障害時は200＋`noindex`やErrorStateへ縮退せず5xxにする。`/sitemap.xml`も募集APIまたはmaster取得の部分失敗時は503（`Retry-After: 300`）を返し、静的4ページへの縮退は正常な0件の場合だけ許可する。URLが45,000件を超えると`/sitemap.xml`は自動的にサイトマップインデックスになり、実体は`/sitemaps/1.xml`以降で配信する（`robots.txt`の参照先は変わらない）
- カテゴリのSEO対象は`frontend/lib/seo.ts`の固定allowlistで管理する。新しいカテゴリや卒年を追加した場合は、正常なデータとページ内容を確認してallowlistを明示的に更新し、サイトマップ件数と代表URLを確認する
- OAuthを使わない場合は、MCP接続にSSHポートフォワードまたは運営者専用VPNを使用する
- OAuthを使う場合は、`MCP_PUBLIC_URL`をhttpsの実ホスト名にし、`MCP_OPERATOR_PASSWORD`を推測できない値にする（開発用の値のままではAPIが起動しない）
- OAuthを使う場合は、リバースプロキシで `/mcp`、`/oauth`、`/.well-known` だけを公開し、`/api/v1` は公開しない
- 実在企業10社分をChatGPT・Claudeの両方から登録し、運用上の受入確認を行う
