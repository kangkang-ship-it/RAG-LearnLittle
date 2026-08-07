"""
PPT 渲染引擎（设计方案 §5）

抽象接口 + PythonPptxRenderer 实现（v1 默认）：
- 16:9 版式（13.333 × 7.5 英寸）
- 封面 / 目录 / 章节 / 内容 / 总结 五类固定版式
- 每页写入演讲者备注（讲解场景刚需）
- 风格预设（business / academic / minimal）来自 config/ppt.yaml themes
- 内容页要点超出单页上限自动分页
- Markdown 轻量清洗（去重符号、提取行首要点），不解析富文本

用户模板（§5.6）：template_path 传入时走模板分支，v1 有限支持
（Phase 1.5 spike 后实现母版/版式复用 + {{key}} 替换）；无法打开/解析
失败 → 抛错由调用方降级默认版式（三档兜底第 2 档）。

Phase 3 可选实现：AsposeCloudRenderer（模板渲染模式完整支持）。
"""
import copy
import io
import re
from datetime import datetime
from typing import List, Optional, Protocol

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.core.logger_handler import logger
from app.schemas.ppt import PPTOutline, PPTSlide

# 正文字体（打开时本地渲染，无字体问题）
FONT_NAME = "微软雅黑"
CODE_FONT_NAME = "Consolas"

# 16:9 页面尺寸（英寸）
SLIDE_W, SLIDE_H = 13.333, 7.5

# 单页内容要点上限（超出自动分页）
MAX_BULLETS_PER_CONTENT = 6
# 代码块最大行数（超出折叠）
MAX_CODE_LINES = 12


