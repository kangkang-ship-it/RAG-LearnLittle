/**
 * 注册页面 - 2.5D 等距微立体风格（与登录页统一）
 *
 * 功能：
 * 1. 左右分栏布局，左侧 2.5D 等距插画，注册卡片
 * 2. 用户名 + 邮箱 + 密码 + 确认密码注册
 * 3. 前端校验密码一致性
 * 4. 注册成功后跳转登录页
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { User, Mail, Lock } from 'lucide-react';
import { authApi } from '../api/auth';
import { GeometricBackground, IllustrationScene } from '../components/common/IllustrationScene';

export default function Register() {
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
    if (password.length < 8) {
      toast.error('密码至少 8 位');
      return;
    }
    if (!/[a-zA-Z]/.test(password) || !/\d/.test(password)) {
      toast.error('密码需同时包含字母和数字');
      return;
    }
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
    <div className="min-h-screen flex relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #f0f6ff 0%, #e8f0fe 30%, #f5f9ff 60%, #dce8ff 100%)' }}>

      {/* 微动效关键帧 */}
      <style>{`
        @keyframes iconFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
      `}</style>

      {/* 2.5D 几何背景块面 */}
      <GeometricBackground />

      {/* ── 左侧：插画区（约60%） ── */}
      <div className="hidden lg:flex items-center justify-center" style={{ width: '60%', minWidth: 480, position: 'relative', zIndex: 2 }}>
        <IllustrationScene />
      </div>

      {/* ── 右侧：注册卡片 ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-8" style={{ position: 'relative', zIndex: 2 }}>
        <div className="w-full max-w-[380px]">
          {/* 卡片容器 - 大圆角 */}
          <div style={{
            background: '#ffffff',
            borderRadius: 24,
            padding: '40px 36px 36px',
            boxShadow: '0 12px 48px rgba(22,119,255,0.1), 0 4px 12px rgba(0,0,0,0.04)',
          }}>

            {/* 主标题 - 云上笔记 */}
            <h2 className="text-center font-semibold mb-4" style={{ fontSize: 28, color: '#1a2a4a' }}>云上笔记</h2>

            {/* 次级标题行 - 创建账号 */}
            <div className="flex items-center justify-between mb-8">
              <h1 className="text-xl font-semibold text-gray-700">创建账号</h1>
              <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center">
                <User size={16} className="text-[#1677ff]" />
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {/* 用户名 */}
              <div className="relative">
                <User size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                  minLength={3}
                  maxLength={50}
                  required
                />
              </div>

              {/* 邮箱 */}
              <div className="relative">
                <Mail size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="请输入邮箱（选填）"
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                />
              </div>

              {/* 密码 */}
              <div className="relative">
                <Lock size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                  minLength={8}
                  required
                />
                <p className="mt-1 text-xs text-gray-400 pl-1">密码需8位以上，且必须同时包含字母和数字</p>
              </div>

              {/* 确认密码 */}
              <div className="relative">
                <Lock size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="请再次输入密码"
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                  required
                />
              </div>

              {/* 注册按钮 - 胶囊型 */}
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 text-white font-medium text-sm
                  bg-[#1677ff] hover:bg-[#0d5bd6] active:bg-[#0a4db8] active:scale-[0.98]
                  disabled:opacity-50 transition-all duration-200
                  shadow-[0_4px_14px_rgba(22,119,255,0.3)] hover:shadow-[0_6px_22px_rgba(22,119,255,0.4)]"
                style={{ borderRadius: 999 }}
              >
                {loading ? '注册中...' : '注册'}
              </button>
            </form>

            {/* 底部登录入口 */}
            <div className="mt-6">
              <div className="relative flex items-center gap-3 mb-4">
                <div className="flex-1 h-px bg-gray-200" />
                <span className="text-xs text-gray-400">或</span>
                <div className="flex-1 h-px bg-gray-200" />
              </div>
              <Link
                to="/login"
                className="block w-full py-2.5 text-center text-sm font-medium
                  text-[#1677ff] bg-blue-50 hover:bg-blue-100
                  rounded-xl border border-blue-100 hover:border-blue-200
                  transition-all duration-200"
              >
                已有账号？立即登录
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
