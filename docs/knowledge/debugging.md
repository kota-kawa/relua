# デバッグと検証の知識

この文書は、実装を変更したときに再現性を保って切り分けるための手順です。現在の仕様そのものは [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) とコードを参照してください。

## 1. まず実行環境を分ける

問題を「SQLiteの単体テスト」「PostgreSQLの移行・検索」「Dockerの実行」「Next.jsのbuild/runtime」のどれとして再現しているかを明示します。

Backendの実行環境は Python 3.12 が正本です（`backend/Dockerfile`、CI、依存コード）。Python 3.10 でテストを起動すると、OAuth実装が使う `datetime.UTC` を import できず、テスト本体へ到達する前に collection error になります。ローカルでは Python 3.12 の仮想環境を選び、例えば `backend/.venv/bin/pytest` と `backend/.venv/bin/ruff` を使います。

### Backendの通常確認

```bash
cd backend
DATABASE_URL=sqlite:// pytest
ruff check .
```

テストは `backend/tests/conftest.py` が SQLite の一時DBを作り、ORM metadata と固定値を直接投入します。これはドメインロジックを速く確認する方法であり、AlembicのupgradeやPostgreSQL拡張の確認ではありません。

### PostgreSQL固有の確認

次を確認する場合は CI の PostgreSQL ジョブ、または Compose の `db` を使います。

- Alembicを空DBへ `upgrade head` できるか。
- `pg_trgm` extension と GIN index が作られるか。
- 関連度検索・タイプミス検索の本番経路が動くか。

関連する正本は `backend/alembic/versions/20260814_0009_add_relevance_search.py`、`20260820_0013_add_company_identity_tools.py`、`backend/tests/test_pg_trgm_migration.py`、CIです。SQLiteで検索結果が完全一致しないことだけでは、本番の回帰とは判断しません。

### Frontendの確認

```bash
cd frontend
npm ci
npm test
npm run lint
npm run build
```

`frontend/lib/api.ts` は `server-only` です。Node側の `API_INTERNAL_URL` と `API_INTERNAL_TOKEN` が必要なコードをブラウザテストから直接呼ばないでください。localStorage、URLフラグメント、整形関数は Vitest の対象です。

## 2. 401 / 接続拒否

### RESTが401になる場合

確認順は次のとおりです。

1. URLが Next.js から到達できる `API_INTERNAL_URL` か。
2. FastAPIへ `X-Internal-API-Token` が付いているか。
3. Compose、`.env`、Next build時の値が同じ token か。
4. `/api/v1` を外部ブラウザから直接叩いていないか。公開境界では意図的に内部専用である。

実装は `backend/app/main.py` の middleware と `frontend/lib/api.ts` の `apiFetch` を対にして読むと早いです。

### MCPが401になる場合

- 固定接続は `Authorization: Bearer <MCP_API_TOKEN>` を使う。
- OAuth有効時は、最初の401の `WWW-Authenticate` にある resource metadata から discovery する。
- OAuthの issuer/resource は `MCP_PUBLIC_URL` から生成されるため、プロキシ越しの公開URLとローカルURLを混ぜない。
- `MCP_PUBLIC_URL` を本番で使う場合は HTTPS が必要で、`FORWARDED_ALLOW_IPS` は実際のプロキシIPに合わせる。

認証を変えた場合は `backend/tests/test_oauth.py` と `test_oauth_endpoints.py` の両方を確認します。サービス関数だけのテストでは、discovery、PKCE、callback検証、MCP middleware を取りこぼします。

## 3. MCPのリダイレクト・ストリーミング

MCPの公開エンドポイントは `/mcp` と `/mcp/` を同じ意味として扱うだけでなく、クライアントが認証付きPOSTをリダイレクト先へ再送しないことを前提に、正確な `POST /mcp` を FastAPIが処理します。

プロキシ越しに接続が途中で止まる場合は、次を確認します。

