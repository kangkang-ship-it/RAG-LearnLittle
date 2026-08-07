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
import { Send, Square, Plus, User, FileText, X, Search, Brain, Paperclip, Download, Loader2, Presentation } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import { normalizeCategory } from '../constants/noteCategories';
import { useSSE } from '../hooks/useSSE';
import { useSessionStore } from '../stores/useSessionStore';
import { useUserStore } from '../stores/useUserStore';
import { sessionsApi } from '../api/sessions';
import { notesApi } from '../api/notes';
import { endpoints } from '../api/endpoints';
import { uploadChatFile, deleteChatFile } from '../api/chat';
import type { ChatMessage, Note, AttachmentMeta, ToolFileInfo } from '../types/api';
import { pptTemplatesApi, type PptTemplateInfo } from '../api/pptTemplates';
import client from '../api/client';
import PlanProgressCard from '../components/chat/PlanProgressCard';
import type { PlanStepData } from '../components/chat/PlanProgressCard';
import AttachmentBar from '../components/chat/AttachmentBar';
import type { PendingAttachment } from '../components/chat/AttachmentBar';
import AttachmentViewer from '../components/chat/AttachmentViewer';

// 附件限制（与后端 .env 配置保持一致）
const MAX_IMAGES_PER_MSG = 6;
const MAX_VIDEOS_PER_MSG = 1;
const MAX_IMAGE_MB = 10;
const MAX_VIDEO_MB = 50;

/** 工具名 → 中文展示名（简单路径补转发工具事件后的状态指示，§7） */
const TOOL_NAME_MAP: Record<string, string> = {
  generate_ppt_tool: '正在生成 PPT（约需 20~30 秒）…',
  search_notes_tool: '正在搜索笔记…',
  get_note_content_tool: '正在读取笔记内容…',
  get_note_stats_tool: '正在统计笔记…',
  get_today_reviews_tool: '正在获取待回顾笔记…',
  mark_reviewed_tool: '正在标记回顾…',
  create_note_tool: '正在创建笔记…',
  update_note_tool: '正在更新笔记…',
  get_related_notes_tool: '正在查找关联笔记…',
  get_user_info_tools: '正在读取用户信息…',
  send_email: '正在发送邮件…',
  what_time_is_now: '正在获取时间…',
};

