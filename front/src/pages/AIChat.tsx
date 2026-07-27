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
import { Send, Square, Plus, User, Bot, FileText, X, Search } from 'lucide-react';
import { useSSE } from '../hooks/useSSE';
import { useSessionStore } from '../stores/useSessionStore';
import { useUserStore } from '../stores/useUserStore';
import { sessionsApi } from '../api/sessions';
import { notesApi } from '../api/notes';
import { endpoints } from '../api/endpoints';
import type { ChatMessage, Note } from '../types/api';
import PlanProgressCard from '../components/chat/PlanProgressCard';
import type { PlanStepData } from '../components/chat/PlanProgressCard';

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

  // 引用笔记状态
  const [selectedNotes, setSelectedNotes] = useState<Note[]>([]);
  const [showNotePicker, setShowNotePicker] = useState(false);
  const [noteList, setNoteList] = useState<Note[]>([]);
  const [noteSearch, setNoteSearch] = useState('');
  const [loadingNotes, setLoadingNotes] = useState(false);
  const notePickerRef = useRef<HTMLDivElement>(null);

  // Plan-and-Execute 进度状态
  const [planGoal, setPlanGoal] = useState('');
  const [planSteps, setPlanSteps] = useState<PlanStepData[]>([]);
  const [planTotalSteps, setPlanTotalSteps] = useState(0);
  const [planCompletedSteps, setPlanCompletedSteps] = useState(0);
  const [planActive, setPlanActive] = useState(false);
  const [planComplete, setPlanComplete] = useState(false);
  const [currentTool, setCurrentTool] = useState('');

  // requestAnimationFrame 节流：合并高频 token 更新
  const rafRef = useRef<number | null>(null);
  const pendingContentRef = useRef('');

  const messages = useSessionStore((s) => s.messages);
  const addMessage = useSessionStore((s) => s.addMessage);
  const setMessages = useSessionStore((s) => s.setMessages);
  const updateLastAssistantMessage = useSessionStore((s) => s.updateLastAssistantMessage);
  const clearCurrentSession = useSessionStore((s) => s.clearCurrentSession);
  const setLastSessionId = useSessionStore((s) => s.setLastSessionId);
  const userAvatar = useUserStore((s) => s.userInfo?.avatar);

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

  /** 点击外部关闭笔记选择面板 */
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (notePickerRef.current && !notePickerRef.current.contains(e.target as Node)) {
        setShowNotePicker(false);
      }
    };
    if (showNotePicker) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showNotePicker]);

  /** 打开笔记选择面板时加载笔记列表 */
  const toggleNotePicker = async () => {
    if (!showNotePicker) {
      setShowNotePicker(true);
      setNoteSearch('');
      setLoadingNotes(true);
      try {
        const res = await notesApi.list({ page: 1, page_size: 100 });
        setNoteList(res.data?.data?.notes ?? []);
      } catch (err) {
        console.error('[AIChat] 加载笔记列表失败:', err);
      } finally {
        setLoadingNotes(false);
      }
    } else {
      setShowNotePicker(false);
    }
  };

  /** 切换笔记选中状态 */
  const toggleNote = (note: Note) => {
    setSelectedNotes((prev) => {
      const exists = prev.find((n) => n.id === note.id);
      if (exists) return prev.filter((n) => n.id !== note.id);
      return [...prev, note];
    });
  };

  /** 移除已引用的笔记 */
  const removeNote = (noteId: string) => {
    setSelectedNotes((prev) => prev.filter((n) => n.id !== noteId));
  };

  /** 过滤后的笔记列表 */
  const filteredNotes = noteList.filter((n) =>
    n.title.toLowerCase().includes(noteSearch.toLowerCase())
  );

  /** 发送消息 */
  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;

    // 构建发送内容：若有引用笔记，将笔记内容作为上下文附加
    let messageText = input;
    if (selectedNotes.length > 0) {
      const noteContext = selectedNotes
        .map((n) => `【笔记：${n.title}】\n${n.content}`)
        .join('\n\n');
      messageText = `${input}\n\n---\n以下是用户引用的笔记内容，请结合这些内容回答：\n${noteContext}`;
    }

    const userMsg: ChatMessage = {
      id: Date.now(),
      session_id: sessionId || '',
      role: 'user',
      content: input, // 气泡中只显示用户原始输入
      created_at: new Date().toISOString(),
    };
    addMessage(userMsg);
    setInput('');
    setSelectedNotes([]);
    setIsStreaming(true);
    setThinkingStages([]);
    // 重置 Plan 状态
    setPlanGoal('');
    setPlanSteps([]);
    setPlanTotalSteps(0);
    setPlanCompletedSteps(0);
    setPlanActive(false);
    setPlanComplete(false);

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

    // 节流刷新函数：用 rAF 合并高频 token 更新
    const scheduleFlush = () => {
      if (rafRef.current !== null) return; // 已有待处理的 rAF
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (pendingContentRef.current) {
          updateLastAssistantMessage(pendingContentRef.current);
          pendingContentRef.current = '';
        }
      });
    };

    try {
      await start(
        endpoints.chat.query,
        { session_id: sessionId, message: messageText },
        {
          onThinking: (stage, content) => {
            setThinkingStages((prev) => [...prev, { stage, content }]);
          },
          onResponse: (content) => {
            accumulated += content;
            pendingContentRef.current = accumulated;
            scheduleFlush();
          },
          onDone: (newSessionId) => {
            // 确保最后一次更新被刷新
            if (rafRef.current !== null) {
              cancelAnimationFrame(rafRef.current);
              rafRef.current = null;
            }
            if (pendingContentRef.current) {
              updateLastAssistantMessage(pendingContentRef.current);
              pendingContentRef.current = '';
            }
            setIsStreaming(false);
            setCurrentTool('');
            // 新会话创建后记录并更新 URL
            if (newSessionId) {
              setLastSessionId(newSessionId);
              if (!sessionId) {
                navigate(`/chat/${newSessionId}`, { replace: true });
              }
            }
          },
          onError: (msg) => {
            // 确保错误前内容被刷新
            if (rafRef.current !== null) {
              cancelAnimationFrame(rafRef.current);
              rafRef.current = null;
            }
            if (pendingContentRef.current) {
              updateLastAssistantMessage(pendingContentRef.current);
              pendingContentRef.current = '';
            }
            updateLastAssistantMessage(`⚠️ ${msg}`);
            setIsStreaming(false);
            setCurrentTool('');
          },
          // Plan-and-Execute 事件回调
          onPlanStart: (goal, totalSteps) => {
            setPlanActive(true);
            setPlanGoal(goal);
            setPlanTotalSteps(totalSteps);
          },
          onPlanStep: (step, action, status) => {
            setPlanSteps((prev) => {
              const existing = prev.find((s) => s.step === step);
              if (existing) {
                return prev.map((s) => s.step === step ? { ...s, status: status as PlanStepData['status'] } : s);
              }
              return [...prev, { step, action, status: status as PlanStepData['status'] }];
            });
          },
          onPlanStepStart: (step, _action) => {
            setPlanSteps((prev) =>
              prev.map((s) => s.step === step ? { ...s, status: 'running' as const } : s)
            );
          },
          onPlanStepEnd: (step, result) => {
            setPlanSteps((prev) =>
              prev.map((s) => s.step === step ? { ...s, status: 'completed' as const, result } : s)
            );
            setPlanCompletedSteps((c) => c + 1);
          },
          onPlanSynthesize: () => {
            // 综合阶段开始，所有步骤已完成
          },
          onPlanComplete: (totalSteps, completedSteps) => {
            setPlanTotalSteps(totalSteps);
            setPlanCompletedSteps(completedSteps);
            setPlanComplete(true);
          },
          onPlanFallback: (_reason) => {
            // Plan 失败降级为 ReAct，隐藏进度条
            setPlanActive(false);
            setCurrentTool('');
          },
          // 工具调用事件
          onToolStart: (name) => {
            setCurrentTool(name);
          },
          onToolEnd: (_name) => {
            setCurrentTool('');
          },
        }
      );
    } finally {
      // 无论正常结束、报错还是用户点击停止（AbortError），都确保重置流式状态
      setIsStreaming(false);
      // 清理 rAF
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (pendingContentRef.current) {
        updateLastAssistantMessage(pendingContentRef.current);
        pendingContentRef.current = '';
      }
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
          <div key={msg.id} className={`flex items-start gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-[var(--color-accent-bg)]">
                <Bot size={18} className="text-[var(--color-accent)]" />
              </div>
            )}
            <div className={`max-w-[80%] p-3 rounded-[var(--radius-md)] ${
              msg.role === 'user'
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-card)] border border-[var(--color-border)] text-[var(--color-text)]'
            }`}>
              {/* Plan 进度卡片（仅在最后一条 AI 消息上显示） */}
              {msg.role === 'assistant' && planActive && msg === messages[messages.length - 1] && (
                <PlanProgressCard
                  goal={planGoal}
                  steps={planSteps}
                  completedSteps={planCompletedSteps}
                  totalSteps={planTotalSteps}
                  isComplete={planComplete}
                  currentTool={currentTool}
                />
              )}
              {msg.role === 'assistant' && thinkingStages.length > 0 && !msg.content && (
                <div className="mb-2 text-xs text-[var(--color-text-tertiary)]">
                  {thinkingStages.map((s, i) => (
                    <div key={i}>• {s.content || s.stage}</div>
                  ))}
                </div>
              )}
              <div className="text-sm whitespace-pre-wrap">{msg.content || '...'}</div>
            </div>
            {msg.role === 'user' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-[var(--color-accent)] overflow-hidden">
                {userAvatar ? (
                  <img src={userAvatar} alt="avatar" className="w-8 h-8 rounded-full object-cover" />
                ) : (
                  <User size={18} className="text-white" />
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 引用笔记标签 */}
      {selectedNotes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selectedNotes.map((note) => (
            <span
              key={note.id}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-[var(--radius-md)] bg-[var(--color-accent-bg)] text-[var(--color-accent)] border border-[var(--color-accent)]/20"
            >
              <FileText size={12} />
              <span className="max-w-[120px] truncate">{note.title}</span>
              <button onClick={() => removeNote(note.id)} className="hover:opacity-70">
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 输入区 */}
      <div className="relative flex gap-2">
        {/* 引用笔记按钮 */}
        <button
          onClick={toggleNotePicker}
          className={`flex-shrink-0 px-3 py-2.5 rounded-[var(--radius-md)] border transition-colors ${
            showNotePicker || selectedNotes.length > 0
              ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent-bg)]'
              : 'border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
          }`}
          title="引用笔记"
        >
          <FileText size={18} />
        </button>

        {/* 笔记选择面板 */}
        {showNotePicker && (
          <div
            ref={notePickerRef}
            className="absolute bottom-full mb-2 left-0 w-72 max-h-64 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] shadow-lg z-10 flex flex-col"
          >
            {/* 搜索栏 */}
            <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
              <Search size={14} className="text-[var(--color-text-tertiary)]" />
              <input
                type="text"
                value={noteSearch}
                onChange={(e) => setNoteSearch(e.target.value)}
                placeholder="搜索笔记..."
                className="flex-1 text-sm bg-transparent text-[var(--color-text)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none"
              />
            </div>
            {/* 笔记列表 */}
            <div className="flex-1 overflow-y-auto">
              {loadingNotes ? (
                <div className="text-center py-6 text-sm text-[var(--color-text-tertiary)]">加载中...</div>
              ) : filteredNotes.length === 0 ? (
                <div className="text-center py-6 text-sm text-[var(--color-text-tertiary)]">暂无笔记</div>
              ) : (
                filteredNotes.map((note) => {
                  const isSelected = selectedNotes.some((n) => n.id === note.id);
                  return (
                    <button
                      key={note.id}
                      onClick={() => toggleNote(note)}
                      className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${
                        isSelected
                          ? 'bg-[var(--color-accent-bg)] text-[var(--color-accent)]'
                          : 'text-[var(--color-text)] hover:bg-[var(--color-accent-bg)]'
                      }`}
                    >
                      <FileText size={14} className="flex-shrink-0" />
                      <span className="truncate">{note.title}</span>
                      {note.category && (
                        <span className="ml-auto text-xs text-[var(--color-text-tertiary)] flex-shrink-0">{note.category}</span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}

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
