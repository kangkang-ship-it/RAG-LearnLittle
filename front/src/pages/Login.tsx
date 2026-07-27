/**
 * 登录页面 - 3D立体几何风格
 *
 * 功能：
 * 1. 统一3D立体几何台面背景，左侧插画，右侧登录卡片
 * 2. 用户名 + 密码 + 验证码登录
 * 3. 登录成功后保存 Token 并跳转首页
 * 4. 密码显隐切换、记住密码、自动登录
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  User, Lock, Check, QrCode, Shield, Camera, Folder,
  Monitor, Cloud, Globe, ChevronRight, ChevronDown
} from 'lucide-react';
import { authApi } from '../api/auth';
import { userApi } from '../api/user';
import { useUserStore } from '../stores/useUserStore';

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
   3D 立体几何背景块面
───────────────────────────────────────────── */
function GeometricBackground() {
  const blocks = [
    { w: 260, h: 160, top: '2%', left: '5%', rot: 8, color: 'rgba(220,235,255,0.6)', r: 20 },
    { w: 180, h: 120, top: '60%', left: '2%', rot: -5, color: 'rgba(200,225,255,0.45)', r: 16 },
    { w: 140, h: 200, top: '8%', left: '30%', rot: -10, color: 'rgba(255,255,255,0.7)', r: 18 },
    { w: 200, h: 90, top: '70%', left: '25%', rot: 12, color: 'rgba(210,230,255,0.5)', r: 14 },
    { w: 100, h: 100, top: '35%', left: '15%', rot: 20, color: 'rgba(255,255,255,0.55)', r: 12 },
    { w: 300, h: 130, top: '15%', right: '8%', rot: -6, color: 'rgba(230,242,255,0.5)', r: 22 },
    { w: 160, h: 180, top: '50%', right: '5%', rot: 10, color: 'rgba(255,255,255,0.6)', r: 16 },
    { w: 120, h: 80, bottom: '8%', right: '20%', rot: -8, color: 'rgba(215,232,255,0.4)', r: 12 },
    { w: 80, h: 140, top: '40%', left: '45%', rot: 15, color: 'rgba(240,248,255,0.5)', r: 10 },
    { w: 220, h: 70, bottom: '20%', left: '40%', rot: -3, color: 'rgba(225,240,255,0.35)', r: 14 },
  ];

  return (
    <>
      {blocks.map((b, i) => (
        <div key={i} className="absolute" style={{
          width: b.w, height: b.h,
          top: b.top, left: b.left, right: b.right, bottom: b.bottom,
          transform: `rotate(${b.rot}deg)`,
          background: b.color,
          borderRadius: b.r,
          boxShadow: '0 4px 24px rgba(22,119,255,0.06), 0 1px 4px rgba(0,0,0,0.03)',
        }} />
      ))}
    </>
  );
}

