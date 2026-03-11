```markdown
# examples
 

- 使用命令行参数（快速测试）

```bash
python examples/run_loan_analysis.py \
  --db-host 127.0.0.1 --db-port 3306 --db-user root --db-password secret --db-name loans_db \
  --db-type mysql \
  --agent-id risk-agent-001 --user-id example-user --api-url http://127.0.0.1:8000/api/v1/agent/execute \
  --max-records 100 --out-csv agent_calls.csv
```

- 使用配置文件（TOML 或 JSON）：

```bash
python examples/run_loan_analysis.py --config examples/run_loan_analysis.example.toml
```

配置和参数说明（常用）：

- `--config <path>`: 指定 TOML 或 JSON 配置文件；当未指定时，脚本会自动在 `examples/` 下查找 `run_loan_analysis.toml` 或 `run_loan_analysis.json`。
- `--db-type`: 数据库类型，支持 `mysql`（使用 `pymysql`）或 `opengauss`（使用 `psycopg2`）。
- `--db-host/--db-port/--db-user/--db-password/--db-name`: 数据库连接信息；这些也可以在配置文件中指定。
- `--sql-table/--sql-column`: 要读取的数据表名与列名（脚本会对白名单校验标识符，仅允许字母/数字/下划线以防注入）。
- `--max-records`: 限制读取的记录数（整数）。设置为 `0` 或不指定表示读取全部（慎用）。
- `--delay`: 每次调用间隔（秒），用于防抖或降低后端压力。
- `--out-csv`: 若指定，脚本会把每次调用结果追加到该 CSV 文件，CSV 包含列 `agent_id,user_id,loan_no,session_id,success,output,error,timestamp`。

其它说明：

- 强烈建议在运行脚本前先启动服务并用小批量（例如 `--max-records 10`）进行调试。
- 若使用 `opengauss`，请确保系统安装了 PostgreSQL 客户端库与头文件（参考 `docs/BUILD_PG_FROM_SOURCE.md`）。

```
# examples

本目录包含一些运行示例脚本，帮助开发者快速上手并复现常见用例。

示例：批量读取贷款单号并调用 Agent
- 文件：`run_loan_analysis.py`
- 功能：从 MySQL 表 `t_ent_loan` 中读取 `loannr_chkdgt` 字段的贷款单号，然后循环调用本地 Agent 执行接口 `/api/v1/agent/execute`，把贷款单号以及要分析的文本作为 `input` 传入。

准备：
1. 安装依赖（示例脚本所需）：
```
pip install pymysql httpx
```
2. 启动本服务（或在另一个终端运行）：
```
./scripts/run_e2e.sh
```

运行示例：
-```
python examples/run_loan_analysis.py \
  --db-host 127.0.0.1 --db-port 3306 --db-user root --db-password secret --db-name loans_db \
  --agent-id risk-agent-001 --api-url http://127.0.0.1:8000/api/v1/agent/execute --max-records 100
```

说明：
- `--max-records` 用于限制获取的贷款单号条数；不指定或设置为 0 则读取全部。
- `--delay` 可用于控制每次调用间隔，避免短时内压垮服务或数据库。
