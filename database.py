import sqlite3
from pathlib import Path

import pandas as pd

from schema import COLUMN_MAP, DATA_DIR, DB_PATH, clean_dataframe


INSERT_TRADE_SQL = """
INSERT OR IGNORE INTO trade_record (
    task_id, customer_id, account_type, account_id,
    algo_type, trade_date, buy_type, stock_code,
    stock_name, trade_result, trade_progress,
    authorized_position, actual_position,
    buy_volume, buy_amount, buy_price,
    sell_volume, sell_amount, sell_price,
    turnover, market_value, profit,
    return_rate, order_status, is_grt
)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def create_table():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_record(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        task_id TEXT,

        customer_id TEXT,

        account_type TEXT,

        account_id TEXT,

        algo_type TEXT,

        trade_date DATE,

        buy_type TEXT,

        stock_code TEXT,

        stock_name TEXT,

        trade_result TEXT,

        trade_progress REAL,

        authorized_position INTEGER,

        actual_position INTEGER,

        buy_volume INTEGER,

        buy_amount REAL,

        buy_price REAL,

        sell_volume INTEGER,

        sell_amount REAL,

        sell_price REAL,

        turnover REAL,

        market_value REAL,

        profit REAL,

        return_rate REAL,

        order_status TEXT,

        is_grt INTEGER,

        UNIQUE (
            task_id,
            account_id,
            trade_date,
            stock_code,
            buy_type,
            trade_progress,
            order_status
        )
    )
    """)

    conn.commit()
    conn.close()


def create_index():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_date ON trade_record(trade_date)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer ON trade_record(customer_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_account ON trade_record(account_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_algo ON trade_record(algo_type)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock ON trade_record(stock_code)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_date_algo ON trade_record(trade_date,algo_type)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_date_stock ON trade_record(trade_date,stock_code)"
    )

    conn.commit()
    conn.close()


def initialize_database():
    """创建交易表及其索引。"""

    create_table()
    create_index()


def read_csv_auto(csv_path):
    """按项目常见编码读取 CSV，初始统一保留为字符串。"""

    for encoding in ("gb18030", "gbk", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(
                csv_path,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文件编码：{csv_path}")


def import_one_csv(csv_path):
    """将一个 CSV 增量写入 trade_record，返回实际插入行数。"""

    df = clean_dataframe(read_csv_auto(csv_path))
    # clean_dataframe 已完成字段映射；按固定字段顺序写入数据库。
    records = list(df[list(COLUMN_MAP.values())].itertuples(index=False, name=None))

    conn = get_connection()
    try:
        before = conn.total_changes
        conn.executemany(INSERT_TRADE_SQL, records)
        conn.commit()
        inserted = conn.total_changes - before
    finally:
        conn.close()

    print(f"{Path(csv_path).name}: CSV={len(records)} 插入={inserted}")
    return inserted


def import_all(data_dir=DATA_DIR):
    """增量导入目录根层的全部 CSV，返回总插入行数。"""

    total = 0
    for csv_file in sorted(Path(data_dir).glob("*.csv")):
        total += import_one_csv(csv_file)
    return total