export default function AIChat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { start, stop } = useSSE();

  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  // 思考阶段日志仍在 SSE 回调中收集（保留收集便于将来恢复展示），当前 UI 仅显示"正在思考"加载动画
  const [, setThinkingStages] = useState<{ stage: string; content: string }[]>([]);
  // 深度思考开关（默认关闭；开启后请求带 enable_thinking=true，后端切换思考模型）
  const [enableThinking, setEnableThinking] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 引用笔记状态
  const [selectedNotes, setSelectedNotes] = useState<Note[]>([]);
  const [showNotePicker, setShowNotePicker] = useState(false);
  const [noteList, setNoteList] = useState<Note[]>([]);
  const [noteSearch, setNoteSearch] = useState('');
  const [loadingNotes, setLoadingNotes] = useState(false);
  const notePickerRef = useRef<HTMLDivElement>(null);

  // PPT 模板选择状态（v1.4，设计方案 §6.5：与笔记一起选中，单选）
  const [selectedTemplate, setSelectedTemplate] = useState<PptTemplateInfo | null>(null);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [templateList, setTemplateList] = useState<PptTemplateInfo[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const templatePickerRef = useRef<HTMLDivElement>(null);

  // 附件状态（上传预览条）
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Plan-and-Execute 进度状态
  const [planGoal, setPlanGoal] = useState('');
  const [planSteps, setPlanSteps] = useState<PlanStepData[]>([]);
  const [planTotalSteps, setPlanTotalSteps] = useState(0);
  const [planCompletedSteps, setPlanCompletedSteps] = useState(0);
  const [planActive, setPlanActive] = useState(false);
  const [planComplete, setPlanComplete] = useState(false);
  const [currentTool, setCurrentTool] = useState('');
  // PPT 生成完成信息（tool_file 事件，§7 下载卡片）
  const [pptFile, setPptFile] = useState<ToolFileInfo | null>(null);

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

  /** 点击外部关闭笔记/模板选择面板 */
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (notePickerRef.current && !notePickerRef.current.contains(e.target as Node)) {
        setShowNotePicker(false);
      }
      if (templatePickerRef.current && !templatePickerRef.current.contains(e.target as Node)) {
        setShowTemplatePicker(false);
      }
    };
    if (showNotePicker || showTemplatePicker) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showNotePicker, showTemplatePicker]);

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

  /** 打开/关闭 PPT 模板选择面板（打开时懒加载模板列表） */
  const toggleTemplatePicker = async () => {
    if (!showTemplatePicker) {
      setShowTemplatePicker(true);
      setLoadingTemplates(true);
      try {
        const res = await pptTemplatesApi.list();
        setTemplateList(res.data?.data?.templates ?? []);
      } catch {
        setTemplateList([]);
      } finally {
        setLoadingTemplates(false);
      }
    } else {
      setShowTemplatePicker(false);
    }
  };

  /** 切换模板选中状态（单选；再次点击取消） */
  const toggleTemplate = (tmpl: PptTemplateInfo) => {
    setSelectedTemplate((prev) => (prev?.id === tmpl.id ? null : tmpl));
  };

  /** 移除已引用的笔记 */
  const removeNote = (noteId: string) => {
    setSelectedNotes((prev) => prev.filter((n) => n.id !== noteId));
  };

  /** 过滤后的笔记列表 */
  const filteredNotes = noteList.filter((n) =>
    n.title.toLowerCase().includes(noteSearch.toLowerCase())
  );

  /** 选择文件（前端预校验：类型/大小/数量上限，然后逐个上传） */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ''; // 允许重复选择同一文件

    if (files.length === 0) return;

    let imgCount = pendingAttachments.filter((a) => a.fileType === 'image').length;
    let vidCount = pendingAttachments.filter((a) => a.fileType === 'video').length;

    const newItems: PendingAttachment[] = [];
    for (const file of files) {
      const isImage = file.type.startsWith('image/');
      const isVideo = file.type.startsWith('video/');
      if (!isImage && !isVideo) {
        alert(`不支持的文件类型: ${file.name}（仅支持图片/视频）`);
        continue;
      }
      const maxMB = isImage ? MAX_IMAGE_MB : MAX_VIDEO_MB;
      if (file.size > maxMB * 1024 * 1024) {
        alert(`${file.name} 超过大小限制 ${maxMB}MB`);
        continue;
      }
      if (isImage && imgCount >= MAX_IMAGES_PER_MSG) {
        alert(`单条消息最多上传 ${MAX_IMAGES_PER_MSG} 张图片`);
        break;
      }
      if (isVideo && vidCount >= MAX_VIDEOS_PER_MSG) {
        alert(`单条消息最多上传 ${MAX_VIDEOS_PER_MSG} 个视频`);
        continue;
      }

      const att: PendingAttachment = {
        localId: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        file,
        fileType: isImage ? 'image' : 'video',
        name: file.name,
        previewUrl: URL.createObjectURL(file), // 本地预览（objectURL）
        status: 'uploading',
        progress: 0,
      };
      newItems.push(att);
      if (isImage) imgCount++;
      else vidCount++;
    }

    if (newItems.length === 0) return;
    setPendingAttachments((prev) => [...prev, ...newItems]);
    newItems.forEach(uploadAttachment);
  };

  /** 上传单个附件（XHR 带进度，成功后记录 file_id） */
  const uploadAttachment = (att: PendingAttachment) => {
    uploadChatFile(att.file, (percent) => {
      setPendingAttachments((prev) =>
        prev.map((a) => (a.localId === att.localId ? { ...a, progress: percent } : a))
      );
    })
      .then((resp) => {
        setPendingAttachments((prev) =>
          prev.map((a) =>
            a.localId === att.localId
              ? {
                  ...a,
                  status: 'done',
                  fileId: resp.file_id,
                  width: resp.width ?? undefined,
                  height: resp.height ?? undefined,
                }
              : a
          )
        );
      })
      .catch((err) => {
        console.error('[AIChat] 附件上传失败:', err);
        setPendingAttachments((prev) =>
          prev.map((a) => (a.localId === att.localId ? { ...a, status: 'error' } : a))
        );
      });
  };

  /** 移除附件（已上传的调 DELETE 接口；未发送可删） */
  const removeAttachment = (localId: string) => {
    const target = pendingAttachments.find((a) => a.localId === localId);
    if (!target) return;
    if (target.previewUrl) URL.revokeObjectURL(target.previewUrl);
    // 已上传且未随消息发送 → 调删除接口（失败由后端孤儿清理兜底）
    if (target.fileId) {
      deleteChatFile(target.fileId).catch((err) =>
        console.warn('[AIChat] 附件删除失败:', err)
      );
    }
    setPendingAttachments((prev) => prev.filter((a) => a.localId !== localId));
  };

  /** 发送消息 */
  const handleSend = async () => {
    // 附件前置校验：正在上传 / 有失败附件
    const uploading = pendingAttachments.some((a) => a.status === 'uploading');
    const failed = pendingAttachments.some((a) => a.status === 'error');
    const readyAttachments = pendingAttachments.filter((a) => a.status === 'done' && a.fileId);
    const attachmentIds = readyAttachments.map((a) => a.fileId!);
    if ((!input.trim() && attachmentIds.length === 0) || isStreaming) return;
    if (uploading) {
      alert('附件正在上传，请稍候再发送');
      return;
    }
    if (failed) {
      alert('有附件上传失败，请移除后重试');
      return;
    }

    // 构建发送内容：若有引用笔记，将笔记内容作为上下文附加（含 ID 供 Agent 直接更新）
    let messageText = input;
    if (selectedNotes.length > 0) {
      const noteContext = selectedNotes
        .map((n) => `【笔记：${n.title}】\n${n.content}`)
        .join('\n\n');
      // 结构化引用块：包含笔记 ID，供后端解析并注入 Agent 上下文
      const noteRefBlock = selectedNotes
        .map((n) => `- ID: ${n.id} | 标题: ${n.title}`)
        .join('\n');
      messageText = `${input}\n\n---\n以下是用户引用的笔记内容，请结合这些内容回答：\n${noteContext}\n\n<referenced_notes>\n${noteRefBlock}\n</referenced_notes>`;
    }
    // 附加用户选择的 PPT 模板（v1.4，§6.5：后端解析注入 system_prompt，LLM 填入工具参数）
    if (selectedTemplate) {
      messageText += `\n\n<ppt_template>\n- ID: ${selectedTemplate.id} | 名称: ${selectedTemplate.name}\n</ppt_template>`;
    }

    // 乐观用户消息：附带附件元数据（气泡立即渲染，历史回显走后端附件数据）
    const userAttachments: AttachmentMeta[] = readyAttachments.map((a) => ({
      file_id: a.fileId!,
      file_type: a.fileType,
      original_name: a.name,
      file_size: a.file.size,
      width: a.width,
      height: a.height,
    }));
    const userMsg: ChatMessage = {
      id: Date.now(),
      session_id: sessionId || '',
      role: 'user',
      content: input, // 气泡中只显示用户原始输入
      created_at: new Date().toISOString(),
      attachments: userAttachments.length > 0 ? userAttachments : undefined,
    };
    addMessage(userMsg);
    setInput('');
    setSelectedNotes([]);
    setIsStreaming(true);
    setThinkingStages([]);
    // 重置 Plan 状态
    setPlanGoal('');
    setPlanSteps([]);
    setPptFile(null);
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
        {
          session_id: sessionId,
          message: messageText,
          enable_thinking: enableThinking,
          attachment_ids: attachmentIds,
        },
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
          // 工具产出文件事件（PPT 生成完成，§6.3 第 3 段）
          onToolFile: (info) => {
            setPptFile(info);
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
      // 清理附件预览条（附件已随消息发出，fileId 由后端管理）
      pendingAttachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
      setPendingAttachments([]);
    }
  };

  const quickQuestions = ['帮我解释量子计算', '写一首春天的诗', '推荐几本好书'];

