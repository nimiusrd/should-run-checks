import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['node_modules/**', '.npm-cache/**'] },
  js.configs.recommended,
  { languageOptions: { globals: globals.node } },
];
