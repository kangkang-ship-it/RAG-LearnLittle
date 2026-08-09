# ========== RAG LearnLittle 前端镜像（构建 + nginx 托管） ==========
# 构建: docker build -t raglearn-front ./front

# ---- 阶段 1: 构建 ----
FROM node:22-alpine AS build

WORKDIR /app

# 利用 lock 文件缓存依赖层
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# build = tsc 类型检查 + vite build（类型错误会在构建期暴露）
RUN npm run build

# ---- 阶段 2: nginx 托管 ----
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
