/**
 * 笔记分类常量
 *
 * 分类语义：
 * - 标准分类：工作 / 学习 / 生活 / 技术
 * - 兜底分类：其他 —— 分类非空且不属于标准分类时（如历史脏数据、AI 创建的任意分类），统一归入
 * - 未分类：分类为空字符串 / null，与"其他"区分
 */

export const NOTE_CATEGORIES = ['工作', '学习', '生活', '技术'] as const;

export const OTHER_CATEGORY = '其他';

/** 分类是否属于标准分类 */
export function isStandardCategory(category: string | null | undefined): boolean {
  return !!category && (NOTE_CATEGORIES as readonly string[]).includes(category);
}

/**
 * 归一化分类：非空且不属于标准分类的任意值统一归为"其他"
 * 返回 null 表示未分类
 */
export function normalizeCategory(category: string | null | undefined): string | null {
  if (!category) return null;
  return isStandardCategory(category) ? category : OTHER_CATEGORY;
}
