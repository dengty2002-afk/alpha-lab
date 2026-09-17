"""Stable metric definitions and explicit undefined states for report consumers."""
from .common import clean


DEFINITIONS = {
    "ic": ("Pearson IC", "corr(factor(t), open(t+1+h)/open(t+1)-1)", "correlation", "有效证券不足阈值，或因子/标签为常数"),
    "rankIc": ("Rank IC", "Pearson correlation of average ranks (Spearman)", "correlation", "有效证券不足阈值，或因子/标签排名为常数"),
    "icir": ("ICIR（不年化）", "mean(daily IC)/std(daily IC,ddof=1)", "ratio", "有效 IC 少于2个或 IC 标准差为0"),
    "rankIcir": ("Rank ICIR（不年化）", "mean(daily Rank IC)/std(daily Rank IC,ddof=1)", "ratio", "有效 Rank IC 少于2个或其标准差为0"),
    "positiveIcRatio": ("正IC比例", "count(IC>0)/count(finite IC)", "fraction", "没有有效 IC 截面"),
    "spread": ("最高减最低组标签收益", "mean(forward_return|Q5)-mean(forward_return|Q1); diagnostic only", "return", "最高或最低分组没有可观察标签"),
    "monotonicity": ("分组单调性", "Spearman(group_number,group_mean_forward_return)", "correlation", "有效分组不足3个或收益为常数"),
    "memberTurnover": ("分组成员换手", "|Q(t) minus Q(t-lag)|/|Q(t)|", "fraction", "当前/历史组为空或历史不足"),
    "rankAutocorrelation": ("排名自相关", "Spearman(factor(t),factor(t-lag)) on common valid instruments", "correlation", "共同有效股票不足或排名为常数"),
    "totalReturn": ("总收益", "NAV(end)/NAV(initial cash)-1", "return", "没有完整有效收益区间"),
    "annualReturn": ("年化收益", "NAV(end)^(annualization/interval_count)-1", "return", "没有有效收益区间或数值范围不可表示"),
    "annualVolatility": ("年化波动率", "std(daily net return,ddof=1)*sqrt(annualization)", "return", "有效日收益不足2条"),
    "sharpe": ("Sharpe", "mean(daily net return)/std(daily net return,ddof=1)*sqrt(annualization); rf=0", "ratio", "有效日收益不足2条或日收益波动为0"),
    "maxDrawdown": ("最大回撤", "max(1-NAV/running_max(NAV)), including initial cash NAV=1", "fraction", "没有完整有效净值序列"),
    "calmar": ("Calmar", "annual_return/max_drawdown", "ratio", "最大回撤为0或年化收益不可计算"),
    "positiveDayRatio": ("正收益日比例", "count(daily return>0)/count(daily return); zero counts as non-positive", "fraction", "没有有效日收益"),
    "turnover": ("平均日双边资金换手", "mean((buy_notional+sell_notional)/pre_trade_NAV), includes non-rebalance zero days", "fraction", "没有完整回测区间"),
    "rebalanceTurnover": ("调仓日平均双边换手", "mean(turnover over scheduled rebalance days)", "fraction", "没有计划调仓日"),
    "totalCost": ("累计成本", "sum(buy_rate*buy_notional+sell_rate*sell_notional)", "initial_NAV", "没有完整回测区间"),
    "pnlPerTraded": ("单位成交额收益", "(final_NAV-1)/sum(buy_notional+sell_notional)", "ratio", "累计理论成交金额为0"),
    "benchmarkReturn": ("同池基准总收益", "same-universe equal-weight final_NAV-1; same schedule and costs", "return", "同池基准数据不可用"),
    "excessReturn": ("同池基准相对收益", "strategy_NAV/benchmark_NAV-1", "return", "同池基准数据不可用"),
    "informationRatio": ("信息比率 IR", "mean(strategy_daily-benchmark_daily)/std(active_daily,ddof=1)*sqrt(annualization)", "ratio", "主动收益不足2条或主动收益标准差为0"),
    "marketBenchmarkReturn": ("沪深300价格指数收益", "CSI300 open-to-open aligned final_NAV-1", "return", "缺少完整沪深300开盘序列"),
    "marketExcessReturn": ("相对沪深300收益", "strategy_NAV/CSI300_price_NAV-1", "return", "缺少完整沪深300开盘序列"),
}


def definitions():
    return [{"metric_id": k, "definition_version": "quantitative-contract-v1", "name": v[0], "formula": v[1],
             "unit": v[2], "undefinedReason": v[3]} for k,v in DEFINITIONS.items()]


def metric_rows(result):
    rows=[]
    for table in ["horizons", "backtests"]:
        for source in result.get("tables",{}).get(table,[]):
            period = source.get("horizon", source.get("rebalancePeriod"))
            scope = f"{period}日标签" if table=="horizons" else f"{source.get('model')} / {period}日调仓 / {source.get('costBps')}bps"
            for key, descriptor in DEFINITIONS.items():
                if key not in source:
                    continue
                value=clean(source[key])
                rows.append({"metric_id":key,"definition_version":"quantitative-contract-v1","name":f"{scope} · {descriptor[0]}",
                             "value":value,"unit":descriptor[2],"period":period,
                             "sample_count":source.get("count",source.get("intervalCount")),
                             "costBps":source.get("costBps"),"direction":result.get("provenance",{}).get("factors",[{}])[0].get("direction",None) if result.get("provenance",{}).get("factors") else None,
                             "data_status":"valid" if value is not None else "undefined", "reason":None if value is not None else descriptor[3]})
    return rows
