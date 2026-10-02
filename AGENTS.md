# 開発ルール

- 日本語で記述・回答する。
- TypeScriptで実装し、ActionはNode.js 24で実行する。実行時はNode.js標準機能だけを使い、外部パッケージへの依存を追加しない。開発用のTypeScript・型定義はnpmで管理し、`package-lock.json`をコミットする。
- コンパイル済みの`dist/index.js`をコミットする。Action内で依存のインストールやビルド、Pythonのセットアップを行わず、呼び出し元のPATHを変更しない。
- ローカルの Dev Container では、プロジェクトのコマンドを `devcontainer exec --workspace-folder . <command>` で実行する。Cursor Cloud Agent では Dev Container を使わず、Node.js 24環境で同じnpmコマンドを直接実行する。Git操作はホストで行う。
- 提出前に `npm ci`、`npm run build`、`npm test`、`npm run check`、`git diff --check` を確認する。CIでは再ビルドによって`dist`に差分が出ないことも確認する。
- スキップルールは利用側workflowの`with`に、1行に1つ指定する。設定ファイルやTOML・YAMLの独自パーサは追加しない。
- 判定できない場合にチェックを省略しない。入力不備やGitの失敗を `run_checks=false` に変換しない。
- 特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- リリースは、Cursor AutomationがRELEASE.mdに従い、CIが成功したコミットにだけタグとGitHub Releaseを付ける。通常の実装作業ではタグを作らない。利用側は40桁のコミットSHAに固定する。
