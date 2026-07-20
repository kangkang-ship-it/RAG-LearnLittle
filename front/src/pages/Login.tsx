/**
 * 登录页面
 * 
 * 功能：
 * 1. 用户名 + 密码登录
 * 2. 登录成功后保存 Token 并跳转首页
 * 3. 错误提示（用户名不存在、密码错误、账户锁定）
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { LogIn } from 'lucide-react';
import { authApi } from '../api/auth';
import { userApi } from '../api/user';
import { useUserStore } from '../stores/useUserStore';
import AuthImage from '../components/common/AuthImage';

export default function Login() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const login = useUserStore((s) => s.login);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  /** 提交登录 */
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;

    setLoading(true);
    try {
      // 1. 登录获取 Token
      const res = await authApi.login({ username, password });
      const { access_token, refresh_token } = res.data.data;

      // 2. 先写入 localStorage，供后续请求拦截器读取
      localStorage.setItem('jwt_token', access_token);
      localStorage.setItem('jwt_refresh_token', refresh_token);

      // 3. 获取用户信息（此时拦截器已能读取到 token）
      const userRes = await userApi.getMe();
      const userInfo = userRes.data.data;

      // 4. 保存到 Store（同步 Zustand 状态）
      login(access_token, refresh_token, userInfo);

      toast.success(t('common.success'));
      navigate('/');
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } } };
      toast.error(error.response?.data?.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <AuthImage />
      <h2 className="text-2xl font-heading font-bold text-center text-[var(--color-text)] mb-6">
        {t('auth.login')}
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.username')}
          </label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
            placeholder={t('auth.username')}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1">
            {t('auth.password')}
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
            placeholder={t('auth.password')}
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          <LogIn size={18} />
          {loading ? t('common.loading') : t('auth.login')}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-[var(--color-text-secondary)]">
        {t('auth.noAccount')}{' '}
        <Link to="/register" className="text-[var(--color-accent)] hover:underline">
          {t('auth.register')}
        </Link>
      </p>
    </div>
  );
}
