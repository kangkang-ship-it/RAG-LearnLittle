/**
 * 注册页面
 * 
 * 功能：
 * 1. 用户名 + 密码 + 邮箱注册
 * 2. 前端校验密码一致性
 * 3. 注册成功后跳转登录页
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { UserPlus } from 'lucide-react';
import { authApi } from '../api/auth';
import AuthImage from '../components/common/AuthImage';

export default function Register() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);

  /** 提交注册 */
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    // 前端校验
    if (password !== confirmPassword) {
      toast.error('两次输入的密码不一致');
      return;
    }

    setLoading(true);
    try {
      await authApi.register({
        username,
        password,
        email: email || undefined,
      });

      toast.success('注册成功，请登录');
      navigate('/login');
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } } };
      toast.error(error.response?.data?.message || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <AuthImage />
      <h2 className="text-2xl font-heading font-bold text-center text-[var(--color-text)] mb-6">
        {t('auth.register')}
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.username')} *
          </label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
            minLength={3}
            maxLength={50}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.email')}
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.password')} *
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
            minLength={8}
            required
          />
          <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">密码需8位以上，且必须同时包含字母和数字</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.confirmPassword')} *
          </label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
            required
          />
          <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">密码需8位以上，且必须同时包含字母和数字</p>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          <UserPlus size={18} />
          {loading ? t('common.loading') : t('auth.register')}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-[var(--color-text-secondary)]">
        {t('auth.hasAccount')}{' '}
        <Link to="/login" className="text-[var(--color-accent)] hover:underline">
          {t('auth.login')}
        </Link>
      </p>
    </div>
  );
}
