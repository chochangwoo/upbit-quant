"""
backtest/strategies/__init__.py - 전략 모듈 초기화

9가지 포트폴리오 전략과 전체 파라미터 조합을 제공합니다.

전략 목록:
  1. 크로스섹셔널 모멘텀 (6개 조합)
  2. 리스크 패리티 (2개 조합)
  3. 통합 전략 (4개 조합)
  4. RSI 역추세 (4개 조합)
  5. 듀얼 모멘텀 (4개 조합)
  6. 거래량 브레이크아웃 (6개 조합)
  7. MA 크로스 로테이션 (6개 조합)
  8. 모멘텀 반전 (4개 조합)
  9. 적응형 모멘텀 (2개 조합)
  -> 총 38개 전략 x 파라미터 조합
"""

from .cross_sectional_momentum import CrossSectionalMomentum
from .risk_parity import RiskParityLite
from .combined_strategy import CombinedStrategy
from .rsi_mean_reversion import RSIMeanReversion
from .dual_momentum import DualMomentum
from .volume_breakout import VolumeBreakout
from .ma_cross_rotation import MACrossRotation
from .momentum_reversal import MomentumReversal
from .adaptive_momentum import AdaptiveMomentum


def get_all_strategy_configs() -> list:
    """
    전체 전략 x 파라미터 조합을 반환합니다.

    반환값:
        list[dict] - 38개의 전략 설정
    """
    configs = []

    # 1. 크로스섹셔널 모멘텀 (3 x 2 = 6개)
    for lookback in [7, 14, 21]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": CrossSectionalMomentum(lookback=lookback, top_k=top_k),
                "params": {"lookback": lookback, "top_k": top_k},
            })

    # 2. 리스크 패리티 (2개)
    for vol_lookback in [20, 60]:
        configs.append({
            "strategy": RiskParityLite(vol_lookback=vol_lookback),
            "params": {"vol_lookback": vol_lookback},
        })

    # 3. 통합 전략 (2 x 2 = 4개)
    for mom_lookback in [7, 14]:
        for top_k in [5, 7]:
            configs.append({
                "strategy": CombinedStrategy(
                    mom_lookback=mom_lookback, vol_lookback=20, top_k=top_k
                ),
                "params": {"mom_lookback": mom_lookback, "vol_lookback": 20, "top_k": top_k},
            })

    # 4. RSI 역추세 (2 x 2 = 4개)
    for threshold in [30, 40]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": RSIMeanReversion(rsi_period=14, threshold=threshold, top_k=top_k),
                "params": {"rsi_period": 14, "threshold": threshold, "top_k": top_k},
            })

    # 5. 듀얼 모멘텀 (2 x 2 = 4개)
    for short_lb in [7, 14]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": DualMomentum(short_lookback=short_lb, long_lookback=60, top_k=top_k),
                "params": {"short_lookback": short_lb, "long_lookback": 60, "top_k": top_k},
            })

    # 6. 거래량 브레이크아웃 (3 x 2 = 6개)
    for vol_ratio in [1.3, 1.5, 2.0]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": VolumeBreakout(price_lookback=5, vol_ratio=vol_ratio, top_k=top_k),
                "params": {"price_lookback": 5, "vol_ratio": vol_ratio, "top_k": top_k},
            })

    # 7. MA 크로스 로테이션 (3 x 2 = 6개)
    for short_ma, long_ma in [(5, 20), (10, 30), (3, 10)]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": MACrossRotation(short_ma=short_ma, long_ma=long_ma, top_k=top_k),
                "params": {"short_ma": short_ma, "long_ma": long_ma, "top_k": top_k},
            })

    # 8. 모멘텀 반전 (2 x 2 = 4개)
    for mid_lb in [20, 30]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": MomentumReversal(mid_lookback=mid_lb, short_lookback=5, top_k=top_k),
                "params": {"mid_lookback": mid_lb, "short_lookback": 5, "top_k": top_k},
            })

    # 9. 적응형 모멘텀 (2개)
    for top_k in [3, 5]:
        configs.append({
            "strategy": AdaptiveMomentum(short_lb=5, long_lb=30, top_k=top_k),
            "params": {"short_lb": 5, "long_lb": 30, "top_k": top_k},
        })

    return configs
