const { unified } = require('unified');
const remarkParse = require('remark-parse');
const remarkMath = require('remark-math');
const remarkRehype = require('remark-rehype');
const rehypeKatex = require('rehype-katex');
const rehypeStringify = require('rehype-stringify');

const md = `**1. 用线速度 v：**
$$\\frac{GMm}{r^2} = \\frac{mv^2}{r} \\Rightarrow v = \\sqrt{\\frac{GM}{r}}$$

**2. 用角速度 ω：**
$$\\frac{GMm}{r^2} = m\\omega^2 r \\Rightarrow \\omega = \\sqrt{\\frac{GM}{r^3}}$$

**4. 用向心加速度 a：**
$$\\frac{GMm}{r^2} = ma \\Rightarrow a = \\frac{GM}{r^2}$$`;

unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkRehype)
  .use(rehypeKatex)
  .use(rehypeStringify)
  .process(md)
  .then((file) => {
    const html = String(file);
    const katexCount = (html.match(/class="katex"/g) || []).length;
    const errorCount = (html.match(/ParseError|katex-error/g) || []).length;
    console.log('=== 渲染结果片段 ===');
    console.log(html.slice(0, 900));
    console.log('====================');
    console.log('KaTeX 渲染的公式数量:', katexCount);
    console.log('解析错误数量:', errorCount);
    process.exit(katexCount >= 3 && errorCount === 0 ? 0 : 1);
  })
  .catch((e) => { console.error('渲染失败:', e.message); process.exit(1); });
