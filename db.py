# -*- coding: utf-8 -*-
"""数据库连接池与查询辅助
所有 SQL 操作统一走这里，便于管理与事务控制。

配置通过环境变量注入，本地开发可用 .env 文件或默认值。
"""
import os
import pymysql
from dbutils.pooled_db import PooledDB

# ---- 本地开发 SSL 补丁（Linux 服务器无需，但保留无副作用）----
import ssl as _ssl
_orig_ctx = _ssl.create_default_context
def _safe_create_default_context(*a, **kw):
    try:
        return _orig_ctx(*a, **kw)
    except _ssl.SSLError:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx
_ssl.create_default_context = _safe_create_default_context

# ---- 数据库配置（环境变量 > 默认值）----
DB_CONFIG = dict(
    host=os.getenv('DB_HOST', '127.0.0.1'),
    port=int(os.getenv('DB_PORT', 3306)),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', 'root'),
    database=os.getenv('DB_DATABASE', 'xiashou2'),
    charset='utf8mb4',
    autocommit=True,
)

_pool = PooledDB(
    creator=pymysql,
    mincached=int(os.getenv('DB_POOL_MIN', '4')),
    maxcached=int(os.getenv('DB_POOL_MAX', '20')),
    maxconnections=int(os.getenv('DB_POOL_MAX_CONN', '50')),
    blocking=True,
    ping=1,  # 连接使用前自动检测是否断开
    **DB_CONFIG
)


def get_conn():
    """从连接池获取一个连接（用完需 close，实际是归还池）"""
    return _pool.connection()


def query_all(sql, args=None):
    with get_conn() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, args or ())
            return list(cur.fetchall())


def query_one(sql, args=None):
    with get_conn() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, args or ())
            return cur.fetchone()


def execute(sql, args=None):
    """执行写操作，返回 lastrowid 或 affected_rows"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            n = cur.execute(sql, args or ())
            return cur.lastrowid if cur.lastrowid else n


def executemany(sql, seq_args):
    with get_conn() as conn:
        with conn.cursor() as cur:
            return cur.executemany(sql, seq_args)
