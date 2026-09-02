from pathlib import Path
import pandas as pd

# CSV 中文字段到数据库字段的唯一映射。
COLUMN_MAP = {
    "任务ID": "task_id",
    "客户号": "customer_id",
    "账号类型": "account_type",
    "资金账号": "account_id",
    "算法类型": "algo_type",
    "交易日期": "trade_date",
    "买入类型": "buy_type",
    "证券代码": "stock_code",
    "证券名称": "stock_name",
    "交易结果": "trade_result",
    "交易进度": "trade_progress",
    "授权持仓量": "authorized_position",
    "实际底仓": "actual_position",
    "总买量": "buy_volume",
    "总买金额": "buy_amount",
    "买入均价": "buy_price",
    "总卖量": "sell_volume",
    "总卖金额": "sell_amount",
    "卖出均价": "sell_price",
    "今日交易额": "turnover",
    "实际底仓的市值": "market_value",
    "当日盈亏金额": "profit",
    "日收益率%": "return_rate",
    "母单状态": "order_status",
    "是否GRT": "is_grt",
}


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """将原始 CSV 字段映射为数据库字段并完成基础类型清洗。"""

    df = df.rename(columns=COLUMN_MAP)
    required = set(COLUMN_MAP.values())
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"CSV 缺少字段：{missing}")

    df["trade_date"] = pd.to_datetime(
        df["trade_date"], errors="raise"
    ).dt.strftime("%Y-%m-%d")

    numeric_cols = [
        "trade_progress", "authorized_position", "actual_position",
        "buy_volume", "buy_amount", "buy_price", "sell_volume",
        "sell_amount", "sell_price", "turnover", "market_value",
        "profit", "return_rate",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["is_grt"] = (
        df["is_grt"].astype(str).str.upper()
        .map({"是": 1, "否": 0, "Y": 1, "N": 0, "TRUE": 1, "FALSE": 0})
        .fillna(0).astype(int)
    )
    df = df.dropna(subset=["task_id"])
    return df.apply(lambda series: series.str.lstrip("'") if series.dtype == "object" else series)

# 项目目录
BASE_DIR = Path(__file__).parent

# SQLite数据库
DB_PATH = BASE_DIR / "trade.db"

# CSV目录
DATA_DIR = BASE_DIR / "data"

# 日志目录
LOG_DIR = BASE_DIR / "log"

# 每次批量插入数量
CHUNK_SIZE = 5000

category_cols = [
            "账号类型",
            "算法类型",
            "买入类型",
            "交易结果",
            "母单状态",
            "是否GRT"
        ]

datetime_cols = [
            "交易日期"
        ]

amount_cols = [
            "总买金额",
            "总卖金额",
            "今日交易额",
            "实际底仓的市值",
            "当日盈亏金额"
        ]

quantity_cols = [
            "授权持仓量",
            "实际底仓",
            "总买量",
            "总卖量"
        ]

price_cols = [
            "买入均价",
            "卖出均价"
        ]

ratio_cols = [
            "交易进度",
            "日收益率%"
        ]

# ==========================================================
# 字段约束
# (min, max)
# None 表示无限制
# ==========================================================

numeric_constraints = {

    # 比例
    "交易进度": (0, 1),

    # 数量
    "授权持仓量": (0, None),
    "实际底仓": (0, None),
    "总买量": (0, None),
    "总卖量": (0, None),

    # 金额
    "总买金额": (0, None),
    "总卖金额": (0, None),
    "今日交易额": (0, None),
    "实际底仓的市值": (0, None),

    # 价格
    "买入均价": (0, None),
    "卖出均价": (0, None),

    # 盈亏允许负数
    "当日盈亏金额": (None, None),

    # 收益率暂不限制
    "日收益率%": (None, None),
}

# ==========================================================
# Trade Record 分组配置
# ==========================================================

# 主要规模分组：实际底仓市值
MARKET_VALUE_GROUPS = [
    {
        "name": "mv_01_very_low",
        "min": None,
        "max": 15680,
    },
    {
        "name": "mv_02_low",
        "min": 15680,
        "max": 43980,
    },
    {
        "name": "mv_03_medium",
        "min": 43980,
        "max": 124000,
    },
    {
        "name": "mv_04_high",
        "min": 124000,
        "max": 617814,
    },
    {
        "name": "mv_05_very_high",
        "min": 617814,
        "max": 2268281,
    },
    {
        "name": "mv_06_extreme",
        "min": 2268281,
        "max": None,
    },
]


# 辅助规模分组：实际底仓
ACTUAL_POSITION_GROUPS = [
    {
        "name": "pos_01_very_low",
        "min": None,
        "max": 1000,
    },
    {
        "name": "pos_02_low",
        "min": 1000,
        "max": 3100,
    },
    {
        "name": "pos_03_medium",
        "min": 3100,
        "max": 10200,
    },
    {
        "name": "pos_04_high",
        "min": 10200,
        "max": 71000,
    },
    {
        "name": "pos_05_very_high",
        "min": 71000,
        "max": 300000,
    },
    {
        "name": "pos_06_extreme",
        "min": 300000,
        "max": None,
    },
]


# ==========================================================
# StockDB 个股行情分组配置
# 区间统一为 min <= x < max
# total_mv 单位：元；turnover/amplitude/pct_chg 单位：百分比点
# ==========================================================

STOCK_TOTAL_MV_GROUPS = [
    {"name": "stock_mv_01_micro", "min": None, "max": 5_000_000_000},
    {"name": "stock_mv_02_small", "min": 5_000_000_000, "max": 20_000_000_000},
    {"name": "stock_mv_03_medium", "min": 20_000_000_000, "max": 100_000_000_000},
    {"name": "stock_mv_04_large", "min": 100_000_000_000, "max": None},
]

STOCK_TURNOVER_GROUPS = [
    {"name": "turnover_01_very_low", "min": None, "max": 1},
    {"name": "turnover_02_low", "min": 1, "max": 3},
    {"name": "turnover_03_medium", "min": 3, "max": 7},
    {"name": "turnover_04_high", "min": 7, "max": None},
]

STOCK_AMPLITUDE_GROUPS = [
    {"name": "amplitude_01_low", "min": None, "max": 3},
    {"name": "amplitude_02_medium", "min": 3, "max": 5},
    {"name": "amplitude_03_high", "min": 5, "max": 8},
    {"name": "amplitude_04_extreme", "min": 8, "max": None},
]

STOCK_RETURN_STATE_GROUPS = [
    {"name": "return_01_strong_down", "min": None, "max": -5},
    {"name": "return_02_down", "min": -5, "max": -1},
    {"name": "return_03_flat", "min": -1, "max": 1},
    {"name": "return_04_up", "min": 1, "max": 5},
    {"name": "return_05_strong_up", "min": 5, "max": None},
]


# ==========================================================
# 市场整体行情分组配置
# 区间统一为 min <= x < max，四个原始指标单位均为百分点
# ==========================================================

MARKET_RETURN_GROUPS = [
    {"name": "market_return_01_strong_down", "min": None, "max": -1.5},
    {"name": "market_return_02_down", "min": -1.5, "max": -0.3},
    {"name": "market_return_03_flat", "min": -0.3, "max": 0.3},
    {"name": "market_return_04_up", "min": 0.3, "max": 1.5},
    {"name": "market_return_05_strong_up", "min": 1.5, "max": None},
]

MARKET_VOLATILITY_GROUPS = [
    {"name": "market_volatility_01_low", "min": None, "max": 20},
    {"name": "market_volatility_02_medium", "min": 20, "max": 25},
    {"name": "market_volatility_03_high", "min": 25, "max": 30},
    {"name": "market_volatility_04_extreme", "min": 30, "max": None},
]

MARKET_BREADTH_GROUPS = [
    {"name": "market_breadth_01_very_weak", "min": None, "max": -50},
    {"name": "market_breadth_02_weak", "min": -50, "max": -15},
    {"name": "market_breadth_03_neutral", "min": -15, "max": 15},
    {"name": "market_breadth_04_strong", "min": 15, "max": 50},
    {"name": "market_breadth_05_very_strong", "min": 50, "max": None},
]

MARKET_TREND_GROUPS = [
    {"name": "market_trend_01_strong_down", "min": None, "max": -3},
    {"name": "market_trend_02_down", "min": -3, "max": -1},
    {"name": "market_trend_03_neutral", "min": -1, "max": 1},
    {"name": "market_trend_04_up", "min": 1, "max": 3},
    {"name": "market_trend_05_strong_up", "min": 3, "max": None},
]


# ==========================================================
# Prepare 默认过滤条件
# ==========================================================

PREPARE_CONFIG = {

    # 只分析已经平仓的订单
    "required_trade_result": "已平",

    # 只分析实际发生交易的订单
    "min_trade_progress": 0,

    # 无法进行规模分组的数据是否删除
    "drop_unclassified": True,

    # 默认主要分组
    "primary_group": "market_value_group",

    # 辅助分组
    "secondary_group": "actual_position_group",
}
