/**
 * 个人信息页面
 * 
 * 功能：
 * 1. 展示用户基本信息（用户名、邮箱、简介）
 * 2. 头像上传 + 实时预览
 * 3. 编辑个人资料（邮箱、简介）
 */

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Camera, Save, User } from 'lucide-react';
import { userApi } from '../api/user';
import { useUserStore } from '../stores/useUserStore';
import LoadingSkeleton from '../components/common/LoadingSkeleton';
import type { UserInfo } from '../types/api';

export default function Profile() {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const userInfo = useUserStore((s) => s.userInfo);
  const updateUserInfo = useUserStore((s) => s.updateUserInfo);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [email, setEmail] = useState('');
  const [bio, setBio] = useState('');
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);

  /** 加载用户信息 */
  useEffect(() => {
    (async () => {
      try {
        const res = await userApi.getMe();
        const user: UserInfo = res.data.data;
        updateUserInfo(user);
        setEmail(user.email || '');
        setBio(user.bio || '');
        setAvatarUrl(user.avatar);
      } catch {
        toast.error('加载用户信息失败');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  /** 头像文件选择 → 预览 + 上传 */
  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // 前端预览
    const previewUrl = URL.createObjectURL(file);
    setAvatarPreview(previewUrl);

    // 调用后端上传接口
    setUploadingAvatar(true);
    try {
      const res = await userApi.uploadAvatar(file);
      const { avatar_url } = res.data.data;
      setAvatarUrl(avatar_url);
      setAvatarPreview(null);
      updateUserInfo({ avatar: avatar_url });
      toast.success('头像更新成功');
    } catch {
      toast.error('头像上传失败');
      setAvatarPreview(null);
    } finally {
      setUploadingAvatar(false);
      e.target.value = '';
    }
  };

  /** 保存资料修改 */
  const handleSave = async () => {
    setSaving(true);
    try {
      await userApi.updateMe({ email, bio });
      updateUserInfo({ email, bio });
      toast.success('保存成功');
    } catch {
      toast.error(t('common.error'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingSkeleton />;

  /** 显示的头像地址（预览 > 已保存 > 默认） */
  const displayAvatar = avatarPreview || avatarUrl;

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-heading font-bold text-[var(--color-text)] mb-6">
        {t('nav.profile')}
      </h1>

      {/* 头像区域 */}
      <div className="flex items-center gap-6 mb-8 p-6 bg-[var(--color-card)] rounded-[var(--radius-lg)] border border-[var(--color-border)]">
        {/* 头像展示 */}
        <div className="relative group">
          <div className="w-20 h-20 rounded-full overflow-hidden bg-[var(--color-bg)] border-2 border-[var(--color-border)]">
            {displayAvatar ? (
              <img
                src={displayAvatar}
                alt="头像"
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <User size={32} className="text-[var(--color-text-tertiary)]" />
              </div>
            )}
          </div>
          {/* 悬浮上传按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadingAvatar}
            className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
          >
            <Camera size={20} className="text-white" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp"
            onChange={handleAvatarChange}
            className="hidden"
          />
          {uploadingAvatar && (
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-xs text-[var(--color-accent)]">
              上传中...
            </div>
          )}
        </div>

        {/* 用户名（只读） */}
        <div>
          <h2 className="text-lg font-bold text-[var(--color-text)]">{userInfo?.username}</h2>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
            注册于 {userInfo?.created_at ? new Date(userInfo.created_at).toLocaleDateString() : '-'}
          </p>
        </div>
      </div>

      {/* 资料编辑表单 */}
      <div className="space-y-4">
        {/* 邮箱 */}
        <div>
          <label className="block text-sm text-[var(--color-text-secondary)] mb-1">
            {t('auth.email')}
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          />
        </div>

        {/* 个人简介 */}
        <div>
          <label className="block text-sm text-[var(--color-text-secondary)] mb-1">
            个人简介
          </label>
          <textarea
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="写点什么介绍自己..."
            rows={3}
            className="w-full px-3 py-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          />
        </div>

        {/* 保存按钮 */}
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2 rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white text-sm hover:opacity-90 disabled:opacity-50"
        >
          <Save size={16} />
          {saving ? '保存中...' : t('common.save')}
        </button>
      </div>
    </div>
  );
}
