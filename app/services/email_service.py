"""
邮件发送服务

基于 aiosmtplib 的异步 SMTP 客户端，提供：
- 通用邮件发送（自动重试瞬态错误，指数退避）
- 注册/修改邮箱的 6 位数字验证码（生成、存储、校验）

验证码存储于 Redis：
- key: ``email_code:{email}``，TTL 300s（5 分钟），一次性使用
- 错误计数: ``email_code_errors:{email}``，TTL 900s（防暴力破解）
"""

import asyncio
import html as html_lib
import logging
import os
import random
import re
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import List, Optional

import aiosmtplib

logger = logging.getLogger(__name__)

# 验证码有效期（秒）
CODE_TTL = 300
# 同一邮箱验证码错误最大次数，超过后删除验证码（锁定）
MAX_CODE_ATTEMPTS = 5
# 错误计数保留时长（秒）
ERROR_COUNT_TTL = 900


class EmailService:
    """
    邮件发送服务

    Attributes:
        smtp_host: SMTP 服务器地址
        smtp_port: SMTP 端口（QQ 邮箱 587，STARTTLS）
        smtp_username: 发件邮箱
        smtp_password: 授权码（非登录密码）
        smtp_from_name: 发件人显示名称
    """

    def __init__(self, config: Optional[dict] = None):
        """
        仅从环境变量/配置字典读取 SMTP 配置，不建立网络连接。
        真正的 SMTP 连接在 send_email 调用时才通过 aiosmtplib 建立。
        """
        config = config or {}
        self.smtp_host = config.get("SMTP_HOST") or os.getenv("SMTP_HOST", "")
        self.smtp_port = int(config.get("SMTP_PORT") or os.getenv("SMTP_PORT", "587"))
        self.smtp_username = config.get("SMTP_USERNAME") or os.getenv("SMTP_USERNAME", "")
        self.smtp_password = config.get("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")
        self.smtp_from_name = config.get("SMTP_FROM_NAME") or os.getenv("SMTP_FROM_NAME", "云尚")
        self.template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "templates" / "email" / "verification_code.html"
        )

    @property
    def available(self) -> bool:
        """SMTP 配置是否完整（未配置时邮件功能不可用）"""
        return bool(self.smtp_host and self.smtp_username and self.smtp_password)

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        retries: int = 2,
        backoff: float = 2.0,
    ) -> None:
        """
        发送邮件，自动重试瞬态错误（指数退避 2s → 4s）。

        Args:
            to: 收件人邮箱
            subject: 邮件主题
            body: 邮件正文（纯文本 / Markdown）
            html: 可选 HTML 正文（与 body 同时存在时作为 multipart/alternative）
            attachments: 可选附件列表，每项为 {"filename": str, "data": bytes, "mime": str}
            retries: 最大重试次数（不含首次尝试）
            backoff: 首次重试等待秒数，按 2^n 指数递增

        Raises:
            aiosmtplib.SMTPAuthenticationError: 认证失败（配置问题，不重试）
            aiosmtplib.SMTPException: 重试耗尽后抛出最后一次连接/超时错误
        """
        if not self.available:
            raise RuntimeError("SMTP 未配置，无法发送邮件")

        # ⚠️ MIME 结构必须标准：
        # - 无附件：multipart/alternative（正文纯文本 + HTML 互为替代）
        # - 有附件：multipart/mixed 外层，内含 multipart/alternative 正文层 + 附件层。
        #   附件不能挂在 alternative 内（部分邮件服务器会拒收或丢弃附件）。
        has_attachments = bool(attachments)

        if has_attachments:
            msg = MIMEMultipart("mixed")
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain", "utf-8"))
            if html:
                alt.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(alt)
        else:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain", "utf-8"))
            if html:
                msg.attach(MIMEText(html, "html", "utf-8"))

        # ⚠️ 显示名/主题可能包含中文等非 ASCII 字符，必须显式 RFC2047 编码，
        # 否则 QQ 等邮件服务器会拒绝（550 "From header is missing or invalid"）
        msg["From"] = formataddr((self.smtp_from_name, self.smtp_username))
        msg["To"] = to
        msg["Subject"] = str(Header(subject, "utf-8"))

        # 附件挂在 mixed 外层（文件名含中文时用 RFC2231 编码）
        for att in attachments or []:
            part = MIMEApplication(att["data"], _subtype=att.get("mime", "application/octet-stream").split("/")[-1])
            part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", att["filename"]))
            msg.attach(part)

        last_error = None
        for attempt in range(retries + 1):
            try:
                async with aiosmtplib.SMTP(
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    timeout=10,
                    use_tls=False,
                    start_tls=True,
                ) as smtp:
                    if self.smtp_username:
                        await smtp.login(self.smtp_username, self.smtp_password)
                    await smtp.send_message(msg)
                logger.info(f"邮件发送成功: to={to}, subject={subject}")
                return
            except (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPTimeoutError) as e:
                last_error = e
                if attempt < retries:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        f"邮件发送瞬态失败（第 {attempt + 1} 次）: to={to}, error={e}，"
                        f"{wait}s 后重试"
                    )
                    await asyncio.sleep(wait)
            except aiosmtplib.SMTPAuthenticationError:
                logger.error(f"SMTP 认证失败（请检查授权码配置）: {self.smtp_username}")
                raise
        logger.error(f"邮件发送失败（重试耗尽）: to={to}, error={last_error}")
        raise last_error

    @staticmethod
    def generate_code() -> str:
        """生成 6 位数字验证码"""
        return f"{random.randint(0, 999999):06d}"

    async def send_verification_code(self, to: str) -> str:
        """
        发送验证码邮件（封装模板 + 重试）。

        验证码同时写入 Redis（key: ``email_code:{email}``，TTL 5 分钟）。

        Args:
            to: 收件人邮箱

        Returns:
            生成的验证码（便于测试断言；正常调用方无需使用）

        Raises:
            aiosmtplib.SMTPException: 重试耗尽后由 send_email 抛出
        """
        code = self.generate_code()
        html = await self._render_verification_template(code)

        # 先写入 Redis 再发送：即使发送失败，冷却期仍生效，防止刷接口
        redis = await self._get_redis()
        await redis.set(f"email_code:{to}", code, ex=CODE_TTL)

        await self.send_email(
            to,
            subject=f"【{self.smtp_from_name}】邮箱验证码",
            body=(
                f"您的验证码是：{code}，{CODE_TTL // 60} 分钟内有效。\n"
                f"如非本人操作，请忽略本邮件。"
            ),
            html=html,
        )
        return code

    async def verify_code(self, email: str, code: str) -> bool:
        """
        校验验证码（查询 Redis → 比对 → 删除，一次性使用）。

        错误次数累计到 MAX_CODE_ATTEMPTS 后删除验证码（锁定 15 分钟）。

        Args:
            email: 邮箱地址
            code: 用户输入的 6 位验证码

        Returns:
            True=校验通过（Redis 记录已删除），False=错误或已过期
        """
        redis = await self._get_redis()
        key = f"email_code:{email}"
        stored = await redis.get(key)
        if stored is None or stored != code:
            # 防暴力破解：累计错误次数，达到上限后删除验证码
            err_key = f"email_code_errors:{email}"
            count = await redis.incr(err_key)
            if count == 1:
                await redis.expire(err_key, ERROR_COUNT_TTL)
            if count >= MAX_CODE_ATTEMPTS:
                await redis.delete(key)
                logger.warning(f"邮箱验证码错误次数过多，已锁定: {email}")
            return False
        await redis.delete(key)
        await redis.delete(f"email_code_errors:{email}")
        return True

    def render_markdown_pdf(self, title: str, content: str) -> bytes:   # TODO 这个有点问题不能唱正常发送邮件
        """
        将 Markdown 内容渲染为 PDF（A4 页面）

        使用 PyMuPDF insert_htmlbox 渲染（自动换行、支持中文字体）；
        若 htmlbox 不可用则降级为 insert_font + insert_text 纯文本排版。

        Args:
            title: 文档标题（仅用于降级模式的页首标题）
            content: Markdown 正文

        Returns:
            PDF 二进制内容

        Raises:
            RuntimeError: 未找到可用的中文字体时
        """
        import fitz

        try:
            html_body = _markdown_to_html(content)
        except Exception as e:
            logger.warning(f"Markdown→HTML 转换失败，降级纯文本: {e}")
            html_body = None

        doc = fitz.open()
        try:
            page = doc.new_page(width=595, height=842)  # A4
            if html_body:
                css = '* { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif; }'
                page.insert_htmlbox(fitz.Rect(72, 72, 523, 800), html_body, css=css)
            else:
                self._render_pdf_plain(doc, page, title, content)
            return doc.tobytes()
        finally:
            doc.close()

    def _render_pdf_plain(self, doc, page, title: str, content: str) -> None:
        """降级方案：insert_font + insert_text 纯文本排版（手动换行分页）"""
        import fitz

        fontfile = self._find_cjk_font()
        if not fontfile:
            raise RuntimeError("未找到可用的中文字体，无法生成 PDF")
        fontname = "cjk_plain"
        page.insert_font(fontname=fontname, fontfile=fontfile)
        font = fitz.Font(fontfile=fontfile)

        page.insert_text((72, 72), title, fontname=fontname, fontsize=18)
        y = 108
        for line in _markdown_to_text(content).splitlines():
            for wrapped in _wrap_text(line, font, fontsize=11, max_width=460):
                if y > 800:
                    page = doc.new_page(width=595, height=842)
                    page.insert_font(fontname=fontname, fontfile=fontfile)
                    y = 72
                page.insert_text((72, y), wrapped, fontname=fontname, fontsize=11)
                y += 17

    @staticmethod
    def _find_cjk_font() -> Optional[str]:
        """查找系统中文字体文件"""
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
            "C:/Windows/Fonts/simhei.ttf", # 黑体
            "C:/Windows/Fonts/simsun.ttc", # 宋体
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    async def _render_verification_template(self, code: str) -> str:
        """加载 HTML 模板并填充验证码占位符"""
        try:
            template = self.template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(f"验证码邮件模板不存在: {self.template_path}，退回纯文本")
            return None
        return (
            template.replace("{{app_name}}", self.smtp_from_name)
            .replace("{{code}}", code)
            .replace("{{expire_minutes}}", str(CODE_TTL // 60))
        )

    @staticmethod
    async def _get_redis():
        """延迟导入并获取 Redis 客户端（避免模块级导入产生循环依赖）"""
        from app.db.redis_client import get_redis

        return get_redis()


# ============================================================
# Markdown → PDF 辅助函数（轻量渲染，非完整 CommonMark 实现）
# ============================================================

def _md_inline(s: str) -> str:
    """
    行内 Markdown 处理：**加粗** → <b>，`代码` → <code>，其余转义。
    用不可见占位符暂存标签，避免转义破坏标签本身。
    """
    s = s.replace("**", "\x01").replace("`", "\x02")
    parts = re.split(r"(\x01[^\x01]*\x01|\x02[^\x02]*\x02)", s)
    out = []
    for part in parts:
        if part.startswith("\x01") and part.endswith("\x01") and len(part) > 2:
            out.append(f"<b>{html_lib.escape(part[1:-1])}</b>")
        elif part.startswith("\x02") and part.endswith("\x02") and len(part) > 2:
            out.append(f"<code>{html_lib.escape(part[1:-1])}</code>")
        else:
            out.append(html_lib.escape(part.replace("\x01", "").replace("\x02", "")))
    return "".join(out)


def _markdown_to_html(md_text: str) -> str:
    """轻量 Markdown → HTML（标题/列表/引用/分割线/段落）"""
    parts = []
    in_list = False
    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        stripped = line.lstrip()
        if line.startswith("#"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            level = min(len(line) - len(line.lstrip("#")), 4)
            parts.append(f"<h{level}>{_md_inline(stripped.lstrip('#').strip())}</h{level}>")
        elif stripped.startswith(("-", "*", "+")) and not stripped.startswith("**"):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_md_inline(stripped[1:].strip())}</li>")
        elif stripped.startswith(">"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p style='color:#666666;'>{_md_inline(stripped.lstrip('>').strip())}</p>")
        elif stripped.startswith("```"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<pre>")
        elif line.strip() == "---" or line.strip() == "***":
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<hr/>")
        elif parts and parts[-1] == "<pre>":
            parts.append(f"<code>{html_lib.escape(line)}</code>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{_md_inline(line)}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def _markdown_to_text(md_text: str) -> str:
    """轻量 Markdown → 纯文本（降级 PDF 排版用）"""
    lines = []
    for raw in md_text.splitlines():
        line = raw.rstrip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "• ", line)
        line = re.sub(r"^\s*\d+\.\s+", "", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]*)\*\*", r"\1", line)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图片]", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        lines.append(line)
    return "\n".join(lines)


def _wrap_text(text: str, font, fontsize: float, max_width: float) -> List[str]:
    """按字符宽度手动换行（中英文混排）"""
    if not text:
        return [""]
    if font.text_length(text, fontsize=fontsize) <= max_width:
        return [text]
    lines = []
    current = ""
    for ch in text:
        if font.text_length(current + ch, fontsize=fontsize) > max_width and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines
