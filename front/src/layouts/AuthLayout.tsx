/**
 * 认证页面布局
 * 
 * Login / Register: 均为左右分栏全页布局（组件自行管理）
 */

import { Outlet } from 'react-router-dom';

export default function AuthLayout() {
  return <Outlet />;
}
