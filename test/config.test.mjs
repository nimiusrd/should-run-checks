import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseConfig } from '../src/config.mjs';
import { shouldRunChecks } from '../src/scope.mjs';

const expected = {
  skipExtensions: ['.md'],
  skipDirectories: ['mockups'],
  alwaysRunFiles: ['docs/api.md'],
};
const yaml = `# スキップ条件
skipExtensions:
  - .md # Markdown
skipDirectories: [mockups]
alwaysRunFiles:
  - 'docs/api.md'
`;
for (const filename of ['rules.yml', 'rules.yaml', 'RULES.YAML']) {
  test(`${filename}: コメントと配列を持つYAMLをJSONと同じルールとして読む`, () => {
    const parsed = parseConfig(yaml, filename);
    assert.deepEqual(parsed, expected);
    assert.deepEqual(parsed, parseConfig(JSON.stringify(expected), 'rules.json'));
    assert.equal(shouldRunChecks(['README.md', 'mockups/app.js'], parsed), false);
    assert.equal(shouldRunChecks(['docs/api.md'], parsed), true);
    assert.equal(shouldRunChecks(['src/app.ts'], parsed), true);
  });
}
test('YAMLの引用符内の#や:をパスの一部として扱う', () => {
  const rules = parseConfig(
    `skipExtensions: ['.md']
skipDirectories: []
alwaysRunFiles: ['docs/a#b.md', 'docs/a: b.md']`,
    'rules.yml',
  );
  assert.equal(shouldRunChecks(['docs/a#b.md'], rules), true);
  assert.equal(shouldRunChecks(['docs/a: b.md'], rules), true);
});
test('既存のJSONと拡張子なしのJSONも読み込める', () => {
  for (const filename of ['rules.json', 'rules']) {
    assert.deepEqual(parseConfig(JSON.stringify(expected), filename), expected);
  }
});
for (const [name, source] of [
  ['構文エラー', 'skipExtensions: ['],
  ['重複キー', `${yaml}\nskipExtensions: []`],
  ['空文書', ''],
  ['複数文書', `${yaml}\n---\n${yaml}`],
  ['配列でない拡張子', 'skipExtensions: .md\nskipDirectories: []\nalwaysRunFiles: []'],
  ['文字列でない値', 'skipExtensions: [false]\nskipDirectories: []\nalwaysRunFiles: []'],
  ['省略された配列', 'skipExtensions: [.md]\nskipDirectories: []\nalwaysRunFiles:'],
  ['未知のタグ', 'skipExtensions: [!unknown .md]\nskipDirectories: []\nalwaysRunFiles: []'],
]) {
  test(`${name}をスキップ判定に使用しない`, () => {
    assert.throws(() => parseConfig(source, 'rules.yml'));
  });
}