/* ─────────────────────────────────────────────
   3D 卡通 Q 版机器人
───────────────────────────────────────────── */
function Robot3D() {
  return (
    <div className="relative" style={{ width: 140, height: 175, filter: 'drop-shadow(0 12px 24px rgba(22,119,255,0.2))' }}>
      {/* 头部 - 白色圆润 */}
      <div className="absolute" style={{
        width: 104, height: 90, borderRadius: '52px 52px 38px 38px',
        background: 'linear-gradient(160deg, #ffffff 0%, #f5f8ff 40%, #e0ecfa 100%)',
        left: '50%', top: 4, transform: 'translateX(-50%)',
        boxShadow: '0 10px 30px rgba(22,119,255,0.15), inset 0 3px 6px rgba(255,255,255,0.9), inset 0 -5px 10px rgba(0,0,0,0.04)',
      }}>
        {/* 顶部高光 */}
        <div className="absolute" style={{ width: 40, height: 18, borderRadius: '50%', background: 'rgba(255,255,255,0.7)', top: 5, left: 14, filter: 'blur(4px)' }} />
        {/* 蓝色发光面罩 */}
        <div className="absolute" style={{
          width: 80, height: 44, borderRadius: 24,
          background: 'linear-gradient(180deg, #1a3a6b 0%, #0d2240 100%)',
          left: '50%', top: 24, transform: 'translateX(-50%)',
          boxShadow: 'inset 0 3px 10px rgba(0,0,0,0.5), 0 0 16px rgba(22,119,255,0.15)',
        }}>
          {/* 左眼 - 蓝色发光 */}
          <div className="absolute" style={{
            width: 18, height: 18, borderRadius: '50%',
            background: 'radial-gradient(circle at 40% 35%, #a0e8ff 0%, #4fc3f7 45%, #2196f3 100%)',
            left: 14, top: 13,
            boxShadow: '0 0 14px rgba(79,195,247,0.95), 0 0 28px rgba(79,195,247,0.35)',
          }}>
            <div className="absolute" style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff', top: 3, left: 4 }} />
          </div>
          {/* 右眼 - 蓝色发光 */}
          <div className="absolute" style={{
            width: 18, height: 18, borderRadius: '50%',
            background: 'radial-gradient(circle at 40% 35%, #a0e8ff 0%, #4fc3f7 45%, #2196f3 100%)',
            right: 14, top: 13,
            boxShadow: '0 0 14px rgba(79,195,247,0.95), 0 0 28px rgba(79,195,247,0.35)',
          }}>
            <div className="absolute" style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff', top: 3, left: 4 }} />
          </div>
        </div>
      </div>

      {/* 左耳 */}
      <div className="absolute" style={{
        width: 20, height: 30, borderRadius: 10,
        background: 'linear-gradient(150deg, #5ba3f5 0%, #1677ff 50%, #0d5bd6 100%)',
        left: -2, top: 30,
        boxShadow: '0 4px 10px rgba(22,119,255,0.4), inset 0 1px 3px rgba(255,255,255,0.25)',
      }} />
      {/* 右耳 */}
      <div className="absolute" style={{
        width: 20, height: 30, borderRadius: 10,
        background: 'linear-gradient(150deg, #5ba3f5 0%, #1677ff 50%, #0d5bd6 100%)',
        right: -2, top: 30,
        boxShadow: '0 4px 10px rgba(22,119,255,0.4), inset 0 1px 3px rgba(255,255,255,0.25)',
      }} />

      {/* 头顶天线 */}
      <div className="absolute" style={{ left: '50%', top: -12, transform: 'translateX(-50%)' }}>
        <div style={{ width: 3, height: 12, background: 'linear-gradient(180deg, #c0ddf5, #8ab8e8)', margin: '0 auto', borderRadius: 1.5 }} />
        <div style={{
          width: 26, height: 8, borderRadius: 4,
          background: 'linear-gradient(90deg, #69b4ff 0%, #1677ff 50%, #69b4ff 100%)',
          boxShadow: '0 0 12px rgba(22,119,255,0.7), 0 0 4px rgba(22,119,255,0.4)',
          marginTop: -1, marginLeft: -11.5,
        }} />
      </div>

      {/* 身体 - 白色圆润 */}
      <div className="absolute" style={{
        width: 82, height: 58, borderRadius: '28px 28px 22px 22px',
        background: 'linear-gradient(160deg, #ffffff 0%, #f0f5ff 40%, #dce8f8 100%)',
        left: '50%', top: 96, transform: 'translateX(-50%)',
        boxShadow: '0 10px 24px rgba(22,119,255,0.12), inset 0 3px 6px rgba(255,255,255,0.8), inset 0 -4px 8px rgba(0,0,0,0.04)',
      }}>
        {/* 身体高光 */}
        <div className="absolute" style={{ width: 28, height: 12, borderRadius: '50%', background: 'rgba(255,255,255,0.6)', top: 4, left: 16, filter: 'blur(3px)' }} />
        {/* 胸部蓝色指示灯 */}
        <div className="absolute" style={{
          width: 22, height: 22, borderRadius: '50%',
          background: 'radial-gradient(circle at 38% 38%, #a0e8ff 0%, #4fc3f7 40%, #1677ff 100%)',
          left: '50%', top: 14, transform: 'translateX(-50%)',
          boxShadow: '0 0 16px rgba(22,119,255,0.55)',
        }} />
        {/* 装饰线 */}
        <div className="absolute" style={{ width: 42, height: 2, borderRadius: 1, background: 'linear-gradient(90deg, transparent, #c0d8f0, transparent)', left: '50%', bottom: 10, transform: 'translateX(-50%)' }} />
      </div>

      {/* 左手 */}
      <div className="absolute" style={{
        width: 20, height: 20, borderRadius: '50%',
        background: 'linear-gradient(150deg, #ffffff, #d8e8f8)',
        left: 4, top: 114,
        boxShadow: '0 4px 10px rgba(22,119,255,0.12), inset 0 1px 3px rgba(255,255,255,0.7)',
      }} />
      {/* 右手 */}
      <div className="absolute" style={{
        width: 20, height: 20, borderRadius: '50%',
        background: 'linear-gradient(150deg, #ffffff, #d8e8f8)',
        right: 4, top: 114,
        boxShadow: '0 4px 10px rgba(22,119,255,0.12), inset 0 1px 3px rgba(255,255,255,0.7)',
      }} />
    </div>
  );
}