/**
 * AI 消息内容渲染：Markdown + LaTeX 数学公式（KaTeX）
 * - remarkMath 解析 $...$ 行内公式与 $$...$$ 块级公式
 * - rehypeKatex 将公式渲染为 KaTeX 排版
 * - 流式中间态（未闭合的公式/代码块）由 react-markdown 安全降级为纯文本
 */
function MessageContent({ content }: { content: string }) {
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

/**
 * PPT 下载卡片（tool_file 事件，§7 下载实现）
 * 下载走 axios client（自动注入 JWT + 401 自动 refresh 重试，不能用 <a href>）
 */
function PptDownloadCard({ file }: { file: ToolFileInfo }) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      // 用 axios client 而非原生 fetch：
      // ① 请求拦截器自动注入 JWT；② 401 自动 refresh 并重试（access token
      // 30 分钟过期，原生 fetch 无此机制会导致过期后下载 401「缺少认证信息」）
      const res = await client.get(file.download_url, { responseType: 'blob' });
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${file.title || '讲解PPT'}.pptx`;   // 文件名取自 tool_file 事件的 title
      document.body.appendChild(a);
      a.click();
      URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        alert('文件已过期，请重新生成');
      } else if (status === 401) {
        alert('登录已过期，请重新登录');
      } else {
        alert(`下载失败(${status ?? '未知错误'})`);
      }
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mt-2 flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-accent-bg)] px-3 py-2">
      <span className="text-lg" role="img" aria-label="PPT">📄</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--color-text)] truncate">
          已生成讲解 PPT{file.slide_count ? `（${file.slide_count} 页）` : ''}
        </p>
        <p className="text-xs text-[var(--color-text-tertiary)] truncate">
          {file.title || '讲解PPT'}
        </p>
      </div>
      <button
        onClick={handleDownload}
        disabled={downloading}
        className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        <Download size={14} />
        {downloading ? '下载中…' : '下载'}
      </button>
    </div>
  );
}

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
                <span role="img" aria-label="AI 助手" className="text-[18px] leading-none">🤖</span>
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
              {/* AI 思考加载态：内容为空时显示"正在思考" + 3 个跳动圆点（demo 规格一致） */}
              {msg.role === 'assistant' && !msg.content && (
                <div className="thinking-loading" role="status" aria-live="polite">
                  <span>正在思考</span>
                  <span className="thinking-dots" aria-hidden="true">
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                  </span>
                </div>
              )}
              {msg.role === 'assistant' ? (
                <MessageContent content={msg.content || '...'} />
              ) : (
                <div className="text-sm whitespace-pre-wrap">{msg.content || '...'}</div>
              )}
              {/* 工具调用状态指示（简单路径补转发工具事件后生效，§6.3/§7；中文名映射） */}
              {msg.role === 'assistant' && msg === messages[messages.length - 1] && currentTool && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-[var(--color-text-tertiary)]">
                  <Loader2 size={12} className="animate-spin" />
                  <span>{TOOL_NAME_MAP[currentTool] ?? currentTool}</span>
                </div>
              )}
              {/* PPT 生成完成下载卡片（tool_file 事件，§7） */}
              {msg.role === 'assistant' && msg === messages[messages.length - 1] && pptFile && (
                <PptDownloadCard file={pptFile} />
              )}
              {/* 用户消息附件渲染（图片缩略图 / 视频播放器，历史回显同样走这里） */}
              {msg.role === 'user' && msg.attachments && msg.attachments.length > 0 && (
                <AttachmentViewer attachments={msg.attachments} />
              )}
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

      {/* 输入区 */}
      <div className="relative flex gap-2">
        {/* 附件上传按钮（📎） */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming}
          className={`flex-shrink-0 px-3 py-2.5 rounded-[var(--radius-md)] border transition-colors ${
            pendingAttachments.length > 0
              ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent-bg)]'
              : 'border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
          } disabled:opacity-50`}
          title="上传图片/视频"
        >
          <Paperclip size={18} />
        </button>
        {/* 隐藏的文件选择器（图片/视频，可多选） */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,video/*"
          multiple
          hidden
          onChange={handleFileSelect}
        />

        {/* 深度思考开关 */}
        <button
          onClick={() => setEnableThinking(!enableThinking)}
          className={`flex-shrink-0 px-3 py-2.5 rounded-[var(--radius-md)] border transition-colors text-xs font-medium ${
            enableThinking
              ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent-bg)]'
              : 'border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
          }`}
          title="深度思考：回答质量更高但响应更慢"
        >
          <Brain size={16} className="inline-block mr-1 align-[-3px]" />
          深度思考
        </button>

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

        {/* PPT 模板按钮（v1.4：与笔记一起选中，生成 PPT 时使用） */}
        <button
          onClick={toggleTemplatePicker}
          className={`flex-shrink-0 px-3 py-2.5 rounded-[var(--radius-md)] border transition-colors ${
            showTemplatePicker || selectedTemplate
              ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent-bg)]'
              : 'border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-bg)] hover:text-[var(--color-accent)]'
          }`}
          title="选择 PPT 模板"
        >
          <Presentation size={18} />
        </button>

        {/* PPT 模板选择面板（单选；懒加载模板列表） */}
        {showTemplatePicker && (
          <div
            ref={templatePickerRef}
            className="absolute bottom-full mb-2 left-0 w-72 max-h-64 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] shadow-lg z-10 flex flex-col"
          >
            <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
              <Presentation size={14} className="text-[var(--color-text-tertiary)]" />
              <span className="flex-1 text-sm text-[var(--color-text)]">选择 PPT 模板</span>
              <button
                onClick={() => setShowTemplatePicker(false)}
                className="text-[var(--color-text-tertiary)] hover:text-[var(--color-text)]"
              >
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {loadingTemplates ? (
                <div className="text-center py-6 text-sm text-[var(--color-text-tertiary)]">加载中...</div>
              ) : templateList.length === 0 ? (
                <div className="text-center py-6 text-sm text-[var(--color-text-tertiary)]">
                  暂无模板，请先在「PPT 模板」页上传
                </div>
              ) : (
                templateList.map((tmpl) => {
                  const isSelected = selectedTemplate?.id === tmpl.id;
                  return (
                    <button
                      key={tmpl.id}
                      onClick={() => toggleTemplate(tmpl)}
                      className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${
                        isSelected
                          ? 'bg-[var(--color-accent-bg)] text-[var(--color-accent)]'
                          : 'text-[var(--color-text)] hover:bg-[var(--color-accent-bg)]'
                      }`}
                    >
                      <Presentation size={14} className="flex-shrink-0" />
                      <span className="truncate">{tmpl.name}</span>
                      {isSelected && <span className="ml-auto text-xs flex-shrink-0">✓</span>}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}

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
                      {normalizeCategory(note.category) && (
                        <span className="ml-auto text-xs text-[var(--color-text-tertiary)] flex-shrink-0">{normalizeCategory(note.category)}</span>
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
            disabled={
              (!input.trim() &&
                pendingAttachments.filter((a) => a.status === 'done' && a.fileId).length === 0) ||
              pendingAttachments.some((a) => a.status === 'uploading')
            }
            className="px-4 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white hover:opacity-90 disabled:opacity-50"
          >
            <Send size={18} />
          </button>
        )}
      </div>

      {/* 附件预览条（输入框下方，发送后清空） */}
      <AttachmentBar items={pendingAttachments} onRemove={removeAttachment} />

      {/* 引用笔记标签（输入框下方） */}
      {selectedNotes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
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

      {/* PPT 模板标签（v1.4，输入框下方） */}
      {selectedTemplate && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-[var(--radius-md)] bg-[var(--color-accent-bg)] text-[var(--color-accent)] border border-[var(--color-accent)]/20">
            <Presentation size={12} />
            <span className="max-w-[160px] truncate">模板：{selectedTemplate.name}</span>
            <button onClick={() => setSelectedTemplate(null)} className="hover:opacity-70">
              <X size={12} />
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
