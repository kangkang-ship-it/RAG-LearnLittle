/**
 * SSE 流式通信 Hook
 * 
 * 核心功能：
 * 1. 使用原生 fetch + ReadableStream 逐行解析 SSE 事件
 * 2. 支持聊天 SSE（thinking/response/done/error）和知识库 SSE（processing/completed/finish）
 * 3. AbortController 支持取消
 */

import { useRef, useCallback } from 'react';
import type { ChatSSEMessage, KnowledgeSSEMessage, ToolFileInfo } from '../types/api';

/** SSE 回调配置 */
interface SSECallbacks {
  /** 思考过程事件（RAG 管线各阶段） */
  onThinking?: (stage: string, content: string, details?: Record<string, unknown>) => void;
  /** 回答内容 chunk */
  onResponse?: (content: string, sessionId?: string) => void;
  /** 完成事件 */
  onDone?: (sessionId?: string) => void;
  /** 错误事件 */
  onError?: (message: string) => void;
  /** 知识库进度事件 */
  onKnowledgeProgress?: (data: KnowledgeSSEMessage) => void;
  // Plan-and-Execute 事件回调
  onPlanStart?: (goal: string, totalSteps: number) => void;
  onPlanStep?: (step: number, action: string, status: string) => void;
  onPlanStepStart?: (step: number, action: string) => void;
  onPlanStepEnd?: (step: number, result: string) => void;
  onPlanSynthesize?: () => void;
  onPlanComplete?: (totalSteps: number, completedSteps: number) => void;
  onPlanFallback?: (reason: string) => void;
  // 工具调用事件回调
  onToolStart?: (name: string) => void;
  onToolEnd?: (name: string, durationMs?: number) => void;
  /** 工具产出文件事件（PPT 生成完成，含下载信息，§6.3） */
  onToolFile?: (info: ToolFileInfo) => void;
}

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);

  /**
   * 启动 SSE 连接
   * 
   * @param url - 请求 URL
   * @param body - 请求体（POST）
   * @param callbacks - 事件回调
   */
  const start = useCallback(async (
    url: string,
    body: Record<string, unknown>,
    callbacks: SSECallbacks,
  ) => {
    // 取消上一次连接
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const token = localStorage.getItem('jwt_token');

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        callbacks.onError?.(`请求失败: ${response.status}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onError?.('无法读取响应流');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 按行解析 SSE 事件
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // 最后一行可能不完整，保留

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;

          try {
            const data = JSON.parse(line.slice(6)) as ChatSSEMessage & KnowledgeSSEMessage;

            // 知识库 SSE 事件（通过 event_type 字段区分）
            if ('event_type' in data && data.event_type) {
              if (data.event_type === 'processing' || data.event_type === 'completed') {
                callbacks.onKnowledgeProgress?.(data);
              } else if (data.event_type === 'finish') {
                callbacks.onKnowledgeProgress?.(data);
              } else if (data.event_type === 'error') {
                callbacks.onError?.(data.message || '上传失败');
              }
              continue;
            }

            // 聊天 SSE 事件
            switch (data.type) {
              case 'thinking':
                callbacks.onThinking?.(data.stage || '', data.content || '', data.details);
                break;

              case 'response':
                if (data.content) {
                  callbacks.onResponse?.(data.content, data.session_id);
                }
                break;

              case 'done':
                callbacks.onDone?.(data.session_id);
                break;

              case 'error':
                callbacks.onError?.(data.content || '未知错误');
                break;

              // Plan-and-Execute 事件
              case 'plan_start':
                callbacks.onPlanStart?.(data.goal || '', data.total_steps || 0);
                break;

              case 'plan_step':
                callbacks.onPlanStep?.(data.step || 0, data.action || '', data.status || 'pending');
                break;

              case 'plan_step_start':
                callbacks.onPlanStepStart?.(data.step || 0, data.action || '');
                break;

              case 'plan_step_end':
                callbacks.onPlanStepEnd?.(data.step || 0, data.result || '');
                break;

              case 'plan_synthesize':
                callbacks.onPlanSynthesize?.();
                break;

              case 'plan_complete':
                callbacks.onPlanComplete?.(data.total_steps || 0, data.completed_steps || 0);
                break;

              case 'plan_fallback':
                callbacks.onPlanFallback?.(data.reason || '');
                break;

              // 工具调用事件
              case 'tool_start':
                callbacks.onToolStart?.(data.name || '');
                break;

              case 'tool_end':
                callbacks.onToolEnd?.(data.name || '', data.duration_ms);
                break;

              case 'tool_file':
                callbacks.onToolFile?.(data as unknown as ToolFileInfo);
                break;
            }
          } catch {
            // JSON 解析失败，跳过该行
          }
        }
      }

      // 流结束

    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // 用户主动取消，不报错
        return;
      }
      callbacks.onError?.(err instanceof Error ? err.message : '连接失败');
    }
  }, []);

  /**
   * 停止当前 SSE 连接
   */
  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  return { start, stop };
}
