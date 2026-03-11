#!/usr/bin/env python3
"""examples/run_loan_analysis.py

示例：从 MySQL 数据库批量读取贷款单号，并循环调用本地 Agent 执行接口。

用法示例：
  pip install pymysql httpx
    python examples/run_loan_analysis.py \
        --db-host 127.0.0.1 --db-port 3306 --db-user root --db-password secret --db-name loans_db \
        --agent-id risk-agent-001 --api-url http://127.0.0.1:8000/api/v1/agent/execute --max-records 100

说明：
- 该脚本为同步示例，依赖 `pymysql` 和 `httpx`。
- 默认查询表 `t_ent_loan` 的字段 `loannr_chkdgt`。
"""
from __future__ import annotations

import argparse
import time
import uuid
from typing import List
import re

import json
try:
    import tomllib  # Python 3.11+
except Exception:
    tomllib = None
from pathlib import Path

import pymysql
import httpx
import csv
import os


def fetch_loan_numbers(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
    db_type: str = "mysql",
    table: str = "t_ent_loan",
    column: str = "loannr_chkdgt",
    max_records: int | None = None,
) -> List[str]:
    """从数据库中查询贷款单号（loannr_chkdgt）。

    支持：mysql（pymysql）与 opengauss（psycopg2）。
    返回：贷款编号字符串列表。
    """
    # 安全校验：仅允许字母、数字和下划线的表名/列名，避免 SQL 注入风险
    ident_re = re.compile(r"^[A-Za-z0-9_]+$")
    if not ident_re.match(table) or not ident_re.match(column):
        raise ValueError("不安全的表名或列名，允许的字符：字母、数字、下划线")

    sql = f"SELECT {column} FROM {table}"
    if max_records is not None and max_records > 0:
        sql += f" LIMIT {int(max_records)}"

    actual_db = db_name
    if not actual_db:
        raise ValueError("数据库名称未提供，请通过 db_name 参数传入")

    db_type_norm = (db_type or "mysql").lower()
    if db_type_norm in ("mysql", "pymysql"):
        conn = pymysql.connect(host=host, port=port, user=user, password=password, database=actual_db, charset="utf8mb4")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                return [str(row[0]) for row in rows]
        finally:
            conn.close()

    elif db_type_norm in ("opengauss", "psycopg2", "postgres", "postgresql"):
        try:
            import psycopg2
        except Exception as e:
            raise RuntimeError("psycopg2 is required for opengauss support. Install psycopg2-binary or psycopg2.") from e

        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=actual_db)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                return [str(row[0]) for row in rows]
        finally:
            conn.close()

    else:
        raise ValueError(f"Unsupported db_type: {db_type}")


def call_agent_execute(api_url: str, agent_id: str, user_id: str, loan_number: str, timeout: int = 300) -> dict:
    """调用 agent 执行接口并返回 JSON 响应。

    payload 中的 input 字段包含 loan_number 和 text。
    """
    payload = {
        "agent_id": agent_id,
        "user_id": user_id,
        "input": {"role": "inspector", "content": f"{loan_number}"},
        "timeout": timeout,
    }

    with httpx.Client(timeout=timeout + 10) as client:
        r = client.post(api_url, json=payload)
        r.raise_for_status()
        return r.json()


