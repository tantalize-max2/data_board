FROM python:3.11-slim

WORKDIR /app

# 替换为阿里云镜像源（解决国内 apt-get 卡住问题）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# 系统依赖（单层安装，减少镜像体积）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev pkg-config curl \
    && rm -rf /var/lib/apt/lists/*

# Python依赖（先清理不可见字符再安装，使用阿里云 PyPI 源）
COPY requirements.txt .
RUN python -c "import re;c=open('requirements.txt',encoding='utf-8').read();open('requirements.txt','w',encoding='utf-8').write(re.sub(r'[\u200b-\u200f\ufeff]','',c))" \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 应用代码
COPY db.py server.py ./
COPY static/ ./static/

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/roles || exit 1

# uvicorn: 4 workers 适配多核，proxy-header 信任 nginx 转发的头
CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
