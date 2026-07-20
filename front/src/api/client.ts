/**
 * Axios 实例配置
 * 
 * 功能：
 * 1. 统一超时、请求头配置
 * 2. 请求拦截：自动注入 JWT Bearer Token
 * 3. 响应拦截：401 自动登出跳转
 */

import axios from 'axios';

/** 创建 Axios 实例 */
const client = axios.create({
  baseURL: '',           // 空 = 相对路径，开发时走 Vite proxy
  timeout: 30000,        // 30 秒超时
  headers: { 'Content-Type': 'application/json' },
});

/**
 * 请求拦截器 — 自动注入 JWT
 * 
 * 从 localStorage 读取 token（与 Zustand persist 双写），
 * 自动添加到 Authorization 请求头。
 */
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('jwt_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * 响应拦截器 — 401 自动登出
 * 
 * 捕获 401 响应，清除本地 token 并跳转到登录页。
 * 其他错误原样抛出，由调用方处理。
 */
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('jwt_token');
      // 避免在登录页重复跳转
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default client;