def _clean_markdown(text: str) -> str:
    """轻量清洗 Markdown 语法（§5.3）：去重符号、提取行首要点，不解析富文本"""
    t = (text or "").strip()
    if not t:
        return ""
    # 行首符号（# 标题 / * - 列表 / 数字列表）
    t = re.sub(r"^(#{1,6}\s*|\*\s*|-\s*|\d+[.、]\s*)", "", t)
    # 行内标记与链接
    t = re.sub(r"[*_`#~]", "", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    return t[:200]


class PPTRenderer(Protocol):
    """渲染引擎抽象接口（§5.2，Phase 3 AsposeCloudRenderer 同签名）"""

    def render(
        self, outline: PPTOutline, theme: str,
        template_path: Optional[str] = None,
    ) -> bytes: ...


class PythonPptxRenderer:
    """本地 python-pptx 渲染（v1 默认引擎）"""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._themes = self.config.get("themes", {})

    # ========== 入口 ==========

    def render(
        self, outline: PPTOutline, theme: str = "business",
        template_path: Optional[str] = None,
    ) -> bytes:
        """
        渲染 PPT 大纲为 .pptx 字节流（纯同步，调用方必须放入线程池，§5.5）

        Args:
            outline: 结构化大纲（§4.4）
            theme: 风格预设（business / academic / minimal）
            template_path: 用户模板路径（§5.6）；None 或渲染失败 → 默认版式

        Returns:
            .pptx 文件字节流
        """
        # 用户模板（§5.6）：模板无法打开/解析失败 → 降级默认版式（三档兜底第 2 档）
        if template_path:
            try:
                return self._render_with_template(template_path, outline, theme)
            except NotImplementedError:
                # Phase 1 模板能力未实现（Phase 1.5 spike 后补充）→ 降级
                logger.warning("用户模板渲染能力未就绪（Phase 1.5），降级默认版式")
            except Exception as e:
                logger.warning(f"用户模板渲染失败，降级默认版式: {e}")
        return self._render_default(outline, theme)

    def _render_with_template(
        self, template_path: str, outline: PPTOutline, theme: str
    ) -> bytes:
        """v1 模板有限支持（§5.6，Phase 1.5 已实施并通过 spike 验证）。

        机制：
        - 模板幻灯片按**名称**匹配版式类型：cover / agenda / section / content / summary
          （用户给模板幻灯片命名，如 "cover"）；未命名/缺失的类型 → 该页退回默认版式
        - 匹配到 → 复制该页（保留母版/版式/形状样式）+ {{key}} 占位符替换：
          标量 {{title}}/{{subtitle}}/{{date}} 行内替换（保留首个 run 格式）；
          列表 {{bullets}}/{{items}}/{{code}} 按项复制段落（继承段落格式）
        - 输出保持模板页面尺寸（不强制 16:9，尊重用户模板）
        - 模板中无任何命名版式页 → 抛 ValueError，由 render() 降级默认版式（三档兜底第 2 档）
        """
        src = Presentation(template_path)
        patterns: dict = {}
        for slide in src.slides:
            name = (slide._element.cSld.get("name") or "").strip().lower()
            if name in ("cover", "agenda", "section", "content", "summary"):
                patterns[name] = slide
        if not patterns:
            raise ValueError("模板中未找到命名版式页（cover/agenda/section/content/summary）")

        out = Presentation()
        out.slide_width = src.slide_width    # 保持模板尺寸
        out.slide_height = src.slide_height
        colors = self._theme_colors(theme)
        blank = out.slide_layouts[6]

        for s in self._expanded_slides(outline):
            pattern = patterns.get(s.type)
            if pattern is None:
                # 该页类型模板缺失 → 退回默认版式（三档兜底第 3 档）
                logger.debug(f"模板缺失 {s.type} 版式页，该页退回默认版式")
                self._render_slide(out, blank, s, colors, outline)
                continue
            slide = self._copy_slide(out, pattern)
            self._fill_placeholders(slide, self._outline_slide_mapping(s))
            if s.notes:
                slide.notes_slide.notes_text_frame.text = s.notes

        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()

    # ========== 模板渲染工具 ==========

    @staticmethod
    def _copy_slide(prs, src_slide):
        """复制模板幻灯片到目标演示文稿。

        使用目标自身的 blank 版式（复用源演示文稿的版式会导致
        layout/theme 文件重复名冲突）；形状 XML 自带样式，母版/主题色
        继承为 v1 能力边界（§5.6）。
        """
        new_slide = prs.slides.add_slide(prs.slide_layouts[6])
        # 删除新页自带的版式占位符（避免与复制的形状叠加）
        for shape in list(new_slide.shapes):
            shape._element.getparent().remove(shape._element)
        for shape in src_slide.shapes:
            new_slide.shapes._spTree.append(copy.deepcopy(shape._element))
        return new_slide

    @staticmethod
    def _outline_slide_mapping(s: PPTSlide) -> dict:
        """大纲页 → 占位符映射（标量/列表分开，供 _fill_placeholders 使用）"""
        mapping: dict = {"title": _clean_markdown(s.title)}
        if s.subtitle:
            mapping["subtitle"] = _clean_markdown(s.subtitle)
        mapping["date"] = datetime.now().strftime("%Y-%m-%d")
        if s.bullets:
            mapping["bullets"] = [_clean_markdown(b) for b in s.bullets]
        if s.items:
            mapping["items"] = [_clean_markdown(i) for i in s.items]
        if s.code:
            mapping["code"] = s.code
        return mapping

    def _fill_placeholders(self, slide, mapping: dict) -> None:
        """{{key}} 占位符替换（§5.6）：
        - 段落文本恰为 {{bullets}}/{{items}}/{{code}} → 列表展开（按项复制段落，继承格式）
        - 其余含 {{标量}} 的文本 → 行内替换（保留首个 run 格式，清空多余 run）
        """
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in list(shape.text_frame.paragraphs):
                full = "".join(r.text for r in para.runs)
                if "{{" not in full:
                    continue
                stripped = full.strip()

                # ① 列表/代码占位符：整段展开（bullets/items 为 list，code 为 str 按行展开）
                list_key = None
                for key in ("bullets", "items", "code"):
                    if stripped == "{{" + key + "}}":
                        list_key = key
                        break
                if list_key:
                    values = mapping.get(list_key)
                    if isinstance(values, list) and values:
                        self._expand_paragraph(para, values)
                    elif isinstance(values, str) and values:
                        self._expand_paragraph(para, values.splitlines())
                    continue

                # ② 标量行内替换（如 "标题：{{title}}"；注意传 para._p 而非 para）
                for key, value in mapping.items():
                    if isinstance(value, (list, dict)):
                        continue
                    ph = "{{" + key + "}}"
                    if ph in full:
                        self._set_para_text(para._p, full.replace(ph, str(value)))
                        break

    @staticmethod
    def _expand_paragraph(para, values: List[str]) -> None:
        """把占位符段落展开为多个段落（每项一段，继承模板段落/首个 run 格式）"""
        p_el = para._p
        parent = p_el.getparent()
        idx = parent.index(p_el)
        PythonPptxRenderer._set_para_text(p_el, values[0])
        for i, value in enumerate(values[1:], start=1):
            new_p = copy.deepcopy(p_el)
            PythonPptxRenderer._set_para_text(new_p, value)
            parent.insert(idx + i, new_p)

    @staticmethod
    def _set_para_text(p_el, text: str) -> None:
        """设置段落文本：保留首个 run 的格式（rPr），删除多余 run"""
        runs = p_el.findall(qn("a:r"))
        if not runs:
            return
        t = runs[0].find(qn("a:t"))
        if t is None:
            t = runs[0].makeelement(qn("a:t"), {})
            runs[0].append(t)
        t.text = text
        for r in runs[1:]:
            p_el.remove(r)

    # ========== 默认版式 ==========

    def _render_default(self, outline: PPTOutline, theme: str) -> bytes:
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)
        colors = self._theme_colors(theme)
        blank = prs.slide_layouts[6]  # blank 版式

        for slide in self._expanded_slides(outline):
            self._render_slide(prs, blank, slide, colors, outline)

        buffer = io.BytesIO()
        prs.save(buffer)
        return buffer.getvalue()

    def _expanded_slides(self, outline: PPTOutline) -> List[PPTSlide]:
        """内容页要点超出单页上限 → 自动分页（§5.3）"""
        for s in outline.slides:
            if s.type == "content" and s.bullets and len(s.bullets) > MAX_BULLETS_PER_CONTENT:
                for i in range(0, len(s.bullets), MAX_BULLETS_PER_CONTENT):
                    yield PPTSlide(
                        type="content", title=s.title,
                        bullets=s.bullets[i:i + MAX_BULLETS_PER_CONTENT],
                        code=s.code if i == 0 else None,
                        notes=s.notes,
                    )
            else:
                yield s

    def _theme_colors(self, theme: str) -> dict:
        """取主题色；未知主题回退 business"""
        theme = theme if theme in self._themes else "business"
        t = self._themes.get(theme, {})
        return {
            "primary": t.get("primary", "1F4E79"),
            "secondary": t.get("secondary", "2E75B6"),
            "background": t.get("background", "FFFFFF"),
            "title_size": t.get("title_font_size", 36),
            "body_size": t.get("body_font_size", 20),
        }

    # ========== 版式绘制 ==========

    def _render_slide(self, prs, blank, s: PPTSlide, colors: dict, outline: PPTOutline):
        slide = prs.slides.add_slide(blank)

        if s.type == "cover":
            # 上半部主色带 + 大标题 + 副标题 + 日期
            self._add_band(slide, 0, 0, SLIDE_W, 3.2, colors["primary"])
            self._add_textbox(slide, 0.8, 0.9, 11.7, 1.6, s.title,
                              size=44, bold=True, color="FFFFFF")
            subtitle = s.subtitle or outline.subtitle
            if subtitle:
                self._add_textbox(slide, 0.8, 2.5, 11.7, 0.6, subtitle,
                                  size=20, color="FFFFFF")
            self._add_textbox(slide, 0.8, 6.6, 11.7, 0.5,
                              datetime.now().strftime("%Y-%m-%d"),
                              size=14, color="9E9E9E")

        elif s.type == "agenda":
            self._add_textbox(slide, 0.8, 0.5, 11.7, 1.0, s.title,
                              size=32, bold=True, color=colors["primary"])
            items = s.items or [t.title for t in outline.slides if t.type == "section"]
            self._add_bullets(slide, 1.2, 1.8, 10.9, 5.0, items, size=22)

        elif s.type == "section":
            # 主色横带 + 大标题
            self._add_band(slide, 0, 2.6, SLIDE_W, 2.2, colors["primary"])
            self._add_textbox(slide, 0.8, 3.0, 11.7, 1.4, s.title,
                              size=36, bold=True, color="FFFFFF",
                              anchor=MSO_ANCHOR.MIDDLE)
            if s.subtitle:
                self._add_textbox(slide, 0.8, 4.5, 11.7, 0.6, s.subtitle,
                                  size=18, color="FFFFFF")

        elif s.type == "content":
            # 顶部辅色标题栏 + 要点 / 代码块
            self._add_band(slide, 0, 0, SLIDE_W, 0.9, colors["secondary"])
            self._add_textbox(slide, 0.6, 0.15, 12.1, 0.6, s.title,
                              size=24, bold=True, color="FFFFFF",
                              anchor=MSO_ANCHOR.MIDDLE)
            if s.code:
                self._add_code_block(slide, 0.9, 1.3, 11.5, 5.3, s.code)
            else:
                self._add_bullets(slide, 0.9, 1.4, 11.5, 5.3,
                                  s.bullets or [], size=colors["body_size"])

        elif s.type == "summary":
            self._add_textbox(slide, 0.8, 0.5, 11.7, 1.0, s.title,
                              size=32, bold=True, color=colors["primary"])
            self._add_bullets(slide, 1.2, 1.8, 10.9, 5.0,
                              s.bullets or [], size=22)

        # 每页写入演讲者备注
        if s.notes:
            slide.notes_slide.notes_text_frame.text = s.notes

    # ========== 绘制工具 ==========

    @staticmethod
    def _add_band(slide, x, y, w, h, color: str):
        """主色横带（无边框矩形）"""
        band = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        band.fill.solid()
        band.fill.fore_color.rgb = RGBColor.from_string(color)
        band.line.fill.background()

    @staticmethod
    def _add_textbox(slide, x, y, w, h, text, size=20, bold=False,
                     color="212121", align=PP_ALIGN.LEFT,
                     anchor=MSO_ANCHOR.TOP):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = _clean_markdown(text)
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = FONT_NAME
        run.font.color.rgb = RGBColor.from_string(color)

    @staticmethod
    def _add_bullets(slide, x, y, w, h, items, size=20, color="212121"):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = _clean_markdown(item)
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.name = FONT_NAME
                run.font.color.rgb = RGBColor.from_string(color)

    @staticmethod
    def _add_code_block(slide, x, y, w, h, code):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        for i, line in enumerate(code.splitlines()[:MAX_CODE_LINES]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = p.add_run()
            run.text = line
            run.font.size = Pt(14)
            run.font.name = CODE_FONT_NAME
            run.font.color.rgb = RGBColor.from_string("37474F")
