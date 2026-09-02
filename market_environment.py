"""获取并保存个股行情及按交易日唯一的市场整体环境数据。"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from stock_sdk import rd

from schema import DB_PATH, LOG_DIR, PREPARE_CONFIG


SINA_INDEX_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/"
    "var%20_data=/CN_MarketDataService.getKLineData"
)
BENCHMARK_SYMBOL = "sh000300"
BENCHMARK_NAME = "沪深300"

STOCK_MARKET_COLUMNS = [
    "stock_open", "stock_high", "stock_low", "stock_close", "stock_volume",
    "stock_amount", "stock_pct_chg", "stock_amplitude", "stock_turnover",
    "stock_pre_close", "stock_total_mv", "stock_float_mv", "stock_pe_ttm",
    "stock_pb", "stock_is_st", "stock_vol_ratio",
]


def configure_logging():
    Path(LOG_DIR).mkdir(exist_ok=True)
    log_path = Path(LOG_DIR) / f"market_environment_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return log_path


def stockdb_code(stock_code):
    code = str(stock_code).strip()
    if "." in code:
        code = code.split(".", 1)[0]
    return code.zfill(6)


def load_market_scope():
    """读取 Prepare 会使用的交易日期和证券范围。"""

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT trade_date, stock_code, trade_result, trade_progress
            FROM trade_record
            """,
            conn,
        )
    finally:
        conn.close()
    if df.empty:
        raise RuntimeError("trade_record 为空，请先运行 import")
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["trade_progress"] = pd.to_numeric(df["trade_progress"], errors="coerce")
    df = df[
        (df["trade_result"] == PREPARE_CONFIG["required_trade_result"])
        & (df["trade_progress"] > PREPARE_CONFIG["min_trade_progress"])
    ].dropna(subset=["trade_date", "stock_code"])
    if df.empty:
        raise RuntimeError("trade_record 经 Prepare 默认条件过滤后为空")
    return df[["trade_date", "stock_code"]].drop_duplicates()


