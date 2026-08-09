/**
 * ESLint 扁平配置（ESLint 9+/10，审查 P2-2 工程化三件套）
 *
 * 覆盖：
 * - JS 推荐规则（@eslint/js）
 * - TypeScript 推荐规则（typescript-eslint）
 * - React Hooks 规则（exhaustive-deps 等）
 *
 * 运行：npm run lint（CI 同步执行）
 */

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // 组件外使用的通用工具模块无需显式 React import（react-jsx runtime）
      'react-refresh/only-export-components': 'off',
      // eslint-plugin-react-hooks 7.x 新增的 React Compiler 时代规则对
      // 「effect 内异步加载数据 → setState」「事件处理器中使用 Date.now()」等
      // 常规模式大量误报（本应用无 Compiler），按社区实践关闭；
      // 保留 rules-of-hooks / exhaustive-deps 两条核心规则
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      'react-hooks/impure': 'off',
      'react-hooks/purity': 'off',
    },
  },
);
