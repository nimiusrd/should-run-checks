# 開発ルール

- 日本語で記述・回答する。
- Node.js 24を使用する。プロジェクトのコマンドは `devcontainer exec --workspace-folder . <command>` で実行し、Git操作はホストで行う。
- 提出前に `npm test`、`npm run lint`、`npm run format:check` を実行する。
- YAMLパーサを含む依存は`npm run build`で`dist/`へ同梱し、配布物をコミットする。利用側はNode.js 24だけで実行でき、npm installやビルドを必要としない。
- ソースや依存を変更した場合はビルドしてからテストする。CIは再ビルドした`dist/`との差分がないことも確認する。
- 判定できない場合にチェックを省略しない。設定不備やGitの失敗を `run_checks=false` に変換しない。
- 設定は利用側のリポジトリに置く。特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- 公開するバージョンは検証済みのコミットにタグを付ける。利用側の参照は40桁のコミットSHAに固定する。
