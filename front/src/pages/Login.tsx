/**
 * 登录页面 - 2.5D 等距微立体风格
 *
 * 功能：
 * 1. 左右分栏布局，左侧 2.5D 等距插画，右侧登录卡片
 * 2. 用户名 + 密码 + 验证码登录
 * 3. 登录成功后保存 Token 并跳转首页
 * 4. 密码显隐切换、记住账号（仅保存用户名，明文密码严禁落盘）
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  User, Lock, Check, QrCode,
  ChevronDown
} from 'lucide-react';
import { authApi } from '../api/auth';
import { userApi } from '../api/user';
import { useUserStore } from '../stores/useUserStore';
import { GeometricBackground, IllustrationScene } from '../components/common/IllustrationScene';

/* ─────────────────────────────────────────────
   验证码 Canvas 生成
───────────────────────────────────────────── */
function generateCaptcha(canvas: HTMLCanvasElement): string {
  const ctx = canvas.getContext('2d');
  if (!ctx) return '';
  const w = canvas.width;
  const h = canvas.height;

  const grad = ctx.createLinearGradient(0, 0, w, h);
  grad.addColorStop(0, '#eef4ff');
  grad.addColorStop(1, '#e0eaff');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  for (let i = 0; i < 4; i++) {
    ctx.strokeStyle = `rgba(22,119,255,${0.15 + Math.random() * 0.15})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.random() * w, Math.random() * h);
    ctx.bezierCurveTo(Math.random() * w, Math.random() * h, Math.random() * w, Math.random() * h, Math.random() * w, Math.random() * h);
    ctx.stroke();
  }

  for (let i = 0; i < 30; i++) {
    ctx.fillStyle = `rgba(22,119,255,${0.2 + Math.random() * 0.3})`;
    ctx.beginPath();
    ctx.arc(Math.random() * w, Math.random() * h, 1, 0, Math.PI * 2);
    ctx.fill();
  }

  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
  let code = '';
  const fontSize = 22;
  ctx.font = `bold ${fontSize}px 'Courier New', monospace`;
  ctx.textBaseline = 'middle';
  for (let i = 0; i < 4; i++) {
    const ch = chars[Math.floor(Math.random() * chars.length)];
    code += ch;
    ctx.save();
    const x = 14 + i * 24;
    const y = h / 2;
    ctx.translate(x, y);
    ctx.rotate((Math.random() - 0.5) * 0.5);
    ctx.fillStyle = `hsl(${210 + Math.random() * 30}, 80%, ${35 + Math.random() * 15}%)`;
    ctx.fillText(ch, 0, 0);
    ctx.restore();
  }
  return code;
}

/* ─────────────────────────────────────────────
   自定义方形复选框
───────────────────────────────────────────── */
function SquareCheckbox({ checked, onChange, label }: {
  checked: boolean; onChange: () => void; label: string;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none text-gray-600 text-sm" onClick={onChange}>
      <div className="relative" style={{ width: 18, height: 18 }}>
        <div style={{
          width: 18, height: 18, borderRadius: 4,
          border: checked ? 'none' : '1.5px solid #c0c8d4',
          background: checked ? '#1677ff' : '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'all 0.2s',
          boxShadow: checked ? '0 2px 6px rgba(22,119,255,0.3)' : 'none',
        }}>
          {checked && <Check size={12} color="#fff" strokeWidth={3} />}
        </div>
      </div>
      <span>{label}</span>
    </label>
  );
}

/* ─────────────────────────────────────────────
   登录页面主组件
───────────────────────────────────────────── */
export default function Login() {
  const navigate = useNavigate();
  const login = useUserStore((s) => s.login);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [captchaInput, setCaptchaInput] = useState('');
  const [rememberPwd, setRememberPwd] = useState(true);
  const [loading, setLoading] = useState(false);

  const captchaCanvasRef = useRef<HTMLCanvasElement>(null);
  const captchaCodeRef = useRef<string>('');

  const refreshCaptcha = useCallback(() => {
    const canvas = captchaCanvasRef.current;
    if (!canvas) return;
    const code = generateCaptcha(canvas);
    captchaCodeRef.current = code;
  }, []);

  useEffect(() => {
    refreshCaptcha();
  }, [refreshCaptcha]);

  // 记住账号：页面加载时恢复保存的用户名（安全审查 P0-6：明文密码严禁落盘，
  // 故此处只恢复用户名，不恢复密码；自动登录需后端签发一次性 remember-me 票据后才可支持）
  useEffect(() => {
    const saved = localStorage.getItem('remembered_login');
    if (saved) {
      try {
        const { username: u } = JSON.parse(saved);
        setUsername(u || '');
        setRememberPwd(true);
      } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    if (!localStorage.getItem('device_id')) {
      const id = crypto.randomUUID?.() || `dev_${Date.now()}_${Math.random().toString(36).slice(2)}`;
      localStorage.setItem('device_id', id);
    }
  }, []);

  const getDeviceName = (): string => {
    const ua = navigator.userAgent;
    let browser = 'Unknown';
    if (ua.includes('Firefox')) browser = 'Firefox';
    else if (ua.includes('Edg')) browser = 'Edge';
    else if (ua.includes('Chrome')) browser = 'Chrome';
    else if (ua.includes('Safari')) browser = 'Safari';
    let os = 'Unknown';
    if (ua.includes('Windows')) os = 'Windows';
    else if (ua.includes('Mac')) os = 'macOS';
    else if (ua.includes('Linux')) os = 'Linux';
    else if (ua.includes('Android')) os = 'Android';
    else if (ua.includes('iOS') || ua.includes('iPhone') || ua.includes('iPad')) os = 'iOS';
    return `${browser} on ${os}`;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;

    // 验证码校验（不区分大小写）
    if (!captchaInput || captchaInput.toLowerCase() !== captchaCodeRef.current.toLowerCase()) {
      toast.error('验证码错误');
      refreshCaptcha();
      setCaptchaInput('');
      return;
    }

    // 记住账号：仅保存用户名（安全审查 P0-6，明文密码不落盘）
    if (rememberPwd) {
      localStorage.setItem('remembered_login', JSON.stringify({ username }));
    } else {
      localStorage.removeItem('remembered_login');
    }

    setLoading(true);
    try {
      const deviceId = localStorage.getItem('device_id') || undefined;
      const deviceName = getDeviceName();

      const res = await authApi.login({ username, password, device_id: deviceId, device_name: deviceName });
      const { access_token, refresh_token } = res.data.data;

      localStorage.setItem('jwt_token', access_token);
      localStorage.setItem('jwt_refresh_token', refresh_token);

      const userRes = await userApi.getMe();
      const userInfo = userRes.data.data;

      login(access_token, refresh_token, userInfo, deviceId);

      toast.success('登录成功');
      navigate('/');
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } } };
      toast.error(error.response?.data?.message || '登录失败');
      refreshCaptcha();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #f0f6ff 0%, #e8f0fe 30%, #f5f9ff 60%, #dce8ff 100%)' }}>

      {/* 微动效关键帧 */}
      <style>{`
        @keyframes robotFloat {
          0%, 100% { transform: translateX(-50%) translateY(0); }
          50% { transform: translateX(-50%) translateY(-6px); }
        }
        @keyframes iconFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .robot-float { animation: none !important; }
          .icon-fade { animation: none !important; }
        }
      `}</style>

      {/* 2.5D 几何背景块面 */}
      <GeometricBackground />

      {/* ── 左侧：插画区（约60%） ── */}
      <div className="hidden lg:flex items-center justify-center" style={{ width: '60%', minWidth: 480, position: 'relative', zIndex: 2 }}>
        <IllustrationScene />
      </div>

      {/* ── 右侧：登录卡片 ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-8" style={{ position: 'relative', zIndex: 2 }}>
        <div className="w-full max-w-[380px]">
          {/* 卡片容器 - 大圆角 */}
          <div style={{
            background: '#ffffff',
            borderRadius: 24,
            padding: '40px 36px 36px',
            boxShadow: '0 12px 48px rgba(22,119,255,0.1), 0 4px 12px rgba(0,0,0,0.04)',
          }}>

            {/* 主标题 - 云尚笔记 */}
            <h2 className="text-center font-semibold mb-4" style={{ fontSize: 28, color: '#1a2a4a' }}>云尚</h2>

            {/* 次级标题行 - 账号登录 */}
            <div className="flex items-center justify-between mb-8">
              <h1 className="text-xl font-semibold text-gray-700">账号登录</h1>
              <button type="button" className="text-gray-400 hover:text-[#1677ff] transition-colors"
                title="扫码登录">
                <QrCode size={22} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {/* 账号 */}
              <div className="relative">
                <User size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入账号"
                  className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                  required
                />
              </div>

              {/* 密码 */}
              <div className="relative">
                <Lock size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full pl-10 pr-10 py-2.5 text-sm text-gray-800
                    placeholder:text-gray-400 outline-none transition-all duration-200
                    hover:border-[#c8d0da]
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                    active:scale-[0.99]"
                  style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                  required
                />
                <button type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors">
                  <ChevronDown size={16} />
                </button>
              </div>

              {/* 验证码 */}
              <div className="flex gap-3">
                <div className="relative flex-1">
                  <Check size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#1677ff]" />
                  <input
                    type="text"
                    value={captchaInput}
                    onChange={(e) => setCaptchaInput(e.target.value)}
                    placeholder="请输入验证码"
                    maxLength={4}
                    className="w-full pl-10 pr-4 py-2.5 text-sm text-gray-800
                      placeholder:text-gray-400 outline-none transition-all duration-200
                      hover:border-[#c8d0da]
                      focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]
                      active:scale-[0.99]"
                    style={{ borderRadius: 12, border: '1px solid #e0e4ea' }}
                    required
                  />
                </div>
                <canvas
                  ref={captchaCanvasRef}
                  width={110}
                  height={40}
                  onClick={refreshCaptcha}
                  className="cursor-pointer hover:opacity-80 transition-opacity flex-shrink-0"
                  style={{ width: 110, height: 40, borderRadius: 12, border: '1px solid #e8ecf0' }}
                  title="点击刷新验证码"
                />
              </div>

              {/* 选项栏 */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <SquareCheckbox checked={rememberPwd} onChange={() => setRememberPwd(!rememberPwd)} label="记住账号" />
                </div>
                <button type="button" className="text-[#1677ff] hover:text-blue-700 transition-colors text-sm">
                  忘记密码？
                </button>
              </div>

              {/* 登录按钮 - 胶囊型 */}
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 text-white font-medium text-sm
                  bg-[#1677ff] hover:bg-[#0d5bd6] active:bg-[#0a4db8] active:scale-[0.98]
                  disabled:opacity-50 transition-all duration-200
                  shadow-[0_4px_14px_rgba(22,119,255,0.3)] hover:shadow-[0_6px_22px_rgba(22,119,255,0.4)]"
                style={{ borderRadius: 999 }}
              >
                {loading ? '登录中...' : '登录'}
              </button>
            </form>

            {/* 底部注册入口 */}
            <div className="mt-6">
              <div className="relative flex items-center gap-3 mb-4">
                <div className="flex-1 h-px bg-gray-200" />
                <span className="text-xs text-gray-400">或</span>
                <div className="flex-1 h-px bg-gray-200" />
              </div>
              <Link
                to="/register"
                className="block w-full py-2.5 text-center text-sm font-medium
                  text-[#1677ff] bg-blue-50 hover:bg-blue-100
                  rounded-xl border border-blue-100 hover:border-blue-200
                  transition-all duration-200"
              >
                没有账号？立即注册
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