def main() -> None:
    p = argparse.ArgumentParser(description="从 MySQL 批量读取贷款单号并调用 Agent 接口的示例脚本")
    p.add_argument("--db-host", default="127.0.0.1")
    p.add_argument("--db-port", default=3306, type=int)
    p.add_argument("--db-user", default=None, help="数据库用户名")
    p.add_argument("--db-password", default=None, help="数据库密码")
    p.add_argument("--db-name", default=None, help="数据库名")
    p.add_argument("--agent-id", default="risk-agent-001")
    p.add_argument("--user-id", default="example-user")
    p.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1/agent/execute")
    p.add_argument("--max-records", dest="max_records", type=int, default=100, help="最多获取多少条贷款单号，0 表示不限")
    p.add_argument("--delay", type=float, default=0.1, help="每次调用间隔（秒）")
    p.add_argument("--timeout", type=int, default=300, help="agent 执行超时时间（秒）")
    p.add_argument("--out-csv", default="loan_inspect_calls.csv", help="将调用记录追加到的 CSV 文件路径")
    p.add_argument("--config", default="", help="可选：配置文件路径（.toml 或 .json），用于批量提供参数")
    p.add_argument("--db-type", default="mysql", choices=["mysql", "opengauss"], help="数据库类型：mysql 或 opengauss")
    p.add_argument("--sql-table", default="t_ent_loan", help="要查询的表名（仅允许字母数字和下划线）")
    p.add_argument("--sql-column", default="loannr_chkdgt", help="要查询的列名（仅允许字母数字和下划线）")

    args = p.parse_args()

    # 如果没有显式提供 --config，则按顺序在示例脚本目录查找配置文件并默认加载
    if not args.config:
        script_dir = Path(__file__).resolve().parent
        # 搜索顺序：用户配置 -> run_loan_analysis.toml -> run_loan_analysis.json -> example toml
        candidates = [script_dir / "run_loan_analysis.toml", script_dir / "run_loan_analysis.json", script_dir / "run_loan_analysis.example.toml"]
        found = None
        for c in candidates:
            if c.exists():
                found = c
                break
        if found:
            args.config = str(found)
            print(f"加载配置文件: {args.config}")

    # 支持通过配置文件覆盖参数（支持 TOML 或 JSON）
    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            print(f"配置文件不存在: {cfg_path}")
            return
        if cfg_path.suffix.lower() == ".toml":
            if tomllib is None:
                print("当前 Python 不支持 tomllib，请使用 JSON 配置或升级到 Python 3.11+")
                return
            with open(cfg_path, "rb") as f:
                file_cfg = tomllib.load(f)
        elif cfg_path.suffix.lower() == ".json":
            with open(cfg_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
        else:
            print("仅支持 .toml 或 .json 配置文件")
            return

        # 将配置文件中的值写回 args（只覆盖存在的属性）
        for k, v in file_cfg.items():
            if hasattr(args, k) and v is not None:
                setattr(args, k, v)

    max_records = args.max_records if args.max_records and args.max_records > 0 else None

    print(f"Connecting to DB {args.db_host}:{args.db_port} db_name={args.db_name}")

    try:
        loan_iter = fetch_loan_numbers(
            host=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
            db_name=args.db_name,
            db_type=args.db_type,
            table=args.sql_table,
            column=args.sql_column,
            max_records=max_records,
        )
        for i, loan_no in enumerate(loan_iter, start=1):
            print(f"[{i}] Calling agent for loan: {loan_no}")
            try:
                resp = call_agent_execute(args.api_url, args.agent_id, args.user_id, loan_no, timeout=args.timeout)
                print("Response:", resp)

                # 将 agent_id、user_id、loan_no 和 resp 中的 session_id 写入 CSV 文件（追加模式）
                csv_path = args.out_csv
                session_id = None
                try:
                    if isinstance(resp, dict):
                        session_id = resp.get("session_id")
                except Exception:
                    session_id = None

                write_header = not os.path.exists(csv_path)
                try:
                    with open(csv_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        if write_header:
                            writer.writerow(["agent_id", "user_id", "loan_no", "session_id"])
                        writer.writerow([args.agent_id, args.user_id, loan_no, session_id])
                except Exception as e:
                    print(f"Warning: 无法将记录写入 CSV ({csv_path}): {e}")
            except Exception as e:
                print(f"Error calling agent for {loan_no}: {e}")

            if args.delay > 0:
                time.sleep(args.delay)

    except Exception as e:
        print("Fatal error:", e)


if __name__ == "__main__":
    main()
