# -*- coding: utf-8 -*-
"""数据库连接池与查询辅助
所有 SQL 操作统一走这里，便于管理与事务控制。
"""
import pymysql
from dbutils.pooled_db import PooledDB

DB_CONFIG = dict(host='127.0.0.1', user='root', password='root',
                 database='xiashou2', charset='utf8mb4', autocommit=True)

_pool = PooledDB(creator=pymysql, mincached=2, maxcached=8, maxconnections=20,
                 blocking=True, **DB_CONFIG)


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
