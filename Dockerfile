FROM python:3.11-slim

# 设置代理参数（仅构建时使用）
ARG http_proxy
ARG https_proxy
ARG no_proxy

# 临时设置代理环境变量用于构建
ENV http_proxy=$http_proxy
ENV https_proxy=$https_proxy
ENV no_proxy=$no_proxy

# 复制证书安装脚本
COPY abcert /tmp/abcert

# 安装证书和系统依赖
RUN chmod +x /tmp/abcert && \
    /tmp/abcert install && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libssl-dev \
    libffi-dev \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /tmp/abcert

WORKDIR /workspace

# Build dependencies (only used in builder stage)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      python3-dev \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

ENV PYTHONPATH=/workspace
ENV PYTHONUNBUFFERED=1

CMD ["python", "run.py"]

