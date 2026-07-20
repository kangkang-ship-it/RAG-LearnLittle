/**
 * 防抖 Hook
 * 
 * 用于搜索输入等场景，延迟指定时间后才执行回调，
 * 避免频繁触发 API 请求。
 * 
 * @param value - 需要防抖的值
 * @param delay - 延迟毫秒数（默认 300ms）
 * @returns 防抖后的值
 */

import { useState, useEffect } from 'react';

export function useDebounce<T>(value: T, delay: number = 300): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}
