"""
冒烟测试（P1: CI 可跑，无 DB / Redis / LLM 外部依赖）

覆盖当前纯逻辑安全护栏:
- SSRF 地址守卫（app/utils/ssrf_guard.py，审查 P0-7）
- JWT_SECRET 启动强校验（app/utils/auth_utils.py，审查 P0-2）
- MCP 工具 SSRF 包装（app/ai_service/mcp_manager.py，审查 P0-7）

运行: python -m pytest tests/ -v
"""

import os
import socket

import pytest

from app.utils import ssrf_guard
from app.utils.ssrf_guard import validate_public_url


# ========== SSRF 守卫 ==========

class TestSsrfGuard:
    """URL 安全校验：私网/回环/云元数据必须拦截，公网必须放行"""

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/x",
        "http://localhost:8000/x",
        "http://169.254.169.254/latest/meta-data",   # 云元数据
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://[::1]:8080/",
        "http://0.0.0.0/",
        "ftp://example.com/",                        # 非 http/https 协议
        "javascript:alert(1)",
        "file:///etc/passwd",
        "",                                          # 空 URL
        None,                                        # 非字符串
    ])
    def test_block_unsafe(self, url):
        with pytest.raises(ValueError):
            validate_public_url(url)

    @pytest.mark.parametrize("url", [
        "https://8.8.8.8/",
        "https://1.1.1.1/dns",
    ])
    def test_allow_public(self, url):
        validate_public_url(url)  # 不应抛异常

    def test_allow_public_domain_via_dns(self, monkeypatch):
        # 模拟 DNS 返回公网 IP（真实环境可能被代理 fake-IP 污染，如 198.18.x.x）
        monkeypatch.setattr(
            ssrf_guard.socket, "getaddrinfo",
            lambda host, port: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))],
        )
        validate_public_url("https://example.com/page")  # 不应抛异常

    def test_block_domain_resolving_to_private(self, monkeypatch):
        # 域名解析到私网地址 → 必须拦截（DNS 解析路径）
        monkeypatch.setattr(
            ssrf_guard.socket, "getaddrinfo",
            lambda host, port: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
        )
        with pytest.raises(ValueError):
            validate_public_url("https://internal.example.com/")

    def test_extract_url_arg_kwargs(self):
        assert ssrf_guard.extract_url_arg((), {"url": "https://a.com"}) == "https://a.com"

    def test_extract_url_arg_positional_dict(self):
        assert ssrf_guard.extract_url_arg(({"url": "https://a.com"},), {}) == "https://a.com"

    def test_extract_url_arg_missing(self):
        assert ssrf_guard.extract_url_arg((), {"query": "x"}) is None


# ========== JWT_SECRET 强校验 ==========

class TestJwtSecretValidation:
    """公开默认密钥/过短密钥必须拒绝启动，强随机密钥必须放行"""

    def test_default_secret_blocked(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
        import importlib
        import app.utils.auth_utils as auth
        importlib.reload(auth)
        with pytest.raises(RuntimeError):
            auth.validate_jwt_secret()

    def test_dev_secret_blocked(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "raglearn-dev-secret-key-change-in-production-2026")
        import importlib
        import app.utils.auth_utils as auth
        importlib.reload(auth)
        with pytest.raises(RuntimeError):
            auth.validate_jwt_secret()

    def test_short_secret_blocked(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "short")
        import importlib
        import app.utils.auth_utils as auth
        importlib.reload(auth)
        with pytest.raises(RuntimeError):
            auth.validate_jwt_secret()

    def test_strong_secret_allowed(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "k9Xp2s5v8y1B4e7h0K3m6N9qRt2Wx5ZaCbDfGiLp")
        import importlib
        import app.utils.auth_utils as auth
        importlib.reload(auth)
        auth.validate_jwt_secret()  # 不应抛异常


# ========== MCP 工具 SSRF 包装 ==========

class TestMcpSsrfWrap:
    """含 url 参数的工具必须被包装，调用时拦截私网地址"""

    @staticmethod
    def _make_tool(url_field: bool = True):
        from pydantic import BaseModel

        from app.ai_service.mcp_manager import _wrap_ssrf_guard

        if url_field:
            class Args(BaseModel):
                url: str
        else:
            class Args(BaseModel):
                query: str

        class FakeTool:
            name = "fetch" if url_field else "tavily_search"
            args_schema = Args

            async def _arun(self, **kwargs):
                return "ORIGINAL"

        return _wrap_ssrf_guard(FakeTool()), FakeTool

    @pytest.mark.asyncio
    async def test_wrap_and_block(self, monkeypatch):
        wrapped, original_cls = self._make_tool(url_field=True)
        # 包装后 _arun 为实例级守卫函数（无 __func__），未包装时为类方法的绑定方法
        assert getattr(wrapped._arun, "__func__", wrapped._arun) is not original_cls._arun

        blocked = await wrapped._arun(url="http://169.254.169.254/")
        assert "拒绝" in blocked or "reject" in blocked.lower() or "Refuse" in blocked

        # 公网域名走 mock DNS（避免代理 fake-IP 影响测试确定性）
        monkeypatch.setattr(
            ssrf_guard.socket, "getaddrinfo",
            lambda host, port: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))],
        )
        allowed = await wrapped._arun(url="https://example.com/page")
        assert allowed == "ORIGINAL"

    def test_no_url_schema_not_wrapped(self):
        wrapped, original_cls = self._make_tool(url_field=False)
        # 无 url 参数 → 不包装：_arun 仍是类方法的绑定方法
        assert getattr(wrapped._arun, "__func__", wrapped._arun) is original_cls._arun
