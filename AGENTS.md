# 開発ルール

- 日本語で記述・回答する。
- Node.js 24を使用する。プロジェクトのコマンドは `devcontainer exec --workspace-folder . <command>` で実行し、Git操作はホストで行う。
- 提出前に `npm test`、`npm run lint`、`npm run format:check` を実行する。
- ActionはNode.js標準ライブラリだけで実行できる状態を維持する。利用側でnpm installやビルドを必要としない。
- 判定できない場合にチェックを省略しない。設定不備やGitの失敗を `run_checks=false` に変換しない。
- 設定は利用側のリポジトリに置く。特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- 公開するバージョンは検証済みのコミットにタグを付ける。利用側の参照は40桁のコミットSHAに固定する。
