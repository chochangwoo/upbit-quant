"""
backtest/run_sideways_backtest.py - 횡보장 전용 전략 백테스트

횡보장(ADX ≤ 25)에서 최적의 전략을 찾기 위한 전용 백테스트입니다.

실행 방법:
    python -m backtest.run_sideways_backtest

파이프라인:
  1단계: 13개 코인 데이터 수집 (800일, OHLCV 전체)
  2단계: ADX 기반 횡보 구간 식별
  3단계: 횡보장 후보 전략 x 파라미터 조합 백테스트
  4단계: 전체 기간 + 횡보 구간 전용 성과 비교
  5단계: 기존 거래량돌파 전략과 비교
  6단계: 결과 저장 및 시각화
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data_collector import collect_all_data, collect_ohlcv_full
from backtest.engine import run_backtest, run_benchmark_btc, run_benchmark_equal
from backtest.metrics import calc_all_metrics, classify_regime
from backtest.report import RESULTS_DIR

# 횡보장 전략 임포트
from backtest.strategies.bb_mean_reversion import BBMeanReversion
from backtest.strategies.rsi_range_trading import RSIRangeTrading
from backtest.strategies.low_vol_rebalance import LowVolRebalance
from backtest.strategies.short_term_reversal import ShortTermReversal

# 기존 전략 (비교 대상)
from backtest.strategies.volume_breakout import VolumeBreakout
from backtest.strategies.rsi_mean_reversion import RSIMeanReversion
from backtest.strategies.cross_sectional_momentum import CrossSectionalMomentum

# ADX 계산 기본값
ADX_PERIOD = 14
ADX_SIDEWAYS_THRESHOLD = 25


def calc_adx_series(highs: pd.Series, lows: pd.Series, closes: pd.Series,
                    period: int = 14) -> pd.DataFrame:
    """
    BTC의 ADX, +DI, -DI 시계열을 계산합니다.

    반환값:
        DataFrame with columns: adx, plus_di, minus_di
    """
    n = len(closes)
    if n < period * 2:
        return pd.DataFrame(index=closes.index, columns=["adx", "plus_di", "minus_di"])

    # True Range
    tr = pd.Series(index=closes.index, dtype=float)
    plus_dm = pd.Series(index=closes.index, dtype=float)
    minus_dm = pd.Series(index=closes.index, dtype=float)

    for i in range(1, n):
        h = highs.iloc[i]
        l = lows.iloc[i]
        c_prev = closes.iloc[i - 1]
        h_prev = highs.iloc[i - 1]
        l_prev = lows.iloc[i - 1]

        tr.iloc[i] = max(h - l, abs(h - c_prev), abs(l - c_prev))

        up_move = h - h_prev
        down_move = l_prev - l

        if up_move > down_move and up_move > 0:
            plus_dm.iloc[i] = up_move
        else:
            plus_dm.iloc[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm.iloc[i] = down_move
        else:
            minus_dm.iloc[i] = 0.0

    # EMA 스무딩
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    smooth_plus_dm = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    smooth_minus_dm = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    # +DI, -DI
    plus_di = 100 * smooth_plus_dm / atr
    minus_di = 100 * smooth_minus_dm / atr

    # DX, ADX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100 * di_diff / di_sum.replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    result = pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }, index=closes.index)

    return result


def identify_sideways_periods(adx_df: pd.DataFrame,
                              threshold: int = ADX_SIDEWAYS_THRESHOLD) -> pd.Series:
    """
    ADX 기반으로 횡보 구간을 식별합니다.

    반환값:
        bool Series (True = 횡보장)
    """
    return adx_df["adx"] <= threshold


def get_sideways_strategy_configs() -> list:
    """
    횡보장 전용 전략 x 파라미터 조합을 반환합니다.
    """
    configs = []

    # 1. 볼린저밴드 평균회귀 (3 x 2 = 6개)
    for pct_b_threshold in [0.1, 0.2, 0.3]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": BBMeanReversion(
                    bb_period=20, bb_std=2.0,
                    pct_b_threshold=pct_b_threshold, top_k=top_k
                ),
                "type": "BB평균회귀",
            })

    # 2. RSI 레인지 트레이딩 (3 x 2 = 6개)
    for oversold in [30, 35, 40]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": RSIRangeTrading(
                    rsi_period=14, oversold=oversold,
                    overbought=65, top_k=top_k
                ),
                "type": "RSI레인지",
            })

    # 3. 저변동성 리밸런싱 (2 x 2 = 4개)
    for vol_lookback in [14, 20]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": LowVolRebalance(
                    vol_lookback=vol_lookback, top_k=top_k
                ),
                "type": "저변동성",
            })

    # 4. 단기 반전 (3 x 2 = 6개)
    for lookback in [3, 5, 7]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": ShortTermReversal(
                    lookback=lookback, max_drop=-0.15, top_k=top_k
                ),
                "type": "단기반전",
            })

    # 5. 기존 전략 비교 대상
    # 거래량 돌파 (현재 횡보장에서 사용 중)
    for vol_ratio in [1.3, 1.5]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": VolumeBreakout(
                    price_lookback=5, vol_ratio=vol_ratio, top_k=top_k
                ),
                "type": "거래량돌파(기존)",
            })

    # RSI 역추세 (기존)
    for threshold in [30, 40]:
        configs.append({
            "strategy": RSIMeanReversion(
                rsi_period=14, threshold=threshold, top_k=5
            ),
            "type": "RSI역추세(기존)",
        })

    # 크로스섹셔널 모멘텀 (기존)
    for lookback in [7, 14]:
        configs.append({
            "strategy": CrossSectionalMomentum(lookback=lookback, top_k=5),
            "type": "모멘텀(기존)",
        })

    return configs


def calc_sideways_metrics(equity_curve: pd.Series, window_details: pd.DataFrame,
                          is_sideways: pd.Series) -> dict:
    """
    횡보 구간만 필터링하여 성과 지표를 계산합니다.

    매개변수:
        equity_curve  : 전체 에쿼티 커브
        window_details: 윈도우별 상세 정보
        is_sideways   : bool Series (True = 횡보장)
    반환값:
        dict: 횡보 구간 지표
    """
    if equity_curve.empty:
        return {"횡보수익률": 0, "횡보샤프": 0, "횡보MDD": 0, "횡보비율": 0}

    # 에쿼티 커브에서 횡보 구간만 필터
    common_idx = equity_curve.index.intersection(is_sideways.index)
    sideways_mask = is_sideways.reindex(common_idx).fillna(False)
    sideways_equity = equity_curve.reindex(common_idx)[sideways_mask]

    if len(sideways_equity) < 10:
        return {"횡보수익률": 0, "횡보샤프": 0, "횡보MDD": 0, "횡보비율": 0}

    # 횡보 구간 내 일별 수익률 기반 지표 계산
    daily_returns = sideways_equity.pct_change().dropna()
    if len(daily_returns) < 2:
        return {"횡보수익률": 0, "횡보샤프": 0, "횡보MDD": 0, "횡보비율": 0}

    cum_return = (1 + daily_returns).prod() - 1
    ann_vol = daily_returns.std() * np.sqrt(365)
    ann_return = cum_return * (365 / len(daily_returns)) if len(daily_returns) > 0 else 0

    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # 횡보 구간 MDD
    peak = sideways_equity.cummax()
    drawdown = (sideways_equity - peak) / peak
    mdd = drawdown.min()

    sideways_ratio = sideways_mask.sum() / len(common_idx) if len(common_idx) > 0 else 0

    # 윈도우 기반 횡보 승률
    if not window_details.empty and "레짐" in window_details.columns:
        sw_windows = window_details[window_details["레짐"] == "횡보"]
        sw_win_rate = (sw_windows["수익률"] > 0).mean() if len(sw_windows) > 0 else 0
    else:
        sw_win_rate = 0

    return {
        "횡보수익률": cum_return,
        "횡보샤프": sharpe,
        "횡보MDD": mdd,
        "횡보비율": sideways_ratio,
        "횡보윈도우승률": sw_win_rate,
        "횡보일수": int(sideways_mask.sum()),
    }


def main():
    """횡보장 전용 백테스트 메인 실행 함수"""
    start_time = time.time()

    SIDEWAYS_RESULTS_DIR = os.path.join(RESULTS_DIR, "sideways")
    os.makedirs(SIDEWAYS_RESULTS_DIR, exist_ok=True)

    # ========================================
    # 1. 데이터 수집
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 1단계: 데이터 수집")
    logger.info(f"{'='*70}")

    # OHLCV 전체 데이터 (ADX 계산에 high/low 필요)
    ohlcv_data = collect_ohlcv_full(days=800, force=False)
    prices = ohlcv_data["prices"]
    volumes = ohlcv_data["volumes"]
    highs = ohlcv_data["highs"]
    lows = ohlcv_data["lows"]

    logger.info(f"  가격 데이터: {prices.shape[0]}일 x {prices.shape[1]}개 코인")
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # ========================================
    # 2. ADX 기반 횡보 구간 식별
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 2단계: ADX 기반 횡보 구간 식별")
    logger.info(f"{'='*70}")

    btc_ticker = "KRW-BTC"
    adx_df = calc_adx_series(
        highs[btc_ticker], lows[btc_ticker], prices[btc_ticker],
        period=ADX_PERIOD
    )
    is_sideways = identify_sideways_periods(adx_df, ADX_SIDEWAYS_THRESHOLD)

    total_days = len(is_sideways.dropna())
    sideways_days = is_sideways.dropna().sum()
    sideways_pct = sideways_days / total_days * 100 if total_days > 0 else 0

    logger.info(f"  ADX 기간: {ADX_PERIOD}일, 횡보 임계값: ADX ≤ {ADX_SIDEWAYS_THRESHOLD}")
    logger.info(f"  전체 일수: {total_days}일")
    logger.info(f"  횡보 일수: {int(sideways_days)}일 ({sideways_pct:.1f}%)")
    logger.info(f"  추세 일수: {int(total_days - sideways_days)}일 ({100 - sideways_pct:.1f}%)")

    # ADX 구간별 통계
    adx_clean = adx_df["adx"].dropna()
    logger.info(f"\n  [ADX 분포]")
    logger.info(f"    평균: {adx_clean.mean():.1f}")
    logger.info(f"    중위수: {adx_clean.median():.1f}")
    logger.info(f"    최소: {adx_clean.min():.1f} / 최대: {adx_clean.max():.1f}")

    # ========================================
    # 3. 전략 구성
    # ========================================
    configs = get_sideways_strategy_configs()
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 3단계: 전략 백테스트")
    logger.info(f"{'='*70}")

    # 유형별 전략 수 카운트
    type_counts = {}
    for c in configs:
        t = c["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, cnt in type_counts.items():
        logger.info(f"    {t}: {cnt}개")
    logger.info(f"    합계: {len(configs)}개 전략")

    # ========================================
    # 4. 백테스트 실행
    # ========================================
    OOS_PERIODS = [15, 30]
    all_results = []

    for oos_days in OOS_PERIODS:
        logger.info(f"\n  --- OOS {oos_days}일 백테스트 시작 ---")

        for i, config in enumerate(configs, 1):
            strategy = config["strategy"]
            stype = config["type"]

            result = run_backtest(strategy, prices, volumes, oos_window=oos_days)
            eq = result["equity_curve"]

            if len(eq) > 0:
                # 전체 기간 지표
                metrics = calc_all_metrics(eq)
                # 횡보 구간 지표
                sw_metrics = calc_sideways_metrics(eq, result["window_details"], is_sideways)

                all_results.append({
                    "전략": strategy.name,
                    "유형": stype,
                    "OOS": oos_days,
                    # 전체 기간
                    "누적수익률": metrics["누적수익률"],
                    "샤프비율": metrics["샤프비율"],
                    "MDD": metrics["MDD"],
                    "소르티노": metrics["소르티노비율"],
                    "일별승률": metrics["일별승률"],
                    "프로핏팩터": metrics["프로핏팩터"],
                    # 횡보 구간
                    "횡보수익률": sw_metrics["횡보수익률"],
                    "횡보샤프": sw_metrics["횡보샤프"],
                    "횡보MDD": sw_metrics["횡보MDD"],
                    "횡보윈도우승률": sw_metrics.get("횡보윈도우승률", 0),
                    "횡보일수": sw_metrics.get("횡보일수", 0),
                })

            if i % 10 == 0:
                logger.info(f"    {i}/{len(configs)} 완료...")

        logger.info(f"  --- OOS {oos_days}일 완료 ({len(configs)}개) ---")

    # ========================================
    # 5. 결과 분석
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 4단계: 결과 분석")
    logger.info(f"{'='*70}")

    results_df = pd.DataFrame(all_results)

    if results_df.empty:
        logger.error("  백테스트 결과가 없습니다!")
        return

    # 횡보 샤프 기준 TOP 15 (OOS 30일 기준)
    oos30 = results_df[results_df["OOS"] == 30].copy()
    if oos30.empty:
        oos30 = results_df[results_df["OOS"] == 15].copy()

    oos30_sorted = oos30.sort_values("횡보샤프", ascending=False)

    logger.info(f"\n  [횡보장 성과 TOP 15 - 횡보 샤프 기준]")
    logger.info(f"  {'전략':<35} {'횡보샤프':>8} {'횡보수익률':>10} {'횡보MDD':>8} {'전체샤프':>8} {'전체수익률':>10}")
    logger.info(f"  {'-'*85}")
    for _, row in oos30_sorted.head(15).iterrows():
        logger.info(
            f"  {row['전략']:<35} "
            f"{row['횡보샤프']:>8.2f} "
            f"{row['횡보수익률']:>+10.2%} "
            f"{row['횡보MDD']:>8.2%} "
            f"{row['샤프비율']:>8.2f} "
            f"{row['누적수익률']:>+10.2%}"
        )

    # 전략 유형별 평균 (횡보 성과)
    logger.info(f"\n  [전략 유형별 횡보 성과 평균]")
    type_avg = oos30.groupby("유형").agg({
        "횡보샤프": "mean",
        "횡보수익률": "mean",
        "횡보MDD": "mean",
        "샤프비율": "mean",
        "누적수익률": "mean",
        "횡보윈도우승률": "mean",
    }).sort_values("횡보샤프", ascending=False)

    logger.info(f"  {'유형':<20} {'횡보샤프':>8} {'횡보수익률':>10} {'횡보MDD':>8} {'전체샤프':>8} {'횡보승률':>8}")
    logger.info(f"  {'-'*70}")
    for stype, row in type_avg.iterrows():
        logger.info(
            f"  {stype:<20} "
            f"{row['횡보샤프']:>8.2f} "
            f"{row['횡보수익률']:>+10.2%} "
            f"{row['횡보MDD']:>8.2%} "
            f"{row['샤프비율']:>8.2f} "
            f"{row['횡보윈도우승률']:>8.0%}"
        )

    # 기존 전략 vs 신규 전략 비교
    logger.info(f"\n  [기존 전략 vs 횡보 전용 전략 비교]")
    existing_types = ["거래량돌파(기존)", "RSI역추세(기존)", "모멘텀(기존)"]
    new_types = ["BB평균회귀", "RSI레인지", "저변동성", "단기반전"]

    existing_avg = oos30[oos30["유형"].isin(existing_types)]
    new_avg = oos30[oos30["유형"].isin(new_types)]

    if not existing_avg.empty and not new_avg.empty:
        logger.info(f"    기존 전략 평균 — 횡보샤프: {existing_avg['횡보샤프'].mean():.2f}, "
                     f"횡보수익률: {existing_avg['횡보수익률'].mean():+.2%}")
        logger.info(f"    신규 전략 평균 — 횡보샤프: {new_avg['횡보샤프'].mean():.2f}, "
                     f"횡보수익률: {new_avg['횡보수익률'].mean():+.2%}")

    # OOS 기간별 안정성
    logger.info(f"\n  [OOS 기간별 상위 전략 안정성]")
    for stype in new_types:
        subset = results_df[results_df["유형"] == stype]
        if subset.empty:
            continue
        avg_by_oos = subset.groupby("OOS")["횡보샤프"].mean()
        oos_str = " / ".join([f"OOS{k}={v:.2f}" for k, v in avg_by_oos.items()])
        logger.info(f"    {stype}: {oos_str}")

    # ========================================
    # 6. 파일 저장
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 5단계: 결과 저장")
    logger.info(f"{'='*70}")

    # 전체 결과 CSV
    results_df.to_csv(
        os.path.join(SIDEWAYS_RESULTS_DIR, "sideways_all_results.csv"),
        index=False, encoding="utf-8-sig"
    )
    logger.info(f"  -> sideways_all_results.csv 저장")

    # 유형별 평균 CSV
    type_avg.to_csv(
        os.path.join(SIDEWAYS_RESULTS_DIR, "sideways_type_avg.csv"),
        encoding="utf-8-sig"
    )
    logger.info(f"  -> sideways_type_avg.csv 저장")

    # TOP 전략 JSON
    top_strategies = []
    for _, row in oos30_sorted.head(10).iterrows():
        top_strategies.append({
            "전략": row["전략"],
            "유형": row["유형"],
            "횡보샤프": round(row["횡보샤프"], 4),
            "횡보수익률": round(row["횡보수익률"], 4),
            "횡보MDD": round(row["횡보MDD"], 4),
            "전체샤프": round(row["샤프비율"], 4),
            "전체수익률": round(row["누적수익률"], 4),
        })

    json_data = {
        "생성시각": pd.Timestamp.now().isoformat(),
        "데이터기간": f"{prices.index[0].date()} ~ {prices.index[-1].date()}",
        "ADX설정": {"기간": ADX_PERIOD, "횡보임계값": ADX_SIDEWAYS_THRESHOLD},
        "횡보비율": f"{sideways_pct:.1f}%",
        "전략수": len(configs),
        "OOS기간": OOS_PERIODS,
        "횡보TOP10": top_strategies,
    }

    with open(os.path.join(SIDEWAYS_RESULTS_DIR, "sideways_results.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"  -> sideways_results.json 저장")

    # ADX 시계열 저장
    adx_df.to_csv(
        os.path.join(SIDEWAYS_RESULTS_DIR, "btc_adx_series.csv"),
        encoding="utf-8-sig"
    )
    logger.info(f"  -> btc_adx_series.csv 저장")

    # ========================================
    # 7. 최종 추천
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  [횡보장 백테스트] 최종 추천")
    logger.info(f"{'='*70}")

    if not oos30_sorted.empty:
        best = oos30_sorted.iloc[0]
        logger.info(f"\n  ** 횡보장 최적 전략 **")
        logger.info(f"  전략명: {best['전략']}")
        logger.info(f"  유형: {best['유형']}")
        logger.info(f"  횡보 샤프: {best['횡보샤프']:.2f}")
        logger.info(f"  횡보 수익률: {best['횡보수익률']:+.2%}")
        logger.info(f"  횡보 MDD: {best['횡보MDD']:.2%}")
        logger.info(f"  전체 샤프: {best['샤프비율']:.2f}")
        logger.info(f"  전체 수익률: {best['누적수익률']:+.2%}")

    # ========================================
    # 완료
    # ========================================
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*70}")
    logger.info(f"  횡보장 백테스트 완료!")
    logger.info(f"{'='*70}")
    logger.info(f"  총 소요 시간: {elapsed:.1f}초")
    logger.info(f"  전략 조합: {len(configs)}개 x OOS 기간: {len(OOS_PERIODS)}개 = {len(configs) * len(OOS_PERIODS)}회")
    logger.info(f"  결과 폴더: {SIDEWAYS_RESULTS_DIR}")
    logger.info(f"\n  생성된 파일:")
    for f_name in sorted(os.listdir(SIDEWAYS_RESULTS_DIR)):
        f_path = os.path.join(SIDEWAYS_RESULTS_DIR, f_name)
        size = os.path.getsize(f_path)
        logger.info(f"    - {f_name} ({size:,} bytes)")


if __name__ == "__main__":
    main()