- `relua.conf` の `/mcp` と `/mcp/` が `proxy_buffering off`、十分な read/send timeout になっているか。
- FastAPIの `mcp_http_app()` を `/mcp` に直接登録しているか。
- `Host`、`X-Forwarded-Proto`、`MCP_PUBLIC_URL` の組み合わせが一致しているか。
- 認証付き初期化と匿名読み取り／認証付き書き込みのテストを分けて失敗箇所を特定できているか。

## 4. 検索・重複・書き込みの切り分け

### 検索結果が想定と違う

1. `deleted_at` が設定された論理削除行を期待していないか。
2. 東京時間の日付フィルタ、status、industry/sector の固定値を確認する。
3. `q` の有無で既定 sort が relevance/deadline に変わることを確認する。
4. PostgreSQLでは `pg_trgm`、SQLiteでは部分一致近似であることを確認する。
5. MCP cursor は最初の検索と同じ条件を要求する。条件を変えた cursor は無効になる。

関連コードは `backend/app/services/opportunities.py` の `search_opportunities`、`_search_signature`、`_decode_search_cursor` です。

### 企業が自動で同一視されない／されすぎる

正式名の正規化は表記ゆれを縮めるだけです。別スクリプトの略称などは `resolve_company` で候補を確認し、公式情報で同一企業だと判断した後に alias を明示登録します。部分一致・trigram の候補が出たこと自体は統合の根拠ではありません。

### 重複・再試行エラー

- 同じ操作の通信再試行は同じ `request_id` を使う。payload、operation、対象が同じなら保存済み結果が返る。
- 検証内容を直した再試行は新しい `request_id` を使う。
- 同名イベントの重複は `allow_duplicate` がない限り拒否される。
- 同じ一次情報URLは、正規化後に警告になるが、複数募集を一律に拒否する条件ではない。
- patch/delete の stale error は `expected_updated_at` の不一致。先に最新を取得し、差分確認からやり直す。

`backend/tests/test_mcp_tools.py` はこれらの境界を直接検証するため、MCPのpayloadを変更したときの回帰確認に使います。

## 5. マイグレーションで起きやすい問題

- 新規DBは最初の migration が live ORM metadata を作るため、後続 migration が追加するテーブル・列をすでに持つ場合がある。後続 migration が「存在するならスキップ」する理由を壊さない。
- 既存DBは migration の順番に依存する。`models.py` だけを変更して起動時に自動反映されるとは考えない。
- `company_industries` への移行は、旧 `collection_targets` の複数行を1社1対象へ統合するデータ移行である。単なる列追加として扱わない。
- PostgreSQL専用の extension/index は SQLite テストで見えないため、CIの migration と `test_pg_trgm_migration.py` を実行する。

スキーマ変更の最低チェックは、空のSQLiteテスト、空のPostgreSQLへの `alembic upgrade head`、既存データを含むupgrade、対象サービスの回帰テストです。

## 6. Next.jsのbuild/runtime差異

- `NEXT_PUBLIC_SITE_URL` は公開URL生成、sitemap、MCPが返す詳細URLに影響し、Docker build時にも渡される。
- `API_INTERNAL_URL` は server-only の実行先で、ブラウザ用のURLではない。
- `.env.example`、`docker-compose.yml`、`frontend/Dockerfile`、`backend/app/config.py` の同名・類似名を突き合わせる。
- buildは通るが実行時だけAPI取得に失敗する場合、build argではなく runner の `API_INTERNAL_URL` / `API_INTERNAL_TOKEN` が欠けていないか確認する。

## 7. 画面遷移時のスクロール

一覧の絞り込み・表示切替・ページ送りは同じ画面のURLだけを変えるため、遷移後にどこへスクロールするかがApp Routerの実装依存になります。挙動がおかしいときは次を順に確認します。

