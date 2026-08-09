/**
 * AI 消息内容渲染：Markdown + LaTeX 数学公式（KaTeX）
 * - remarkMath 解析 $...$ 行内公式与 $$...$$ 块级公式
 * - rehypeKatex 将公式渲染为 KaTeX 排版
 * - 流式中间态（未闭合的公式/代码块）由 react-markdown 安全降级为纯文本
 *
 * 审查 ⑤：从 AIChat.tsx（1088 行巨型组件）拆出。
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';

export default function MessageContent({ content }: { content: string }) {
  return (
    <div className="md-prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
