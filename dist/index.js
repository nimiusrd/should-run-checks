"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.readInputs = readInputs;
exports.shouldRunChecks = shouldRunChecks;
exports.evaluateChanges = evaluateChanges;
exports.writeResult = writeResult;
exports.run = run;
/** Node.js標準機能だけでworkflow入力とGit差分からCIの実行要否を判定する。 */
const node_child_process_1 = require("node:child_process");
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
function lines(value) {
    return (value ?? '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}
function readInputs(env) {
    if (env['INPUT_CONFIG-PATH']?.trim()) {
        throw new Error('config-pathは廃止しました。workflowのwithにルールを指定してください。');
    }
    const config = {
        skipExtensions: lines(env['INPUT_SKIP-EXTENSIONS']),
        skipDirectories: lines(env['INPUT_SKIP-DIRECTORIES']),
        alwaysRunFiles: lines(env['INPUT_ALWAYS-RUN-FILES']),
    };
    for (const extension of config.skipExtensions) {
        if (!extension.startsWith('.') || extension.length < 2 || /[/\\*?\[\]{}!\r]/.test(extension)) {
            throw new Error(`skip-extensionsはドットから始まる拡張子を指定してください: ${extension}`);
        }
    }
    for (const key of ['skipDirectories', 'alwaysRunFiles']) {
        for (const path of config[key]) {
            if (/[\\*?\[\]{}!\r]/.test(path) || path.split('/').some(part => ['', '.', '..'].includes(part))) {
                throw new Error(`${key}はglobを使わずリポジトリルートからの相対パスを指定してください: ${path}`);
            }
        }
    }
    return config;
}
function shouldRunChecks(files, config) {
    return files.some(path => {
        if (config.alwaysRunFiles.includes(path))
            return true;
        if (config.skipDirectories.some(directory => path.startsWith(`${directory}/`)))
            return false;
        return !config.skipExtensions.some(extension => path.endsWith(extension));
    });
}
function object(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        throw new Error('イベントはオブジェクトで指定してください。');
    }
    return value;
}
function evaluateChanges(workspace, eventName, value, config) {
    const event = object(value);
    let base;
    let head;
    let separator;
    if (eventName === 'pull_request') {
        const pr = object(event.pull_request);
        base = object(pr.base).sha;
        head = object(pr.head).sha;
        separator = '...';
    }
    else if (eventName === 'push') {
        base = event.before;
        head = event.after;
        if (typeof base === 'string' && /^(?:0{40}|0{64})$/.test(base)) {
            return { runChecks: true, reason: 'initial-push' };
        }
        separator = '..';
    }
    else {
        return { runChecks: true, reason: 'unsupported-event' };
    }
    for (const sha of [base, head]) {
        if (typeof sha !== 'string' || !/^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/.test(sha)) {
            throw new Error('イベントに有効なbase/headコミットSHAがありません。');
        }
    }
    // 削除とリネーム前後の両パスを含め、空白・改行のあるパスもNUL区切りで保持する。
    const diff = (0, node_child_process_1.execFileSync)('git', [
        '-C', workspace, 'diff', '--no-renames', '--name-only', '-z', `${base}${separator}${head}`, '--',
    ], { stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024 });
    // 不正なUTF-8を置換してスキップルールに誤一致させず、判定失敗として扱う。
    const files = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(diff).split('\0').filter(Boolean);
    const runChecks = shouldRunChecks(files, config);
    return {
        runChecks,
        reason: files.length === 0 ? 'no-changes' : runChecks ? 'changed-files' : 'skip-only',
        changedFileCount: files.length,
    };
}
function writeResult(result, env) {
    const output = `run_checks=${result.runChecks}\nreason=${result.reason}\n`;
    if (env.GITHUB_OUTPUT)
        (0, node_fs_1.appendFileSync)(env.GITHUB_OUTPUT, output, 'utf8');
    process.stdout.write(output);
    if (env.GITHUB_STEP_SUMMARY) {
        let summary = `## Should Run Checks\n\n- チェックを実行: ${result.runChecks}\n- 判定理由: ${result.reason}\n`;
        if (result.changedFileCount !== undefined)
            summary += `- 変更パス数: ${result.changedFileCount}\n`;
        (0, node_fs_1.appendFileSync)(env.GITHUB_STEP_SUMMARY, summary, 'utf8');
    }
}
function run(env = process.env) {
    try {
        const config = readInputs(env);
        if (!env.GITHUB_EVENT_PATH)
            throw new Error('GITHUB_EVENT_PATHがありません。');
        const event = JSON.parse((0, node_fs_1.readFileSync)(env.GITHUB_EVENT_PATH, 'utf8'));
        const result = evaluateChanges((0, node_path_1.resolve)(env.GITHUB_WORKSPACE || '.'), env.GITHUB_EVENT_NAME ?? '', event, config);
        writeResult(result, env);
        return result;
    }
    catch (error) {
        writeResult({ runChecks: true, reason: 'error' }, env);
        throw error;
    }
}
if (require.main === module) {
    try {
        run();
    }
    catch (error) {
        const message = (error instanceof Error ? error.message : String(error))
            .replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A');
        process.stderr.write(`::error::${message}\n`);
        process.exitCode = 1;
    }
}
