# 走 daocloud 反代避开 docker.io 网络超时（国内服务器无法直连）
# tag@digest 双写（2026-08-29 第八轮审计），升级版本时同步更新 digest
FROM docker.m.daocloud.io/library/node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS builder

WORKDIR /app

COPY package*.json ./
# 用 npm install 而不是 npm ci：esbuild 跨平台 optional dependencies
# 在 Linux runner 上用 npm ci 会报 EBADPLATFORM；npm install 能正确
# 跳过非当前平台的 optional dep（如 netbsd-arm64/win32-x64 等）
RUN npm install --no-audit --no-fund --registry=https://registry.npmmirror.com

# Sentry 前端 DSN / 环境标识 / release，由 docker-compose 的 build.args 传入
# Vite 是 build-time 替换 import.meta.env.VITE_*，所以必须在 npm run build 之前
# 以 ENV 暴露给 build 进程。未传 = 空字符串 = sentry.ts 内部直接跳过初始化（零侵入）。
ARG VITE_SENTRY_DSN=""
ARG VITE_SENTRY_ENVIRONMENT=""
ARG VITE_SENTRY_RELEASE=""
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ENV VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT
ENV VITE_SENTRY_RELEASE=$VITE_SENTRY_RELEASE

COPY . .
RUN npm run build

# --- 生产镜像 ---
FROM docker.m.daocloud.io/library/nginx:alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
