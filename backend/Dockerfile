# 走 daocloud 反代避开 docker.io 网络超时（国内服务器无法直连）
FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

# 使用阿里云公网镜像源加速（2026-07-15 迁移：原 mirrors.tencentyun.com 是
# 腾讯云内网源，只在腾讯云机器上可解析，服务器迁到阿里云后构建直接失败。
# 换成公网可达的 mirrors.aliyun.com，在任何机器上构建都能通）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    p7zip-full \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt

COPY . .

RUN mkdir -p uploads && chmod +x entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["sh", "entrypoint.sh"]