def fetch_stock_market_data(scope_df):
    """从 StockDB 获取样本证券行情，并包含首日 lag1 所需预热区间。"""

    project_codes = sorted(scope_df["stock_code"].astype(str).unique())
    code_map = {stockdb_code(code): code for code in project_codes}
    start = (scope_df["trade_date"].min() - timedelta(days=10)).strftime("%Y%m%d")
    end = scope_df["trade_date"].max().strftime("%Y%m%d")
    rows = []
    codes = sorted(code_map)
    for offset in range(0, len(codes), 500):
        batch = codes[offset:offset + 500]
        logging.info("读取 StockDB 批次 %d/%d：%d 只", offset // 500 + 1, (len(codes) + 499) // 500, len(batch))
        data = rd.get_data(batch, start=start, end=end, frequency="1d", fq=None)
        if not isinstance(data, dict):
            logging.warning("StockDB 批次返回类型异常：%s", type(data))
            continue
        for raw_code, records in data.items():
            project_code = code_map.get(str(raw_code))
            if project_code is None:
                continue
            for record in records:
                record = dict(record)
                rows.append({
                    "trade_date": pd.to_datetime(str(record.get("date")), format="%Y%m%d", errors="coerce"),
                    "stock_code": project_code,
                    **{
                        column: record.get(column[len("stock_"):])
                        for column in STOCK_MARKET_COLUMNS
                    },
                })
    if not rows:
        raise RuntimeError("StockDB 未返回任何行情数据")
    result = pd.DataFrame(rows).dropna(subset=["trade_date", "stock_code"])
    return result.drop_duplicates(["trade_date", "stock_code"], keep="last")


def save_stock_market_data(df):
    conn = sqlite3.connect(DB_PATH)
    try:
        saved = df.copy()
        saved["trade_date"] = pd.to_datetime(saved["trade_date"]).dt.strftime("%Y-%m-%d")
        saved.to_sql("stock_market_data", conn, if_exists="replace", index=False)
        conn.execute(
            "CREATE UNIQUE INDEX idx_stock_market_data_key "
            "ON stock_market_data(trade_date, stock_code)"
        )
        conn.commit()
    finally:
        conn.close()


def parse_sina_index_data(text):
    """解析新浪指数日线 JSONP。"""

    marker = re.search(r"var\s+_data\s*=", text)
    array_start = text.find("[", marker.end()) if marker else -1
    array_end = text.rfind("]")
    if array_start < 0 or array_end < array_start:
        raise ValueError("无法从指数接口返回内容中找到 _data 数组")

    data = json.loads(text[array_start:array_end + 1])
    if not isinstance(data, list):
        raise ValueError("指数接口解析结果不是 list")

    required = ["day", "open", "high", "low", "close", "volume"]
    result = pd.DataFrame(data)
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise ValueError(f"指数接口缺少字段：{missing}")

    result = result.rename(columns={"day": "trade_date"})
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    return (
        result[["trade_date", "open", "high", "low", "close", "volume"]]
        .dropna(subset=["trade_date", "close"])
        .drop_duplicates("trade_date", keep="last")
        .sort_values("trade_date")
        .reset_index(drop=True)
    )


def fetch_benchmark_data(start_date, end_date, datalen=200):
    """获取含预热期的沪深300日线数据。"""

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    request_start = start - pd.Timedelta(days=60)

    response = requests.get(
        SINA_INDEX_URL,
        params={
            "symbol": BENCHMARK_SYMBOL,
            "scale": "240",
            "ma": "5",
            "datalen": str(datalen),
        },
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    response.encoding = "gbk"

    result = parse_sina_index_data(response.text)
    result = result[
        (result["trade_date"] >= request_start)
        & (result["trade_date"] <= end)
    ].copy()
    if result.empty:
        raise ValueError(f"沪深300无指定范围数据：{request_start.date()} ~ {end.date()}")
    return result


def calculate_market_environment(index_df, stock_df, trade_dates):
    """计算收益、20日年化波动率、市场宽度和20日趋势。"""

    index_df = index_df.copy().sort_values("trade_date")
    index_df["market_return"] = index_df["close"].pct_change() * 100
    index_df["market_volatility"] = (
        index_df["market_return"].rolling(20, min_periods=20).std() * (252 ** 0.5)
    )
    moving_average = index_df["close"].rolling(20, min_periods=20).mean()
    index_df["market_trend"] = (index_df["close"] / moving_average - 1) * 100

    stocks = stock_df[["trade_date", "stock_code", "stock_pct_chg"]].copy()
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"], errors="coerce")
    stocks["stock_pct_chg"] = pd.to_numeric(stocks["stock_pct_chg"], errors="coerce")
    stocks = stocks.dropna(subset=["trade_date", "stock_code", "stock_pct_chg"])
    stocks = stocks.drop_duplicates(["trade_date", "stock_code"], keep="last")

    breadth = stocks.groupby("trade_date")["stock_pct_chg"].agg(
        breadth_valid_count="count",
        breadth_up_count=lambda values: int((values > 0).sum()),
        breadth_down_count=lambda values: int((values < 0).sum()),
        breadth_flat_count=lambda values: int((values == 0).sum()),
    ).reset_index()
    breadth["market_breadth"] = (
        (breadth["breadth_up_count"] - breadth["breadth_down_count"])
        / breadth["breadth_valid_count"]
        * 100
    )

    environment = index_df.rename(columns={
        "open": "benchmark_open",
        "high": "benchmark_high",
        "low": "benchmark_low",
        "close": "benchmark_close",
        "volume": "benchmark_volume",
    }).merge(breadth, on="trade_date", how="left")
    wanted_dates = pd.to_datetime(pd.Series(trade_dates).dropna().unique())
    environment = environment[environment["trade_date"].isin(wanted_dates)].copy()
    environment["benchmark_symbol"] = BENCHMARK_SYMBOL
    environment["benchmark_name"] = BENCHMARK_NAME
    environment["data_source"] = "sina+stockdb"

    columns = [
        "trade_date", "benchmark_symbol", "benchmark_name",
        "benchmark_open", "benchmark_high", "benchmark_low", "benchmark_close",
        "benchmark_volume", "market_return", "market_volatility",
        "market_breadth", "market_trend", "breadth_valid_count",
        "breadth_up_count", "breadth_down_count", "breadth_flat_count", "data_source",
    ]
    return environment[columns].sort_values("trade_date").reset_index(drop=True)


def validate_market_environment(df, expected_dates=None):
    """在落表前执行完整性和基本数值约束检查。"""

    required = {
        "trade_date", "market_return", "market_volatility",
        "market_breadth", "market_trend",
    }
    missing_columns = required - set(df.columns)
    if missing_columns:
        raise ValueError(f"market_environment 缺少字段：{sorted(missing_columns)}")
    if df.empty:
        raise ValueError("market_environment 为空")
    if df["trade_date"].duplicated().any():
        raise ValueError("market_environment 存在重复交易日")

    if expected_dates is not None:
        expected = set(pd.to_datetime(pd.Series(expected_dates).dropna()).dt.normalize())
        actual = set(pd.to_datetime(df["trade_date"]).dt.normalize())
        missing_dates = sorted(expected - actual)
        if missing_dates:
            raise ValueError(f"market_environment 缺少交易日：{missing_dates}")

    core = ["market_return", "market_volatility", "market_breadth", "market_trend"]
    if df[core].isna().any().any():
        raise ValueError(f"market_environment 核心字段存在缺失：{df[core].isna().sum().to_dict()}")
    if not df["market_breadth"].between(-100, 100).all():
        raise ValueError("market_breadth 超出 [-100, 100]")
    if (df["market_volatility"] < 0).any():
        raise ValueError("market_volatility 存在负数")


def save_market_environment(df):
    """全量替换 market_environment，并建立日期唯一索引。"""

    conn = sqlite3.connect(DB_PATH)
    try:
        df.to_sql("market_environment", conn, if_exists="replace", index=False)
        conn.execute(
            "CREATE UNIQUE INDEX idx_market_environment_date "
            "ON market_environment(trade_date)"
        )
        conn.commit()
    finally:
        conn.close()


def build_market_environment(stock_df, trade_dates):
    """拉取指数、计算市场指标、验证并保存，返回最终表。"""

    dates = pd.to_datetime(pd.Series(trade_dates).dropna())
    index_df = fetch_benchmark_data(dates.min(), dates.max())
    environment = calculate_market_environment(index_df, stock_df, dates)
    validate_market_environment(environment, dates)
    save_market_environment(environment)
    return environment


def run_market_environment():
    """完整更新个股行情表和市场环境表。"""

    scope = load_market_scope()
    stock_df = fetch_stock_market_data(scope)
    save_stock_market_data(stock_df)

    trade_dates = pd.DatetimeIndex(scope["trade_date"].unique()).sort_values()
    market_dates = pd.DatetimeIndex(stock_df["trade_date"].unique()).sort_values()
    required_dates = set(trade_dates)
    for trade_date in trade_dates:
        previous = market_dates[market_dates < trade_date]
        if len(previous):
            required_dates.add(previous[-1])
    environment = build_market_environment(stock_df, sorted(required_dates))
    logging.info(
        "市场数据更新完成：stock_market_data=%d 行，market_environment=%d 行",
        len(stock_df), len(environment),
    )
    return stock_df, environment


if __name__ == "__main__":
    configure_logging()
    run_market_environment()
