# 開発ルール

- 日本語で記述・回答する。
- TypeScriptで実装する。GitHub ActionsのJavaScript Actionは`node24`で実行し、開発・CI・Dev ContainerはeMudhra中間CAを拒否するNode.js 26.12.1以上、27未満を使う。実行時はNode.js標準機能だけを使い、外部パッケージへの依存を追加しない。開発用のTypeScript・型定義はnpmで管理し、`package-lock.json`をコミットする。
- コンパイル済みの`dist/index.js`をコミットする。Action内で依存のインストールやビルド、Pythonのセットアップを行わず、呼び出し元のPATHを変更しない。
- ローカルの Dev Container では、プロジェクトのコマンドを `devcontainer exec --workspace-folder . <command>` で実行する。Cursor Cloud Agent では Dev Container を使わず、Node.js 26.12.1以上、27未満の環境で同じnpmコマンドを直接実行する。Git操作はホストで行う。
- 提出前に `npm ci`、`npm run build`、`npm test`、`npm run check`、`git diff --check` を確認する。CIでは再ビルドによって`dist`に差分が出ないことも確認する。
- スキップルールは利用側workflowの`with`に、1行に1つ指定する。設定ファイルやTOML・YAMLの独自パーサは追加しない。
- 判定できない場合にチェックを省略しない。入力不備やGitの失敗を `run_checks=false` に変換しない。
- 特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- リリースはCIが成功したコミットにタグを付ける。利用側は40桁のコミットSHAに固定する。
