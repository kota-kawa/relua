# ADR-0019: 公開済みの開発用シークレットと未設定の公開オリジンで起動を止める

- Status: Accepted
- Scope: `backend/app/config.py`、`docker-compose.yml`、`frontend/lib/site.ts`、`frontend/lib/api.ts`、`frontend/proxy.ts`、`relua.conf`、レート制限のクライアント識別

## Context

`ENVIRONMENT=production` のときだけ `local-development-` で始まるシークレットを拒否していた。しかし `environment` の既定値は `development` で、`ENVIRONMENT` は `docker-compose.yml` の `environment:` ブロックに無く `.env` 経由でしか渡らなかった。同時に compose は `${MCP_API_TOKEN:-local-development-mcp-token}` の形でリポジトリに書かれた既知の値を注入していた。

つまり `.env` のキー名を1つ間違えるだけで、`relua.conf` によってインターネットに公開されている `/mcp` が、GitHubで読める文字列の Bearer トークンで全書き込みツールを受け付ける状態になり、起動は成功するため気づく手段が無かった。`API_INTERNAL_TOKEN` は `frontend/lib/api.ts` と `frontend/proxy.ts` にも同じ既定値がハードコードされており、フロント側も黙って開発用トークンで通っていた。

`NEXT_PUBLIC_SITE_URL` も同種の問題を持つ。未設定なら `http://localhost:3100` に縮退するが、この値はビルド時にインライン化されるため、build arg を渡し忘れても**ビルドもテストも通り**、canonical・OG url・JSON-LD の `@id`・`robots.txt` の `Sitemap:`・サイトマップの全 `<loc>` が localhost になってから初めて発覚する。

クライアントIPも解決できていなかった。uvicorn の `--forwarded-allow-ips=127.0.0.1` に対し、`ports: 127.0.0.1:8000:8000` 経由でコンテナから見えるピアは docker bridge ゲートウェイであり一致しない。結果 `request.client.host` は全リクエストで同一になり、攻撃者は毎分5回の誤パスワードで運営者をロックアウトできた。回避のため `FORWARDED_ALLOW_IPS=*` にすると、今度は uvicorn が `X-Forwarded-For` の先頭を無条件で信頼するため、ヘッダを変えるだけで運営者パスワードの総当たり制限を完全にバイパスできた。

## Decision

- シークレット検証を「production がopt-out」から**「development が明示的にopt-in」**へ反転する。`ENVIRONMENT` は `Literal["development", "production"]` とし、未設定・綴り違い・`staging` のような未知の値はすべて起動失敗にする。公開済みの開発用シークレットが実際に使われていれば、環境名に関わらず拒否する。
- `docker-compose.yml` から `:-local-development-*` のフォールバックを削除し `${VAR:?}` 形式にする。未設定はスタックの起動前に止まる。`ENVIRONMENT` は `environment:` ブロックに明示し、既定値を `production`（＝拒否側）に倒す。
- フロントエンドも同じ規律に従う。`siteOrigin()` と内部APIトークンの解決は、本番で値が無ければ localhost や公開済み既定値へ縮退せず例外を投げる。開発とテストでは従来どおりの既定値を使う。
- `siteOrigin()` の検査は**ビルド時にも適用する**。`next build` は `NEXT_PUBLIC_*` をバンドルへ埋め込むため、ビルドこそがこの値を決める唯一の機会である。ビルドを免除していたときは、変数なしのビルドが `/about`・`/terms`・`/policy`・`/list`・`/saved`・`/import`・`/robots.txt` を「canonical・OGP・JSON-LD がすべて localhost を指す静的ファイル」として出力し、それらは200を返し続ける一方で動的ルートだけがエラーになっていた。ビルドの失敗は数秒で回復できるが、インデックスとSNSカードに焼き付いた到達不能URLは回復できない。`NEXT_PUBLIC_SITE_URL=http://localhost:3100` の明示指定は引き続き有効なので、ローカルとCIは値を明示するだけでよい。`frontend/Dockerfile` の ARG 既定値も削除する。
- `FORWARDED_ALLOW_IPS` の既定を docker bridge のレンジ（`127.0.0.1,172.16.0.0/12`）とし、`*` を禁止する理由を `.env.example` と compose のコメントに残す。
- ログイン回数制限を、識別子の信頼度でバケットを選ぶ方式にする。解決できたアドレスには per-IP と per-client_id を適用し、**全体カウンタは使わない**。全リクエストが共有する全体カウンタは、アドレスを数十個回すだけで攻撃者が使い切れてしまい、その瞬間に運営者自身のログインも拒否されるロックアウトスイッチになるからである。分散した総当たりはパスワード強度（`config.py` が既定値を拒否する）で抑える。解決できないアドレスは per-IP バケットを持てないので、そのときだけ全体の上限で抑える。クライアント登録の制限も同じ形に揃える。
- `relua.conf` の443サーバーに `Strict-Transport-Security` を追加する。運営者パスワードを平文フォームで送る画面があるため、初回アクセスのHTTPダウングレードを残さない。

## Consequences

必須の環境変数（`API_INTERNAL_TOKEN`、`MCP_API_TOKEN`、OAuth有効時の `MCP_OPERATOR_PASSWORD`、`NEXT_PUBLIC_SITE_URL`）が揃っていないデプロイは**起動しなくなる**。これは意図した変更で、既存環境の `.env` は更新が必要である。設定漏れの現れ方が「静かな侵害」から「起動失敗」に変わる。

`ENVIRONMENT` に未知の値を入れていた環境は起動に失敗する。移行時は `development` か `production` のどちらかへ明示的に寄せる。

`npm run build` も `NEXT_PUBLIC_SITE_URL` を要求するようになる。CI とローカル検証は値を明示する必要があり、`AGENTS.md` と `README.md` の検証コマンドを更新済みである。

分散した総当たり（多数のアドレス × 多数の client_id）に対する上限は無くなる。これは意図した取捨選択で、可用性（運営者が締め出されないこと）を、単独では実効性の乏しい全体上限より優先している。パスワードは12文字以上かつ既定値が禁止されているため、1アドレスあたり毎分5回という制限の下では総当たりは成立しない。共有IP背後の正規利用者が per-client_id の上限（per-IP の4倍）に当たる可能性は残るが、通常の運用では到達しない。
