FROM node:20-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --registry=https://mirrors.tencentyun.com/npm/

COPY . .
RUN npm run build

# --- 生产镜像 ---
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
