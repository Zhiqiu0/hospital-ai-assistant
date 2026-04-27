# 走 daocloud 反代避开 docker.io 网络超时（国内服务器无法直连）
FROM docker.m.daocloud.io/library/node:20-slim AS builder

WORKDIR /app

COPY package*.json ./
# 用 npm install 而不是 npm ci：esbuild 跨平台 optional dependencies
# 在 Linux runner 上用 npm ci 会报 EBADPLATFORM；npm install 能正确
# 跳过非当前平台的 optional dep（如 netbsd-arm64/win32-x64 等）
RUN npm install --no-audit --no-fund --registry=https://mirrors.tencentyun.com/npm/

COPY . .
RUN npm run build

# --- 生产镜像 ---
FROM docker.m.daocloud.io/library/nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
