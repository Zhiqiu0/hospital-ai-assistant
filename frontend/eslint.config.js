import js from '@eslint/js'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettierConfig from 'eslint-config-prettier'

export default [
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 2020, sourceType: 'module' },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      // TypeScript
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],

      // React Hooks
      ...reactHooks.configs.recommended.rules,
      // useEffect 内同步调 setState 是刻意行为（换患者清空表单等），降为 warn
      'react-hooks/set-state-in-effect': 'warn',

      // React Refresh（Vite HMR）
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // 通用
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  // 关闭所有与 Prettier 冲突的格式化规则（必须放最后）
  prettierConfig,
]
