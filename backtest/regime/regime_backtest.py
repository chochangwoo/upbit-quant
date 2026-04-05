"""
backtest/regime/regime_backtest.py - 국면별 백테스트 엔진

전략을 Bull/Bear/Sideways 국면별로 분리 평가합니다.

핵심 기능:
  1. 국면별 분리 백테스트: 각 국면에서의 전략 성과를 독립 평가
  2. 적응형 전략 백테스트: 국면에 따라 전략을 자동 전환
  3. 국면 전환 분석: 국면 전환 시점의 성과 변화 추적
  4. 종합 리포트: 국면별 비교 테이블 + 시각화
"""

import numpy as np
import pandas as pd
from loguru import logger

from backtest.engine import run_backtest
from backtest.metrics import calc_all_metrics
from backtest.regime.detector import detect_regimes


def run_regime_backtest(
    strategy,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    btc_prices,
    oos_window: int = 30,
    regime_method: str = "indicator",
) -> dict:
    """
    전략을 국면별로 분리하여 평가합니다.

    매개변수:
        strategy      : 전략 객체
        prices        : 전체 가격 DataFrame
        volumes       : 전체 거래량 DataFrame
        btc_prices    : BTC 가격 (국면 감지용)
        oos_window    : OOS 기간
        regime_method : 국면 감지 방법
    반환값:
        {
            "overall": 전체 기간 성과,
            "bull"   : 상승장 성과,
            "bear"   : 하락장 성과,
            "sideways": 횡보장 성과,
            "regimes": 국면 시계열,
            "regime_transitions": 국면 전환 분석,
        }
    """
    # 1. 국면 감지
    regimes = detect_regimes(btc_prices, method=regime_method)

    # 2. 전체 백테스트
    full_result = run_backtest(strategy, prices, volumes, oos_window)
    full_equity = full_result["equity_curve"]
    full_metrics = calc_all_metrics(full_equity) if len(full_equity) > 10 else {}

    # 3. 국면별 성과 분석
    regime_results = {}
    for regime_name in ["bull", "bear", "sideways"]:
        regime_dates = regimes[regimes == regime_name].index
        if len(regime_dates) < 5:
            continue

        # 해당 국면의 에쿼티 커브 구간 추출
        regime_equity = full_equity.reindex(regime_dates).dropna()
        if len(regime_equity) < 5:
            continue

        # 국면 내 구간들을 찾아서 성과 계산
        segments = _find_regime_segments(regimes, regime_name)
        segment_returns = []

        for seg_start, seg_end in segments:
            seg_equity = full_equity.loc[seg_start:seg_end].dropna()
            if len(seg_equity) >= 2:
                seg_return = seg_equity.iloc[-1] / seg_equity.iloc[0] - 1
                seg_days = (seg_end - seg_start).days
                segment_returns.append({
                    "시작": seg_start.date(),
                    "종료": seg_end.date(),
                    "기간(일)": seg_days,
                    "수익률": seg_return,
                })

        # 국면 전체 일별 수익률로 지표 계산
        daily_returns = []
        for seg_start, seg_end in segments:
            seg_equity = full_equity.loc[seg_start:seg_end].dropna()
            if len(seg_equity) >= 2:
                dr = seg_equity.pct_change().dropna()
                daily_returns.append(dr)

        if daily_returns:
            all_daily = pd.concat(daily_returns)
            total_days = len(all_daily)
            avg_return = all_daily.mean() * 365
            vol = all_daily.std() * np.sqrt(365)
            sharpe = avg_return / vol if vol > 0 else 0
            win_rate = (all_daily > 0).mean()
            cum_return = (1 + all_daily).prod() - 1

            # MDD 계산 (연결된 에쿼티로)
            cum_equity = (1 + all_daily).cumprod()
            peak = cum_equity.cummax()
            mdd = ((cum_equity - peak) / peak).min()
        else:
            sharpe = 0
            cum_return = 0
            mdd = 0
            win_rate = 0
            total_days = 0

        regime_results[regime_name] = {
            "누적수익률": cum_return,
            "샤프비율": sharpe,
            "MDD": mdd,
            "승률": win_rate,
            "총일수": total_days,
            "구간수": len(segments),
            "구간상세": segment_returns,
        }

    # 4. 국면 전환 분석
    transitions = _analyze_transitions(regimes, full_equity)

    return {
        "overall": full_metrics,
        "regimes": regimes,
        "regime_results": regime_results,
        "regime_transitions": transitions,
        "strategy_name": strategy.name,
        "equity_curve": full_equity,
    }


def _find_regime_segments(regimes: pd.Series, target_regime: str) -> list:
    """연속된 국면 구간을 찾습니다."""
    segments = []
    in_segment = False
    seg_start = None

    for date, regime in regimes.items():
        if regime == target_regime and not in_segment:
            seg_start = date
            in_segment = True
        elif regime != target_regime and in_segment:
            segments.append((seg_start, prev_date))
            in_segment = False
        prev_date = date

    if in_segment:
        segments.append((seg_start, prev_date))

    return segments


def _analyze_transitions(regimes: pd.Series, equity: pd.Series) -> list:
    """국면 전환 시점의 성과를 분석합니다."""
    transitions = []
    prev_regime = None

    for i, (date, regime) in enumerate(regimes.items()):
        if prev_regime is not None and regime != prev_regime:
            # 전환 전후 10일 성과
            idx = regimes.index.get_loc(date)
            before_start = max(0, idx - 10)
            after_end = min(len(regimes) - 1, idx + 10)

            before_equity = equity.iloc[before_start:idx].dropna()
            after_equity = equity.iloc[idx:after_end + 1].dropna()

            before_return = (before_equity.iloc[-1] / before_equity.iloc[0] - 1) if len(before_equity) >= 2 else 0
            after_return = (after_equity.iloc[-1] / after_equity.iloc[0] - 1) if len(after_equity) >= 2 else 0

            transitions.append({
                "날짜": date.date(),
                "전환": f"{prev_regime} → {regime}",
                "전환전_10일_수익률": before_return,
                "전환후_10일_수익률": after_return,
            })

        prev_regime = regime

    return transitions


