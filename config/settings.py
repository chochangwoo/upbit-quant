"""
전역 설정값 관리
.env 파일의 값을 읽어 사용하기 편하게 정리합니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# 매매 대상 코인 목록
TARGET_COINS = os.getenv("TARGET_COINS", "KRW-BTC").split(",")

# 1회 매수 금액 (원)
ORDER_AMOUNT = int(os.getenv("ORDER_AMOUNT", "10000"))

# 변동성 돌파 K값
VOLATILITY_K = float(os.getenv("VOLATILITY_K", "0.5"))

# 실거래 여부
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

# 매도 시간: 오전 8시 50분
SELL_HOUR = 8
SELL_MINUTE = 50
