/**
 * AI 对话页面
 * 
 * 功能：
 * 1. SSE 流式对话（思考过程实时展示）
 * 2. Markdown 渲染 AI 回答
 * 3. 消息气泡列表 + 自动滚动
 * 4. 快捷问题按钮
 */

import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Send, Square, Plus } from 'lucide-react';
import { useSSE } from '../hooks/useSSE';
import { useSessionStore } from '../stores/useSessionStore';
import { sessionsApi } from '../api/sessions';
import { endpoints } from '../api/endpoints';
import type { ChatMessage } from '../types/api';

export default function AIChat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { start, stop } = useSSE();

  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [thinkingStages, setThinkingStages] = useState<{ stage: string; content: string }[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const messages = useSessionStore((s) => s.messages);
  const addMessage = useSessionStore((s) => s.addMessage);
  const setMessages = useSessionStore((s) => s.setMessages);
  const updateLastAssistantMessage = useSessionStore((s) => s.updateLastAssistantMessage);
  const clearCurrentSession = useSessionStore((s) => s.clearCurrentSession);
  const setLastSessionId = useSessionStore((s) => s.setLastSessionId);

  /** 进入会话时加载历史消息，或恢复最近会话 */
  useEffect(() => {
    if (!sessionId) {
      // /chat 无 sessionId：通过 getState() 读取最新 lastSessionId（不加入依赖数组，避免状态变化触发 effect）
      const lastId = useSessionStore.getState().lastSessionId;
      if (lastId) {
        navigate(`/chat/${lastId}`, { replace: true });
        return;
      }
      // 无最近会话：真正的新对话，清空状态
      clearCurrentSession();
      return;
    }

    // 有 sessionId：记录为最近会话并加载消息
    setLastSessionId(sessionId);

    let cancelled = false;
    (async () => {
      setLoadingMessages(true);
      try {
        const res = await sessionsApi.getMessages(sessionId);
        if (cancelled) return;
        const msgs = res.data?.data?.messages ?? [];
        setMessages(msgs);
      } catch (err) {
        if (!cancelled) {
          // 404 表示会话已被删除，清除残留状态并回退到空白新对话
          const status = (err as { response?: { status?: number } })?.response?.status;
          if (status === 404) {
            console.warn('[AIChat] 会话不存在(404)，清除残留状态');
            clearCurrentSession();
            navigate('/chat', { replace: true });
          } else {
            console.error('[AIChat] 加载历史消息失败:', err);
          }
        }
      } finally {
        if (!cancelled) setLoadingMessages(false);
      }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  /** 自动滚动到底部 */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  /** 发送消息 */
  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      id: Date.now(),
      session_id: sessionId || '',
      role: 'user',
      content: input,
      created_at: new Date().toISOString(),
    };
    addMessage(userMsg);
    setInput('');
    setIsStreaming(true);
    setThinkingStages([]);

    // 添加 AI 占位消息
    const aiMsg: ChatMessage = {
      id: Date.now() + 1,
      session_id: sessionId || '',
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    };
    addMessage(aiMsg);

    let accumulated = '';

    try {
      await start(
        endpoints.chat.query,
        { session_id: sessionId, message: input },
        {
          onThinking: (stage, content) => {
            setThinkingStages((prev) => [...prev, { stage, content }]);
          },
          onResponse: (content) => {
            accumulated += content;
            updateLastAssistantMessage(accumulated);
          },
          onDone: (newSessionId) => {
            setIsStreaming(false);
            // 新会话创建后记录并更新 URL
            if (newSessionId) {
              setLastSessionId(newSessionId);
              if (!sessionId) {
                navigate(`/chat/${newSessionId}`, { replace: true });
              }
            }
          },
          onError: (msg) => {
            updateLastAssistantMessage(`⚠️ ${msg}`);
            setIsStreaming(false);
          },
        }
      );
    } finally {
      // 无论正常结束、报错还是用户点击停止（AbortError），都确保重置流式状态
      setIsStreaming(false);
    }
  };

  const quickQuestions = ['帮我解释量子计算', '写一首春天的诗', '推荐几本好书'];

  return (
    <div className="flex flex-col h-[calc(100vh-48px)]">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-heading font-bold text-[var(--color-text)]">
          {t('nav.chat')}
        </h1>
        <button
          onClick={() => {
            clearCurrentSession();
            navigate('/chat');
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-[var(--radius-md)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)] transition-colors"
          title="新建对话"
        >
          <Plus size={16} />
          <span>新对话</span>
        </button>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {loadingMessages ? (
          <div className="text-center py-16">
            <p className="text-[var(--color-text-tertiary)]">{t('common.loading')}</p>
          </div>
        ) : messages.length === 0 && !sessionId ? (
          <div className="text-center py-16">
            <p className="text-[var(--color-text-tertiary)] mb-4">💡 快捷问题</p>
            <div className="flex flex-wrap justify-center gap-2">
              {quickQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="px-3 py-1.5 text-sm rounded-full border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] p-3 rounded-[var(--radius-md)] ${
              msg.role === 'user'
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-card)] border border-[var(--color-border)] text-[var(--color-text)]'
            }`}>
              {msg.role === 'assistant' && thinkingStages.length > 0 && !msg.content && (
                <div className="mb-2 text-xs text-[var(--color-text-tertiary)]">
                  {thinkingStages.map((s, i) => (
                    <div key={i}>• {s.content || s.stage}</div>
                  ))}
                </div>
              )}
              <div className="text-sm whitespace-pre-wrap">{msg.content || '...'}</div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder={t('chat.placeholder')}
          className="flex-1 px-4 py-2.5 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          disabled={isStreaming}
        />
        {isStreaming ? (
          <button
            onClick={stop}
            className="px-4 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-danger)] text-white hover:opacity-90"
          >
            <Square size={18} />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="px-4 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white hover:opacity-90 disabled:opacity-50"
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  );
}
