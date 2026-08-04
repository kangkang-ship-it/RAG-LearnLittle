"""
Token 预算管理模块

精确控制每次 LLM 调用中各组件消耗的 token 数量，
确保总消耗不超出模型的上下文窗口限制。

职责：
- TokenBudget: 静态配置 + 动态配额分配
- TokenCounter: 基于 tiktoken 的 token 计数
"""

from dataclasses import dataclass
from typing import List, Optional

from app.core.logger_handler import logger


# ========== Token 计数器 ==========

class TokenCounter:
    """
    Token 计数器（基于 tiktoken）
    
    使用编码器缓存避免重复加载，支持中英文混合文本。
    """
    
    _encoders: dict = {}
    
    @classmethod
    def get_encoder(cls, model_name: str = "cl100k_base"):
        """获取编码器（带缓存）"""
        if model_name not in cls._encoders:
            try:
                import tiktoken
                cls._encoders[model_name] = tiktoken.get_encoding(model_name)
            except Exception as e:
                logger.warning(f"tiktoken 加载失败，回退到字符估算: {e}")
                cls._encoders[model_name] = None
        return cls._encoders[model_name]
    
    @classmethod
    def count(cls, text: str, model_name: str = "cl100k_base") -> int:
        """计算文本的 token 数量"""
        if not text:
            return 0
        encoder = cls.get_encoder(model_name)
        if encoder:
            return len(encoder.encode(text))
        # 回退：中文约 1.5 字符/token，英文约 4 字符/token
        return max(1, len(text) // 2)
    
    @classmethod
    def count_image(cls, width: int, height: int) -> int:
        """
        估算单张图片的 token 消耗（按长边分辨率，DashScope VL 系列计价简化公式）

        Args:
            width: 图片宽度（像素）
            height: 图片高度（像素）

        Returns:
            估算 token 数
        """
        if not width or not height:
            return 1500  # 未知尺寸按中等估算
        long_edge = max(width, height)
        if long_edge <= 1024:
            return 1000
        return 2000

    @classmethod
    def count_content(cls, content, model_name: str = "cl100k_base") -> int:
        """
        计算消息 content 的 token 数（兼容多模态 content 块列表）

        content 为字符串 → 文本计数；
        content 为列表（OpenAI 多模态格式）→ 逐块累计：
        - text 块走文本计数
        - image_url 块按图片尺寸估算（无法获取尺寸时按中等估算）
        - video_url 块按固定预留（帧数未知，按 8 帧估算）

        Args:
            content: 消息 content（str 或多模态块列表）
            model_name: 编码器名称

        Returns:
            token 数
        """
        if isinstance(content, str):
            return cls.count(content, model_name)
        if isinstance(content, list):
            total = 0
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    total += cls.count(block.get("text", ""), model_name)
                elif block_type == "image_url":
                    total += 1500  # 无尺寸信息，按中等估算（见 count_image）
                elif block_type == "video_url":
                    total += 16000  # 视频按 8 帧 × 2000 估算
            return total
        return cls.count(str(content), model_name)

    @classmethod
    def count_messages(cls, messages: list, model_name: str = "cl100k_base") -> int:
        """计算消息列表的总 token 数（含角色标记开销，支持多模态 content）"""
        total = 0
        for msg in messages:
            total += 4  # 每条消息固定开销：角色标记
            content = ""
            if hasattr(msg, "content"):
                content = msg.content or ""
            elif isinstance(msg, dict):
                content = msg.get("content", "")
            else:
                content = str(msg)
            total += cls.count_content(content, model_name)
        total += 2  # 序列结束标记
        return total


# ========== Token 预算 ==========

@dataclass
class TokenBudget:
    """
    Token 预算分配
    
    根据模型上下文窗口大小，为各组件分配固定/动态配额。
    """
    model_context_size: int = 32768       # 模型上下文窗口总大小

    # 固定分配
    system_prompt: int = 500              # 系统提示词
    rag_context_max: int = 2000           # RAG 上下文上限
    summary_max: int = 800               # 摘要文本上限
    agent_scratchpad_reserve: int = 4000  # 工具调用预留
    current_input_estimate: int = 300     # 当前输入估算
    safety_margin: int = 1000             # 安全余量

    # 多模态（图片/视频）预算
    image_tokens_per_msg: int = 3000      # 单条消息图片预留（当前消息优先保证）
    max_history_images: int = 4           # 历史回放单条消息最多保留的图片数
    
    @property
    def fixed_budget(self) -> int:
        """固定消耗的 token 总量"""
        return (
            self.system_prompt
            + self.rag_context_max
            + self.summary_max
            + self.agent_scratchpad_reserve
            + self.current_input_estimate
            + self.safety_margin
        )
    
    @property
    def available_for_history(self) -> int:
        """chat_history 可用的 token 配额"""
        return max(0, self.model_context_size - self.fixed_budget)
    
    def allocate(self, rag_context_len: int = 0) -> int:
        """
        动态配额分配
        
        根据实际 RAG 上下文长度，计算 chat_history 可用配额。
        
        Args:
            rag_context_len: RAG 上下文的实际字符长度
            
        Returns:
            chat_history 可用的 token 配额
        """
        # 实际 RAG 消耗（取上限和实际值的较小者）
        actual_rag_tokens = min(
            TokenCounter.count(rag_context_len if isinstance(rag_context_len, str) else ""),
            self.rag_context_max
        )
        
        # 配额 = 总窗口 - 固定消耗 - 实际 RAG 消耗
        quota = self.model_context_size - self.fixed_budget - actual_rag_tokens
        
        # 最小保证 500 tokens
        quota = max(500, quota)
        
        logger.debug(
            f"Token 预算分配: total={self.model_context_size}, "
            f"fixed={self.fixed_budget}, rag={actual_rag_tokens}, "
            f"history_quota={quota}"
        )
        return quota
