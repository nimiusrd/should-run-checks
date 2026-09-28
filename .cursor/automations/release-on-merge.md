# マージ後のリリース

このファイルは Cursor Automation のプロンプトです。

- トリガーは Pull request merged
- 対象はこのリポジトリ
- Pull request を作成するツールは無効にする

---

main へマージされた pull request のリリースを行う。コードは変更しない。Pull request は開かない。タグと GitHub Release は `create_release.py` だけが作る。`git tag` と `gh release create` は実行しない。

1. マージ先がデフォルトブランチであることを確認する。違う場合は何も作らず終了する。
2. マージコミットの40桁 SHA を確定する。短い SHA は使わない。
3. その SHA に対する名前 `CI` のワークフローが、デフォルトブランチへの push として成功するまで待つ。失敗した、または結果を確認できない場合はタグを作らず終了する。成功した実行の ID を控える。
4. リポジトリルートで次を実行する。`--dry-run` は付けない。

```bash
export GITHUB_REPOSITORY="<owner>/<name>"
export RELEASE_SHA="<マージコミットの40桁SHA>"
export RELEASE_EVENT=push
export RELEASE_BRANCH="<デフォルトブランチ名>"
export RELEASE_CI_RUN_ID="<成功したCIの実行ID>"
python3 create_release.py
```

`GITHUB_REPOSITORY` はこのリポジトリの `owner/name` にする。`RELEASE_EVENT` は `push` にする。信頼する CI は、マージコミットがデフォルトブランチへ push された実行である。

5. 終了コードが 0 で、出力が「リリースを作成しました」または「リリースを省略します」なら完了する。それ以外はタグを作らず終了する。
6. 作成したリリースの URL を結果として残す。固定参照は出力に含まれる40桁のコミット SHA である。
