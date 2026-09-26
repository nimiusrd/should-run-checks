import { execFileSync } from 'node:child_process';

const KEYS = ['skipExtensions', 'skipDirectories', 'alwaysRunFiles'];

export function validateConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('設定はJSONオブジェクトで指定してください。');
  }
  for (const key of Object.keys(config)) {
    if (!KEYS.includes(key)) throw new Error(`未知の設定キー: ${key}`);
  }
  for (const key of KEYS) {
    if (
      !Array.isArray(config[key]) ||
      config[key].some((value) => typeof value !== 'string' || value.length === 0)
    ) {
      throw new Error(`${key} は空でない文字列の配列で指定してください。`);
    }
  }
  for (const extension of config.skipExtensions) {
    if (!/^\.[^/*?[\]{}!]+$/.test(extension) || extension.includes('\\')) {
      throw new Error(`skipExtensionsにはドットから始まる拡張子を指定してください: ${extension}`);
    }
  }
  for (const key of ['skipDirectories', 'alwaysRunFiles']) {
    for (const path of config[key]) {
      if (
        /[*?[\]{}!]/.test(path) ||
        path.includes('\\') ||
        path.split('/').some((part) => part === '' || part === '.' || part === '..')
      ) {
        throw new Error(`${key} にはglobを使わず相対パスを指定してください: ${path}`);
      }
    }
  }
  return config;
}

export function shouldRunChecks(changedFiles, config) {
  return changedFiles.some((path) => {
    if (config.alwaysRunFiles.includes(path)) return true;
    if (config.skipDirectories.some((directory) => path.startsWith(`${directory}/`))) return false;
    return !config.skipExtensions.some((extension) => path.endsWith(extension));
  });
}

export function comparisonForEvent(eventName, event) {
  if (eventName === 'pull_request') {
    return {
      base: event.pull_request?.base?.sha,
      head: event.pull_request?.head?.sha,
      separator: '...',
    };
  }
  if (eventName === 'push') {
    if (typeof event.before === 'string' && /^0{40,64}$/.test(event.before)) {
      return { reason: 'initial-push' };
    }
    return { base: event.before, head: event.after, separator: '..' };
  }
  return { reason: 'unsupported-event' };
}

export function evaluateChanges({ workspace, eventName, event, config }) {
  validateConfig(config);
  const comparison = comparisonForEvent(eventName, event);
  if (comparison.reason) return { runChecks: true, reason: comparison.reason };
  const { base, head, separator } = comparison;
  for (const sha of [base, head]) {
    if (typeof sha !== 'string' || !/^(?:[a-f\d]{40}|[a-f\d]{64})$/i.test(sha)) {
      throw new Error('イベントに有効なbase/headコミットSHAがありません。');
    }
  }
  // リネーム元の削除も検査する。空白・改行を含むパスはNUL区切りで保持する。
  const diff = execFileSync(
    'git',
    [
      '-C',
      workspace,
      'diff',
      '--no-renames',
      '--name-only',
      '-z',
      `${base}${separator}${head}`,
      '--',
    ],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] },
  );
  const files = diff.split('\0').filter(Boolean);
  const runChecks = shouldRunChecks(files, config);
  return {
    runChecks,
    reason: files.length === 0 ? 'no-changes' : runChecks ? 'changed-files' : 'skip-only',
    changedFileCount: files.length,
  };
}
