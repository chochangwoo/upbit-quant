"""
전역 설정값 관리
settings.yaml과 .env 파일의 값을 읽어 사용하기 편하게 정리합니다.
"""
import os
import yaml
from dotenv import load_dotenv

load_dotenv()

# ─── settings.yaml 로드 ────────────────────────────────
_yaml_path = os.path.join(os.path.dirname(__file__), "settings.yaml")
with open(_yaml_path, "r", encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)

# ─── 전략 설정 (MA 크로스 5/20) ───────────────────────
STRATEGY_NAME  = _cfg["strategy"]["name"]           # "ma_cross"
SHORT_WINDOW   = _cfg["strategy"]["short_window"]    # 5
LONG_WINDOW    = _cfg["strategy"]["long_window"]     # 20
TICKER         = _cfg["strategy"]["ticker"]          # "KRW-BTC"
INVEST_RATIO   = _cfg["strategy"]["invest_ratio"]    # 0.95

# ─── 거래 기본 설정 ────────────────────────────────────
# LIVE_TRADING은 .env 우선, 없으면 settings.yaml 값 사용
LIVE_TRADING = os.getenv("LIVE_TRADING", str(_cfg["trading"]["live_trading"])).lower() == "true"