- スクロールイベントの発生回数を数える。1回なら即時移動、数十回ならアニメーションが走っている。
- `html { scroll-behavior: smooth }` を置くと、App Routerは `<html data-scroll-behavior="smooth">` が無いかぎり遷移中にそれを止められない（devのconsoleに警告が出る）。差し替え中の内容の上を長距離スクロールするので、document のスクローラーは `auto` のままにする。この指定はbrowserのback/forward位置復元も遅延アニメーション化する。
- ハッシュの飛び先が `position: sticky` / `fixed` だと、routerはその要素を読み飛ばして次の兄弟要素へ落ちる。sticky barそのものにidを付けると、結果セクションの先頭がbarの裏に潜る。飛び先はflow内に置いた高さ0の要素にする。
- URLに残ったハッシュは、そのhistory entryへ戻るたび再適用され、読み手が実際にいたスクロール位置の復元を上書きする。一度きりの移動はクリック時に `scrollIntoView` し、リンクは `scroll={false}` にしてURLにハッシュを残さない。
- 現在はroot/detailに `loading.tsx` を置いていないため、ハッシュの飛び先は実ページのDOMに対して解決される。placeholderを追加する場合は、同じidと高さを持たせたうえで、404／308のHTTP statusを壊さないか確認する。

## 8. 遷移中に何が表示されるか

「押しても反応がない」「一瞬別の画面が挟まる」を切り分けるときは、`RouteProgress`の表示と実HTTP statusを確認します。現在はroot/detailに `loading.tsx` を置かず、routerが現在のDOMを保持したまま応答を待つ構成です。dev serverはHMRのwebsocketが張れないとリンクがfull reloadに落ちることがあり、遷移の観察には向きません。`npm run build && npx next start` で確認します。

- 同一ルート内の遷移（`/?view=list` など）は、新しい結果が揃うまで今のDOMを保持し、`RouteProgress`と押した側のpending状態を表示する。`window.__probe = 1` を置いてから遷移し、遷移後も残っていればclient遷移、消えていればfull reloadである。
- 別ルートへの遷移でも現在の画面を保持する。旧UUIDは308、存在しない詳細は404になり、placeholderの200に置き換わらないことを`curl -I`で確認する。
- Playwrightで遅い遷移を再現するときは、prefetchまで遅らせないこと。`next-router-prefetch` ヘッダのあるリクエストは素通しし、それ以外の `_rsc=` だけ遅らせる。両方遅らせるとクリックがprefetch待ちになり、遷移そのものが始まらない。
- 登場アニメーションが再生されないときは、要素が作り直されているかを見る。keyが同じなら React はDOMを再利用し、CSS animationは再実行されない。
- `prefers-reduced-motion: reduce` の一括リセットは `animation-duration` しか縮めない。`animation-delay` と `animation-fill-mode` は残るので、`opacity: 0` から始まる登場は明示的に `animation: none` で止める。止め忘れると内容が見えないまま残りうる。

## 9. スクローラーを増やしたときに出る余白

`overflow: auto` を新しく付けた要素に、中身が無いのにスクロール量が生まれることがあります。`scrollHeight - clientHeight` が実際の最後の子要素の位置と合わないときは、絶対配置の子孫を疑います。

- `position: absolute` の要素を切り取れるのは、その要素の包含ブロック（`position` が `static` 以外の最も近い祖先）から先の `overflow` だけ。あいだに `overflow: hidden` の祖先があっても、そこが包含ブロックでなければ素通りする。
- 視覚的に隠したcheckbox（`position: absolute; opacity: 0`）を折り畳み領域の中に置くと、これが起きる。折り畳みは高さ0でも、checkboxは元の位置に居残り、包含ブロックである外側のスクローラーの高さに算入される。
- 直し方は、行そのものに `position: relative` を付けて包含ブロックを行に閉じること。スクローラー側で `overflow: hidden` を足しても、包含ブロックが変わらなければ効かない。
- 確認は、スクローラー内の全要素の `getBoundingClientRect().bottom` を content box の下端と比べて、はみ出しているものを列挙するのが速い。

## 10. 知識を追記するとき

同じ問題を再び切り分ける価値がある場合だけ、原因の一般化、再現条件、確認先、回避策を追記します。作業日時、担当者、特定環境のログ、修正しただけの履歴は残しません。
