"""算法层面的环境控制、Benchmark 比较、共同股票覆盖与显著性检验。"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from schema import DB_PATH


REPORT_DIR = Path("report")
LOG_DIR = Path("log")
REPORT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

RUN_TIME = datetime.now()
REPORT_PATH = REPORT_DIR / f"analysis_algo_{RUN_TIME:%Y%m%d_%H%M%S}.json"
STOCK_OVERLAP_REPORT_PATH = (
    REPORT_DIR / f"analysis_algo_stock_overlap_{RUN_TIME:%Y%m%d_%H%M%S}.json"
)
LOG_PATH = LOG_DIR / f"analysis_algo_{RUN_TIME:%Y%m%d_%H%M%S}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)

BENCHMARKS = {
    "benchmark_a": {
        "name": "持仓规模环境",
        "group_cols": ["trade_date", "market_value_group", "actual_position_group"],
    },
    "benchmark_b": {
        "name": "同日同证券",
        "group_cols": ["trade_date", "stock_code"],
    },
    "benchmark_c": {
        "name": "个股行情特征环境",
        "group_cols": [
            "trade_date", "security_type", "stock_total_mv_group",
            "stock_turnover_group", "stock_amplitude_group", "stock_return_state",
        ],
    },
    "benchmark_d": {
        "name": "市场整体行情环境",
        "group_cols": [
            "market_return_group", "market_volatility_group",
            "market_breadth_group", "market_trend_group", "security_type",
        ],
    },
}

# 主要收益指标必须按交易额加权。未加权平均收益率仅保留为分布诊断，
# 不参与算法排名、显著性结论或“最佳算法”判断。
PRIMARY_METRICS = ["win_rate", "profit_capture_ratio", "turnover_weighted_return_rate"]
MIN_ALGO_RECORDS = 30
MIN_COMMON_UNITS = 5
PERMUTATIONS = 10_000
BOOTSTRAPS = 5_000
RANDOM_SEED = 20260817
TOP_STOCK_SIGNIFICANCE_GROUPS = 10
MIN_COMMON_RECORD_RATIO = 0.50


def load_data():
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("SELECT * FROM analysis_record", conn)
    finally:
        conn.close()

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for column in ["profit", "return_rate", "turnover"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def calculate_metrics(df):
    profit = pd.to_numeric(df["profit"], errors="coerce").dropna()
    returns = pd.to_numeric(df["return_rate"], errors="coerce").dropna()
    turnover = pd.to_numeric(df["turnover"], errors="coerce").dropna()
    win_profit = float(profit[profit > 0].sum())
    loss_profit_abs = float(-profit[profit < 0].sum())
    profit_pool = win_profit + loss_profit_abs
    total_turnover = float(turnover.sum())
    weighted_valid = df["return_rate"].notna() & df["turnover"].notna() & df["turnover"].gt(0)
    weighted_return = (
        np.average(df.loc[weighted_valid, "return_rate"], weights=df.loc[weighted_valid, "turnover"])
        if weighted_valid.any() else None
    )

    return {
        "record_count": int(len(df)),
        "valid_profit_count": int(len(profit)),
        "trade_date_count": int(df["trade_date"].nunique()),
        "stock_count": int(df["stock_code"].nunique()),
        "account_count": int(df["account_id"].nunique()),
        "total_profit": float(profit.sum()),
        "total_win_profit": win_profit,
        "total_loss_profit_abs": loss_profit_abs,
        "total_turnover": total_turnover,
        "win_rate": float((profit > 0).mean()) if len(profit) else None,
        "profit_capture_ratio": float(win_profit / profit_pool) if profit_pool > 0 else None,
        "average_return_rate_unweighted": float(returns.mean()) if len(returns) else None,
        "turnover_weighted_return_rate": float(weighted_return) if weighted_return is not None else None,
        "median_return_rate": float(returns.median()) if len(returns) else None,
        "profit_per_turnover_bps": (
            float(profit.sum() / total_turnover * 10_000) if total_turnover > 0 else None
        ),
    }


def aggregate_units(df, group_cols):
    """生成显著性检验所需的环境×日期×算法聚合单元。"""
    unit_cols = list(group_cols)
    if "trade_date" not in unit_cols:
        unit_cols = ["trade_date", *unit_cols]

    work = df.copy()
    work["win"] = (work["profit"] > 0).astype(float)
    work["win_profit"] = work["profit"].clip(lower=0)
    work["loss_profit_abs"] = -work["profit"].clip(upper=0)
    work["return_turnover_product"] = work["return_rate"] * work["turnover"]

    units = work.groupby([*unit_cols, "algo_type"], dropna=False).agg(
        record_count=("profit", "size"),
        win_count=("win", "sum"),
        win_rate=("win", "mean"),
        win_profit=("win_profit", "sum"),
        loss_profit_abs=("loss_profit_abs", "sum"),
        return_sum=("return_rate", "sum"),
        return_turnover_product=("return_turnover_product", "sum"),
        total_profit=("profit", "sum"),
        total_turnover=("turnover", "sum"),
    ).reset_index()
    denominator = units["win_profit"] + units["loss_profit_abs"]
    units["profit_capture_ratio"] = units["win_profit"] / denominator.replace(0, np.nan)
    units["profit_per_turnover_bps"] = (
        units["total_profit"] / units["total_turnover"].replace(0, np.nan) * 10_000
    )
    units["turnover_weighted_return_rate"] = (
        units["return_turnover_product"] / units["total_turnover"].replace(0, np.nan)
    )
    return units, unit_cols


def sign_permutation_pvalue(differences, weights, rng):
    values = np.asarray(differences, dtype=float)
    weights = np.asarray(weights, dtype=float)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values, weights = values[valid], weights[valid]
    if len(values) < MIN_COMMON_UNITS:
        return None
    observed = abs(np.average(values, weights=weights))
    exceed = 0
    completed = 0
    chunk_size = 500
    while completed < PERMUTATIONS:
        size = min(chunk_size, PERMUTATIONS - completed)
        signs = rng.choice([-1.0, 1.0], size=(size, len(values)))
        permuted = (signs * values * weights).sum(axis=1) / weights.sum()
        exceed += int((np.abs(permuted) >= observed).sum())
        completed += size
    return float((exceed + 1) / (PERMUTATIONS + 1))


def date_cluster_bootstrap(difference_df, rng):
    valid = difference_df.dropna(subset=["difference", "weight", "trade_date"])
    valid = valid[valid["weight"] > 0]
    dates = valid["trade_date"].drop_duplicates().to_numpy()
    if len(dates) < 2:
        return None, None

    valid = valid.assign(weighted_difference=valid["difference"] * valid["weight"])
    date_stats = valid.groupby("trade_date").agg(
        weighted_sum=("weighted_difference", "sum"), weight_sum=("weight", "sum")
    )
    sampled_indices = rng.integers(0, len(date_stats), size=(BOOTSTRAPS, len(date_stats)))
    sums = date_stats["weighted_sum"].to_numpy()[sampled_indices].sum(axis=1)
    weights = date_stats["weight_sum"].to_numpy()[sampled_indices].sum(axis=1)
    estimates = sums / weights
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(low), float(high)


def compare_pair(units, unit_cols, algo_a, algo_b, rng):
    left = units[units["algo_type"] == algo_a]
    right = units[units["algo_type"] == algo_b]
    merged = left.merge(right, on=unit_cols, suffixes=("_a", "_b"), how="inner")

    result = {
        "algo_a": algo_a,
        "algo_b": algo_b,
        "common_unit_count": int(len(merged)),
        "common_trade_date_count": int(merged["trade_date"].nunique()) if len(merged) else 0,
        "metrics": {},
    }
    for metric in PRIMARY_METRICS:
        difference = merged[f"{metric}_a"] - merged[f"{metric}_b"]
        # 同一环境对两算法使用相同权重；取双方交易额之和代表该环境的业务规模。
        comparison_weight = merged["total_turnover_a"] + merged["total_turnover_b"]
        valid = pd.DataFrame({
            "trade_date": merged["trade_date"],
            "difference": difference,
            "weight": comparison_weight,
        })
        valid = valid.replace([np.inf, -np.inf], np.nan).dropna()
        low, high = date_cluster_bootstrap(valid, rng)
        weighted_difference = (
            np.average(valid["difference"], weights=valid["weight"])
            if len(valid) and valid["weight"].sum() > 0 else None
        )
        result["metrics"][metric] = {
            "valid_common_unit_count": int(len(valid)),
            "turnover_weighted_mean_difference": (
                float(weighted_difference) if weighted_difference is not None else None
            ),
            "median_difference": float(valid["difference"].median()) if len(valid) else None,
            "algo_a_win_turnover_ratio": (
                float(valid.loc[valid["difference"] > 0, "weight"].sum() / valid["weight"].sum())
                if len(valid) and valid["weight"].sum() > 0 else None
            ),
            "bootstrap_ci_95_low": low,
            "bootstrap_ci_95_high": high,
            "permutation_p_value": sign_permutation_pvalue(
                valid["difference"], valid["weight"], rng
            ),
            "fdr_q_value": None,
            "fdr_significant_0_05": None,
        }
    return result


def leave_one_algorithm_out(units, unit_cols, algorithm):
    """算法自身按其环境交易额加权，与相同环境中的其他算法比较。"""
    current = units[units["algo_type"] == algorithm].copy()
    peer_units = units[units["algo_type"] != algorithm].copy()
    peers = peer_units.groupby(unit_cols, dropna=False).agg(
        record_count=("record_count", "sum"),
        win_count=("win_count", "sum"),
        win_profit=("win_profit", "sum"),
        loss_profit_abs=("loss_profit_abs", "sum"),
        return_sum=("return_sum", "sum"),
        return_turnover_product=("return_turnover_product", "sum"),
        total_profit=("total_profit", "sum"),
        total_turnover=("total_turnover", "sum"),
    ).reset_index()
    peers["win_rate"] = peers["win_count"] / peers["record_count"].replace(0, np.nan)
    peers["profit_capture_ratio"] = peers["win_profit"] / (
        peers["win_profit"] + peers["loss_profit_abs"]
    ).replace(0, np.nan)
    peers["turnover_weighted_return_rate"] = (
        peers["return_turnover_product"] / peers["total_turnover"].replace(0, np.nan)
    )
    peers["profit_per_turnover_bps"] = (
        peers["total_profit"] / peers["total_turnover"].replace(0, np.nan) * 10_000
    )
    matched = current.merge(peers, on=unit_cols, suffixes=("_current", "_peer"), how="inner")
    weights = matched["total_turnover_current"].where(
        matched["total_turnover_current"] > 0,
        matched["record_count_current"],
    )
    output = {
        "matched_environment_count": int(len(matched)),
        "matched_weight": float(weights.sum()),
    }
    for metric in PRIMARY_METRICS + ["profit_per_turnover_bps"]:
        current_values = pd.to_numeric(matched[f"{metric}_current"], errors="coerce")
        peer_values = pd.to_numeric(matched[f"{metric}_peer"], errors="coerce")
        valid = current_values.notna() & peer_values.notna() & weights.gt(0)
        valid_weight = weights[valid].sum()
        if valid_weight <= 0:
            output[f"adjusted_{metric}"] = None
            output[f"peer_{metric}"] = None
            output[f"difference_{metric}"] = None
            continue
        current_value = np.average(current_values[valid], weights=weights[valid])
        peer_value = np.average(peer_values[valid], weights=weights[valid])
        output[f"adjusted_{metric}"] = float(current_value)
        output[f"peer_{metric}"] = float(peer_value)
        output[f"difference_{metric}"] = float(current_value - peer_value)
    return output


def benchmark_summary(name, algorithm_results, pairwise):
    eligible = [item for item in algorithm_results if item["overall"]["record_count"] >= MIN_ALGO_RECORDS]
    def adjusted_return(item):
        value = item["leave_one_algorithm_out"].get("difference_turnover_weighted_return_rate")
        return -np.inf if value is None else value
    return {
        "benchmark_name": name,
        "algorithm_count": len(algorithm_results),
        "eligible_algorithm_count": len(eligible),
        "pairwise_comparison_count": len(pairwise),
        "significant_comparison_count_after_fdr": None,
        "best_adjusted_turnover_weighted_return_algorithm": max(
            eligible, key=adjusted_return,
        )["algo_type"] if eligible else None,
        "significant_findings": [],
        "note": "显著性结论需在全报告完成 BH-FDR 校正后读取。",
    }


def build_benchmark(df, key, config, rng):
    logging.info("计算 %s", key)
    group_cols = config["group_cols"]
    algorithms = sorted(df["algo_type"].dropna().astype(str).unique())
    units, unit_cols = aggregate_units(df, group_cols)
    algorithm_results = []
    for algorithm in algorithms:
        algo_df = df[df["algo_type"].astype(str) == algorithm]
        algorithm_results.append({
            "algo_type": algorithm,
            "overall": calculate_metrics(algo_df),
            "leave_one_algorithm_out": leave_one_algorithm_out(units, unit_cols, algorithm),
        })

    pairwise = [
        compare_pair(units, unit_cols, algo_a, algo_b, rng)
        for algo_a, algo_b in combinations(algorithms, 2)
    ]
    comparable_units = units.groupby(unit_cols, dropna=False)["algo_type"].nunique()

    result = {
        "definition": {
            "name": config["name"],
            "environment_columns": group_cols,
            "significance_unit_columns": unit_cols,
            "pooled_environment_count": int(df.groupby(group_cols, dropna=False).ngroups),
            "common_multi_algorithm_unit_count": int((comparable_units >= 2).sum()),
        },
        "pooled_metrics": calculate_metrics(df),
        "algorithm_results": algorithm_results,
        "pairwise_significance": pairwise,
    }
    result["summary"] = benchmark_summary(config["name"], algorithm_results, pairwise)
    return result


def apply_bh_fdr(benchmarks):
    tests = []
    for benchmark_key, benchmark in benchmarks.items():
        for pair_index, pair in enumerate(benchmark["pairwise_significance"]):
            for metric, values in pair["metrics"].items():
                p_value = values["permutation_p_value"]
                if p_value is not None:
                    tests.append((p_value, benchmark_key, pair_index, metric))

    ordered = sorted(tests, key=lambda item: item[0])
    count = len(ordered)
    adjusted = [0.0] * count
    running = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        running = min(running, ordered[index][0] * count / rank)
        adjusted[index] = min(1.0, running)

    for (_, benchmark_key, pair_index, metric), q_value in zip(ordered, adjusted):
        target = benchmarks[benchmark_key]["pairwise_significance"][pair_index]["metrics"][metric]
        target["fdr_q_value"] = float(q_value)
        target["fdr_significant_0_05"] = bool(q_value < 0.05)

    for benchmark in benchmarks.values():
        significant = sum(
            values["fdr_significant_0_05"] is True
            for pair in benchmark["pairwise_significance"]
            for values in pair["metrics"].values()
        )
        benchmark["summary"]["significant_comparison_count_after_fdr"] = significant
        findings = []
        for pair in benchmark["pairwise_significance"]:
            for metric, values in pair["metrics"].items():
                if values["fdr_significant_0_05"] is not True:
                    continue
                difference = values["turnover_weighted_mean_difference"]
                findings.append({
                    "metric": metric,
                    "better_algorithm": pair["algo_a"] if difference > 0 else pair["algo_b"],
                    "worse_algorithm": pair["algo_b"] if difference > 0 else pair["algo_a"],
                    "turnover_weighted_difference_algo_a_minus_algo_b": difference,
                    "fdr_q_value": values["fdr_q_value"],
                })
        benchmark["summary"]["significant_findings"] = findings
        benchmark["summary"]["note"] = "已完成全报告范围 BH-FDR 校正。"
    return len(tests)


def apply_pairwise_bh_fdr(pairwise_results):
    """对独立股票共同覆盖报告中的配对检验统一执行 BH-FDR。"""
    tests = []
    for pair_index, pair in enumerate(pairwise_results):
        for metric, values in pair["metrics"].items():
            p_value = values["permutation_p_value"]
            if p_value is not None:
                tests.append((p_value, pair_index, metric))

    ordered = sorted(tests, key=lambda item: item[0])
    count = len(ordered)
    adjusted = [0.0] * count
    running = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        running = min(running, ordered[index][0] * count / rank)
        adjusted[index] = min(1.0, running)

    for (_, pair_index, metric), q_value in zip(ordered, adjusted):
        target = pairwise_results[pair_index]["metrics"][metric]
        target["fdr_q_value"] = float(q_value)
        target["fdr_significant_0_05"] = bool(q_value < 0.05)
    return count


def dataframe_records(frame, columns):
    """把 DataFrame 转为可 JSON 序列化记录，并统一处理日期和缺失值。"""
    records = []
    for row in frame[columns].to_dict(orient="records"):
        clean = {}
        for key, value in row.items():
            if isinstance(value, pd.Timestamp):
                clean[key] = value.strftime("%Y-%m-%d")
            elif pd.isna(value):
                clean[key] = None
            elif isinstance(value, (np.integer,)):
                clean[key] = int(value)
            elif isinstance(value, (np.floating,)):
                clean[key] = float(value)
            else:
                clean[key] = value
        records.append(clean)
    return records


def build_stock_pair_rankings(units):
    """按固定股票计算算法对的共同日期、共同记录和覆盖比例。"""
    rankings = []
    for stock_code, stock_units in units.groupby("stock_code", dropna=False):
        algorithms = sorted(stock_units["algo_type"].dropna().astype(str).unique())
        for algo_a, algo_b in combinations(algorithms, 2):
            left = stock_units[stock_units["algo_type"].astype(str) == algo_a]
            right = stock_units[stock_units["algo_type"].astype(str) == algo_b]
            merged = left.merge(
                right, on=["trade_date", "stock_code"], suffixes=("_a", "_b"), how="outer",
            )
            present_a = merged["record_count_a"].notna()
            present_b = merged["record_count_b"].notna()
            common = present_a & present_b
            union_unit_count = int((present_a | present_b).sum())
            common_unit_count = int(common.sum())
            record_a = float(merged["record_count_a"].fillna(0).sum())
            record_b = float(merged["record_count_b"].fillna(0).sum())
            common_record_count = int(
                np.minimum(
                    merged.loc[common, "record_count_a"],
                    merged.loc[common, "record_count_b"],
                ).sum()
            )
            record_denominator = record_a + record_b
            rankings.append({
                "group_name": f"stock={stock_code}|{algo_a}__{algo_b}",
                "stock_code": stock_code,
                "algo_a": algo_a,
                "algo_b": algo_b,
                "algo_a_record_count": int(record_a),
                "algo_b_record_count": int(record_b),
                "union_trade_date_count": union_unit_count,
                "common_trade_date_count": common_unit_count,
                "common_unit_ratio": (
                    float(common_unit_count / union_unit_count) if union_unit_count else None
                ),
                "common_record_count": common_record_count,
                "common_record_ratio": (
                    float(2 * common_record_count / record_denominator)
                    if record_denominator else None
                ),
            })
    rankings.sort(
        key=lambda item: (
            -item["common_record_count"],
            -item["common_trade_date_count"],
            -(item["common_record_ratio"] or 0),
            str(item["stock_code"]),
            item["algo_a"],
            item["algo_b"],
        )
    )
    for rank, item in enumerate(rankings, 1):
        item["rank"] = rank
    return rankings


def build_stock_date_pair_rankings(units):
    """按股票＋日期计算算法对的记录数平衡重叠率。"""
    rankings = []
    for (trade_date, stock_code), group in units.groupby(
        ["trade_date", "stock_code"], dropna=False
    ):
        algorithms = sorted(group["algo_type"].dropna().astype(str).unique())
        for algo_a, algo_b in combinations(algorithms, 2):
            row_a = group[group["algo_type"].astype(str) == algo_a].iloc[0]
            row_b = group[group["algo_type"].astype(str) == algo_b].iloc[0]
            record_a = int(row_a["record_count"])
            record_b = int(row_b["record_count"])
            common_record_count = min(record_a, record_b)
            denominator = record_a + record_b
            date_text = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
            rankings.append({
                "group_name": f"stock_date={stock_code}@{date_text}|{algo_a}__{algo_b}",
                "trade_date": date_text,
                "stock_code": stock_code,
                "algo_a": algo_a,
                "algo_b": algo_b,
                "algo_a_record_count": record_a,
                "algo_b_record_count": record_b,
                "common_record_count": common_record_count,
                "common_record_ratio": (
                    float(2 * common_record_count / denominator) if denominator else None
                ),
            })
    rankings.sort(
        key=lambda item: (
            -item["common_record_count"],
            -(item["common_record_ratio"] or 0),
            item["trade_date"],
            str(item["stock_code"]),
            item["algo_a"],
            item["algo_b"],
        )
    )
    for rank, item in enumerate(rankings, 1):
        item["rank"] = rank
    return rankings


def test_top_stock_groups(units, stock_rankings, rng):
    """先按日期数和覆盖率筛选，再对共同记录数靠前的固定股票组检验。"""
    eligible = [
        item for item in stock_rankings
        if item["common_trade_date_count"] >= MIN_COMMON_UNITS
        and (item["common_record_ratio"] or 0) >= MIN_COMMON_RECORD_RATIO
    ][:TOP_STOCK_SIGNIFICANCE_GROUPS]
    results = []
    for ranking in eligible:
        stock_units = units[units["stock_code"] == ranking["stock_code"]]
        comparison = compare_pair(
            stock_units,
            ["trade_date", "stock_code"],
            ranking["algo_a"],
            ranking["algo_b"],
            rng,
        )
        comparison.update({
            "rank": ranking["rank"],
            "group_name": ranking["group_name"],
            "stock_code": ranking["stock_code"],
            "common_unit_ratio": ranking["common_unit_ratio"],
            "common_record_count": ranking["common_record_count"],
            "common_record_ratio": ranking["common_record_ratio"],
        })
        results.append(comparison)
    test_count = apply_pairwise_bh_fdr(results)
    return results, test_count


def run_stock_overlap_analysis():
    """单独输出算法×日期×股票统计、共同覆盖排名及高覆盖组显著性检验。"""
    logging.info("开始计算算法＋日期＋股票共同覆盖报告")
    df = load_data()
    required = ["trade_date", "stock_code", "algo_type", "profit", "return_rate", "turnover"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"analysis_record 缺少股票共同覆盖字段：{missing}")

    units, _ = aggregate_units(df, ["trade_date", "stock_code"])
    unit_columns = [
        "trade_date", "stock_code", "algo_type", "record_count", "win_count", "win_rate",
        "win_profit", "loss_profit_abs", "profit_capture_ratio", "total_profit",
        "total_turnover", "turnover_weighted_return_rate", "profit_per_turnover_bps",
    ]
    stock_rankings = build_stock_pair_rankings(units)
    stock_date_rankings = build_stock_date_pair_rankings(units)
    rng = np.random.default_rng(RANDOM_SEED)
    significance_results, test_count = test_top_stock_groups(units, stock_rankings, rng)

    report = {
        "metadata": {
            "generated_at": RUN_TIME.strftime("%Y-%m-%d %H:%M:%S"),
            "source_table": "analysis_record",
            "record_count": int(len(df)),
            "algorithm_count": int(df["algo_type"].nunique()),
            "trade_date_count": int(df["trade_date"].nunique()),
            "stock_count": int(df["stock_code"].nunique()),
            "algorithm_date_stock_unit_count": int(len(units)),
            "top_significance_group_limit": TOP_STOCK_SIGNIFICANCE_GROUPS,
            "minimum_common_trade_dates_for_significance": MIN_COMMON_UNITS,
            "minimum_common_record_ratio_for_significance": MIN_COMMON_RECORD_RATIO,
        },
        "definitions": {
            "fixed_stock_common_unit_ratio": "共同交易日数 / 两算法交易日并集数",
            "common_record_count": "每个共同单元 min(算法A记录数, 算法B记录数) 的合计",
            "common_record_ratio": "2 × 共同记录数 / (算法A记录数 + 算法B记录数)",
            "ranking_order": "共同记录条数降序、共同交易日数降序、共同记录占比降序、小组名称升序",
            "significance_group_selection": (
                "先筛选共同交易日数不少于5且共同记录占比不少于50%的固定股票组，"
                "再按共同记录条数降序选择前10组。"
            ),
            "stock_date_significance_note": (
                "股票＋日期只有一个独立日期，仅输出覆盖统计，不执行日期配对显著性检验。"
            ),
            "significance_method": (
                "固定股票高覆盖组：共同日期配对、交易额加权差值、符号置换检验、"
                "日期聚类Bootstrap、组内全部指标BH-FDR。"
            ),
        },
        "algorithm_date_stock_statistics": dataframe_records(units, unit_columns),
        "fixed_stock_pair_rankings": stock_rankings,
        "stock_date_pair_rankings": stock_date_rankings,
        "top_fixed_stock_significance": significance_results,
        "summary": {
            "fixed_stock_pair_group_count": len(stock_rankings),
            "stock_date_pair_group_count": len(stock_date_rankings),
            "significance_group_count": len(significance_results),
            "fdr_test_count": test_count,
            "significant_test_count_after_fdr": sum(
                values["fdr_significant_0_05"] is True
                for pair in significance_results
                for values in pair["metrics"].values()
            ),
            "significant_test_count_before_fdr": sum(
                values["permutation_p_value"] < 0.05
                for pair in significance_results
                for values in pair["metrics"].values()
                if values.get("permutation_p_value") is not None
            ),
        },
    }
    with open(STOCK_OVERLAP_REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, default=json_default)
    logging.info("股票共同覆盖报告已保存：%s", STOCK_OVERLAP_REPORT_PATH)
    return report


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d")
    raise TypeError(f"无法序列化：{type(value).__name__}")


def run_analysis():
    df = load_data()
    required = sorted({column for config in BENCHMARKS.values() for column in config["group_cols"]})
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"analysis_record 缺少算法分析字段：{missing}")

    rng = np.random.default_rng(RANDOM_SEED)
    benchmarks = {
        key: build_benchmark(df, key, config, rng)
        for key, config in BENCHMARKS.items()
    }
    test_count = apply_bh_fdr(benchmarks)

    report = {
        "metadata": {
            "generated_at": RUN_TIME.strftime("%Y-%m-%d %H:%M:%S"),
            "source_table": "analysis_record",
            "record_count": len(df),
            "trade_date_count": int(df["trade_date"].nunique()),
            "algorithm_count": int(df["algo_type"].nunique()),
            "primary_metrics": PRIMARY_METRICS,
            "return_metric_definition": "Σ(return_rate × turnover) / Σturnover",
            "unweighted_return_usage": "仅用于分布诊断，不参与排名和显著性结论",
            "profit_capture_ratio_definition": "盈利额 / (盈利额 + 亏损额绝对值)",
            "permutation_count": PERMUTATIONS,
            "bootstrap_count": BOOTSTRAPS,
            "minimum_common_units": MIN_COMMON_UNITS,
        },
        "benchmarks": benchmarks,
        "final_summary": {
            "completed_benchmarks": list(benchmarks),
            "fdr_test_count": test_count,
            "method": "环境内算法比较 + leave-one-algorithm-out + 配对置换检验 + 日期聚类Bootstrap + BH-FDR",
            "interpretation": [
                "优先查看胜率、盈利捕获率和交易额加权收益率是否同方向。",
                "未加权平均收益率只用于诊断收益分布，不参与算法排名或显著性结论。",
                "只有共同环境覆盖充分且FDR校正后显著的差异才作为强结论。",
                "当日行情分组仅用于事后评价，不得直接作为当日预测输入。",
            ],
        },
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, default=json_default)
    logging.info("算法分析报告已保存：%s", REPORT_PATH)
    return report


def parse_args():
    parser = argparse.ArgumentParser(description="算法表现与共同股票覆盖分析")
    parser.add_argument(
        "--mode",
        choices=["standard", "stock-overlap", "all"],
        default="standard",
        help="standard=原 Benchmark 报告；stock-overlap=股票共同覆盖独立报告；all=两者均运行",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.mode in {"standard", "all"}:
        run_analysis()
    if args.mode in {"stock-overlap", "all"}:
        run_stock_overlap_analysis()
