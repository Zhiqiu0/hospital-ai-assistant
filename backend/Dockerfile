# 走 daocloud 反代避开 docker.io 网络超时（国内服务器无法直连）
FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

# 使用腾讯云镜像源加速（服务器在上海）
RUN sed -i 's/deb.debian.org/mirrors.tencentyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.tencentyun.com/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    p7zip-full \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.tencentyun.com/pypi/simple -r requirements.txt

COPY . .

RUN mkdir -p uploads && chmod +x entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["sh", "entrypoint.sh"]