/* ─────────────────────────────────────────────
   3D 立体同心圆平台
───────────────────────────────────────────── */
function Platform3D() {
  return (
    <div className="relative" style={{ width: 260, height: 80 }}>
      {/* 第三层（最底、最大） */}
      <div className="absolute" style={{ left: '50%', top: 40, transform: 'translateX(-50%)' }}>
        <div style={{ width: 260, height: 16, borderRadius: '0 0 130px 130px', background: 'linear-gradient(180deg, #a0c0e5 0%, #88aed0 100%)' }} />
        <div style={{ width: 260, height: 52, borderRadius: '50%', background: 'linear-gradient(180deg, #c8dffa 0%, #b0d0f2 100%)', marginTop: -8, boxShadow: '0 8px 20px rgba(22,119,255,0.1)' }} />
      </div>
      {/* 第二层 */}
      <div className="absolute" style={{ left: '50%', top: 22, transform: 'translateX(-50%)' }}>
        <div style={{ width: 200, height: 14, borderRadius: '0 0 100px 100px', background: 'linear-gradient(180deg, #7ea3d4 0%, #6b93c6 100%)' }} />
        <div style={{ width: 200, height: 42, borderRadius: '50%', background: 'linear-gradient(180deg, #a8c8f5 0%, #92b8e8 100%)', marginTop: -7, boxShadow: '0 6px 14px rgba(22,119,255,0.13)' }} />
      </div>
      {/* 第一层（最上、最小） */}
      <div className="absolute" style={{ left: '50%', top: 0, transform: 'translateX(-50%)' }}>
        <div style={{ width: 150, height: 12, borderRadius: '0 0 75px 75px', background: 'linear-gradient(180deg, #4a8ed4 0%, #1677ff 100%)' }} />
        <div style={{
          width: 150, height: 34, borderRadius: '50%',
          background: 'linear-gradient(135deg, #93c5fd 0%, #5b9ee0 40%, #1677ff 100%)',
          marginTop: -6,
          boxShadow: '0 6px 28px rgba(22,119,255,0.35), inset 0 -2px 8px rgba(0,0,0,0.1)',
          position: 'relative',
        }}>
          <div className="absolute" style={{ width: 90, height: 18, borderRadius: '50%', border: '1.5px solid rgba(255,255,255,0.3)', left: '50%', top: '50%', transform: 'translate(-50%,-50%)' }} />
          <div className="absolute" style={{ width: 56, height: 12, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.2)', left: '50%', top: '50%', transform: 'translate(-50%,-50%)' }} />
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   3D 环绕图标节点（白色底座）
───────────────────────────────────────────── */
function IconNode3D({ icon, style }: { icon: React.ReactNode; style: React.CSSProperties }) {
  return (
    <div className="absolute" style={{ zIndex: 8, ...style }}>
      {/* 底座侧面 */}
      <div style={{
        width: 56, height: 16, borderRadius: '0 0 28px 28px',
        background: 'linear-gradient(180deg, #90b5d8 0%, #7ea3c8 100%)',
        marginTop: 46,
      }} />
      {/* 底座顶面 */}
      <div style={{
        width: 56, height: 56, borderRadius: '50%',
        background: 'linear-gradient(150deg, #ffffff 0%, #eaf2ff 100%)',
        boxShadow: '0 6px 18px rgba(22,119,255,0.14), 0 2px 6px rgba(0,0,0,0.06)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginTop: -51,
      }}>
        {/* 内圈 */}
        <div style={{
          width: 44, height: 44, borderRadius: '50%',
          background: 'linear-gradient(145deg, #ffffff 0%, #f0f6ff 100%)',
          boxShadow: 'inset 0 1px 4px rgba(22,119,255,0.08), 0 1px 3px rgba(255,255,255,0.9)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#1677ff',
        }}>
          {icon}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   插画场景（机器人 + 平台 + 图标 + 连接线）
───────────────────────────────────────────── */
function IllustrationScene() {
  const iconPositions = [
    { x: 60, y: 100 },   // 左上
    { x: 320, y: 100 },  // 右上
    { x: 25, y: 230 },   // 左中
    { x: 355, y: 230 },  // 右中
    { x: 60, y: 355 },   // 左下
    { x: 320, y: 355 },  // 右下
  ];
  const centerX = 190;
  const centerY = 220;

  return (
    <div className="relative" style={{ width: 400, height: 440 }}>
      {/* SVG 发光连接线 */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 1 }}>
        <defs>
          <linearGradient id="lineGlow" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#1677ff" stopOpacity="0.15" />
            <stop offset="50%" stopColor="#1677ff" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#1677ff" stopOpacity="0.15" />
          </linearGradient>
        </defs>
        {iconPositions.map((pos, i) => (
          <line key={i} x1={centerX} y1={centerY} x2={pos.x + 28} y2={pos.y + 28}
            stroke="url(#lineGlow)" strokeWidth="2" strokeDasharray="8 5" />
        ))}
        {/* 环形连线 */}
        {iconPositions.map((pos, i) => {
          const next = iconPositions[(i + 1) % iconPositions.length];
          return (
            <line key={`ring-${i}`}
              x1={pos.x + 28} y1={pos.y + 28}
              x2={next.x + 28} y2={next.y + 28}
              stroke="url(#lineGlow)" strokeWidth="1.5" opacity="0.6" />
          );
        })}
      </svg>

      {/* 机器人 */}
      <div className="absolute" style={{ left: '50%', top: 100, transform: 'translateX(-50%)', zIndex: 10 }}>
        <Robot3D />
      </div>

      {/* 平台 */}
      <div className="absolute" style={{ left: '50%', top: 260, transform: 'translateX(-50%)', zIndex: 5 }}>
        <Platform3D />
      </div>

      {/* 6 个环绕图标 */}
      <IconNode3D icon={<Folder size={20} />} style={{ left: iconPositions[0].x, top: iconPositions[0].y }} />
      <IconNode3D icon={<Shield size={20} />} style={{ left: iconPositions[1].x, top: iconPositions[1].y }} />
      <IconNode3D icon={<Camera size={20} />} style={{ left: iconPositions[2].x, top: iconPositions[2].y }} />
      <IconNode3D icon={<Cloud size={20} />} style={{ left: iconPositions[3].x, top: iconPositions[3].y }} />
      <IconNode3D icon={<Monitor size={20} />} style={{ left: iconPositions[4].x, top: iconPositions[4].y }} />
      <IconNode3D icon={<Globe size={20} />} style={{ left: iconPositions[5].x, top: iconPositions[5].y }} />
    </div>
  );
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
  const [autoLogin, setAutoLogin] = useState(false);
  const [loading, setLoading] = useState(false);

  const captchaCanvasRef = useRef<HTMLCanvasElement>(null);

  const refreshCaptcha = useCallback(() => {
    const canvas = captchaCanvasRef.current;
    if (!canvas) return;
    generateCaptcha(canvas);
  }, []);

  useEffect(() => {
    refreshCaptcha();
  }, [refreshCaptcha]);

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

      {/* 3D 几何背景块面 */}
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
            padding: '40px 36px',
            boxShadow: '0 12px 48px rgba(22,119,255,0.1), 0 4px 12px rgba(0,0,0,0.04)',
          }}>

            {/* 主标题 - 云上笔记 */}
            <h2 className="text-center font-semibold mb-4" style={{ fontSize: 28, color: '#1a2a4a' }}>云上笔记</h2>

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
                    placeholder:text-gray-400 outline-none transition-all
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]"
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
                    placeholder:text-gray-400 outline-none transition-all
                    focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]"
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
                      placeholder:text-gray-400 outline-none transition-all
                      focus:border-[#1677ff] focus:shadow-[0_0_0_3px_rgba(22,119,255,0.08)]"
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
                  <SquareCheckbox checked={rememberPwd} onChange={() => setRememberPwd(!rememberPwd)} label="记住密码" />
                  <SquareCheckbox checked={autoLogin} onChange={() => setAutoLogin(!autoLogin)} label="自动登录" />
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
                  bg-[#1677ff] hover:bg-[#0d5bd6] active:bg-[#0a4db8]
                  disabled:opacity-50 transition-all
                  shadow-[0_4px_14px_rgba(22,119,255,0.3)] hover:shadow-[0_6px_22px_rgba(22,119,255,0.4)]"
                style={{ borderRadius: 999 }}
              >
                {loading ? '登录中...' : '登录'}
              </button>
            </form>

            {/* 底部注册入口 */}
            <p className="mt-6 text-center text-sm text-gray-500">
              没有账号{' '}
              <Link to="/register" className="text-[#1677ff] hover:text-blue-700 font-medium inline-flex items-center gap-0.5 transition-colors">
                立即注册 <ChevronRight size={14} />
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
