# マージ後のリリース

このファイルは Cursor Automation のプロンプトです。

- トリガーは Pull request merged
- 対象はこのリポジトリ
- Pull request を作成するツールは無効にする

---

main へマージされた pull request のバージョンを決め、そのマージコミットにタグと GitHub Release を作成する。コードは変更しない。`pyproject.toml` は書き換えない。Pull request は開かない。

1. マージ先がデフォルトブランチであることを確認する。違う場合は何も作らず終了する。
2. マージコミットの40桁 SHA を確定する。短い SHA は使わない。
3. その SHA に対する名前 `CI` のワークフローが、デフォルトブランチへの push として成功するまで待つ。失敗した、または結果を確認できない場合はタグも GitHub Release も作らず終了する。成功した実行の URL を控える。
4. その SHA に `vX.Y.Z` 形式のリリースタグが既にある場合は、新しいタグも GitHub Release も作らず終了する。マージされた pull request がない場合も終了する。
5. 次のタグ番号を決める。
   - リリースタグがなければ、`pyproject.toml` の `version` を使う。
   - その `version` が最新の `vX.Y.Z` より新しければ、その値を使う。
   - それ以外は最新タグから上げる。ラベルがなければ patch を 1 つ上げる。`release:minor` なら minor、`release:major` なら major にする。両方が付いている場合は何も作らず終了する。
   - タグ名は `v` に続けた `X.Y.Z` にする。別のコミットを指している既存タグは動かさない。
6. 手順 5 で決めたタグと GitHub Release を、手順 2 の40桁 SHA に作成する。ブランチ名は指定しない。

```bash
gh release create "vX.Y.Z" \
  --target "<マージコミットの40桁SHA>" \
  --title "vX.Y.Z — <pull requestの題名>" \
  --notes "<本文>"
```

7. 本文には変更内容を書く。次の2行を必ず入れる。`owner/name` はこのリポジトリにする。

```text
検証: <成功したCIのURL>

固定参照: `owner/name@<マージコミットの40桁SHA>`
```

8. 作成した GitHub Release の URL を結果として残す。固定参照は本文の40桁 SHA である。