# ═══════════════════════════════════════════════════════
# 적응형 전략 (국면별 전략 전환)
# ═══════════════════════════════════════════════════════

class AdaptiveRegimeStrategy:
    """
    국면에 따라 전략을 자동 전환하는 적응형 전략

    규칙:
      - Bull (상승장)  : 공격적 전략 실행 (모멘텀 등)
      - Bear (하락장)  : 방어적 (현금 비중 높임 or 포지션 축소)
      - Sideways (횡보장): 보수적 (거래 최소화 or 평균회귀)
    """

    def __init__(
        self,
        bull_strategy,
        bear_strategy,
        sideways_strategy,
        btc_prices,
        regime_method: str = "indicator",
        cash_ratio_bear: float = 0.5,
    ):
        """
        매개변수:
            bull_strategy     : 상승장 전략
            bear_strategy     : 하락장 전략 (None이면 현금 보유)
            sideways_strategy : 횡보장 전략
            btc_prices        : BTC 가격 (국면 감지용)
            regime_method     : 국면 감지 방법
            cash_ratio_bear   : 하락장 시 현금 비율 (0.5 = 50% 현금)
        """
        self.bull_strategy = bull_strategy
        self.bear_strategy = bear_strategy
        self.sideways_strategy = sideways_strategy
        self.btc_prices = btc_prices
        self.regime_method = regime_method
        self.cash_ratio_bear = cash_ratio_bear
        self.name = f"적응형({bull_strategy.name}/{sideways_strategy.name})"

        # 국면 사전 계산
        self.regimes = detect_regimes(btc_prices, method=regime_method)

    def get_weights(self, prices, volumes, date, lookback_prices):
        """
        현재 국면에 맞는 전략으로 비중을 계산합니다.
        """
        # 현재 국면 확인
        if date in self.regimes.index:
            current_regime = self.regimes.loc[date]
        else:
            # 가장 가까운 이전 날짜의 국면 사용
            prior = self.regimes.loc[:date]
            current_regime = prior.iloc[-1] if len(prior) > 0 else "sideways"

        # 국면별 전략 선택
        if current_regime == "bull":
            weights = self.bull_strategy.get_weights(prices, volumes, date, lookback_prices)

        elif current_regime == "bear":
            if self.bear_strategy is not None:
                weights = self.bear_strategy.get_weights(prices, volumes, date, lookback_prices)
                # 하락장: 비중 축소
                if len(weights) > 0:
                    weights = weights * (1 - self.cash_ratio_bear)
            else:
                # 전략 없으면 현금 보유 (빈 비중)
                weights = pd.Series(dtype=float)

        else:  # sideways
            weights = self.sideways_strategy.get_weights(prices, volumes, date, lookback_prices)

        return weights


# ═══════════════════════════════════════════════════════
# 종합 비교 리포트
# ═══════════════════════════════════════════════════════

def run_regime_comparison(
    strategies: list,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    btc_prices,
    oos_window: int = 30,
    regime_method: str = "indicator",
) -> pd.DataFrame:
    """
    여러 전략을 국면별로 비교합니다.

    매개변수:
        strategies    : [(이름, 전략객체)] 리스트
        prices        : 가격 데이터
        volumes       : 거래량 데이터
        btc_prices    : BTC 가격
        oos_window    : OOS 기간
        regime_method : 국면 감지 방법
    반환값:
        비교 DataFrame
    """
    rows = []

    for name, strategy in strategies:
        logger.info(f"[국면비교] {name} 백테스트 중...")

        result = run_regime_backtest(
            strategy, prices, volumes, btc_prices,
            oos_window, regime_method,
        )

        # 전체 성과
        overall = result["overall"]
        row = {
            "전략": name,
            "국면": "전체",
            "누적수익률": overall.get("누적수익률", 0),
            "샤프비율": overall.get("샤프비율", 0),
            "MDD": overall.get("MDD", 0),
            "승률": overall.get("일별승률", 0),
            "일수": len(result["equity_curve"]),
        }
        rows.append(row)

        # 국면별 성과
        for regime_name in ["bull", "bear", "sideways"]:
            if regime_name in result["regime_results"]:
                rr = result["regime_results"][regime_name]
                rows.append({
                    "전략": name,
                    "국면": regime_name,
                    "누적수익률": rr["누적수익률"],
                    "샤프비율": rr["샤프비율"],
                    "MDD": rr["MDD"],
                    "승률": rr["승률"],
                    "일수": rr["총일수"],
                })

    df = pd.DataFrame(rows)

    # 요약 출력
    logger.info("\n" + "=" * 70)
    logger.info("국면별 전략 비교 결과")
    logger.info("=" * 70)

    for regime in ["전체", "bull", "bear", "sideways"]:
        regime_df = df[df["국면"] == regime]
        if regime_df.empty:
            continue
        emoji = {"전체": "📊", "bull": "📈", "bear": "📉", "sideways": "↔️"}.get(regime, "")
        logger.info(f"\n  {emoji} {regime}")
        for _, r in regime_df.iterrows():
            logger.info(
                f"    {r['전략']:>25s}: "
                f"샤프 {r['샤프비율']:>6.2f} | "
                f"수익률 {r['누적수익률']:>7.1%} | "
                f"MDD {r['MDD']:>7.1%} | "
                f"승률 {r['승률']:>5.1%} | "
                f"{r['일수']:>4.0f}일"
            )

    return df
