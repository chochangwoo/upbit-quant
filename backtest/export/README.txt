=== 백테스트 데이터 메타정보 ===
생성일시: 2026-03-28 22:23:58
데이터 소스: Upbit API (pyupbit)
수집 방식: pyupbit.get_ohlcv(ticker, interval="day", count=200) × 페이지네이션
기간: 2022-02-18 ~ 2026-03-28 (1,500 거래일)
코인: 13종 (BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, LINK, DOT, XLM, NEAR, UNI, POL)
UNI 참고: 2024-10-22부터 523일만 존재 (나머지 12코인은 1500일 전부)
시간 기준: 업비트 일봉 (매일 09:00 KST)
비용 설정: 수수료 편도 0.05% + 슬리피지 편도 0.05% = 편도 총 0.10%
시뮬레이터: RealisticSimulator (자본금 1,000만원, 복리)

=== 파일 목록 ===
prices_full.csv      - 종가 (1500일 × 13코인)
highs.csv            - 고가 (1500일 × 13코인)
lows.csv             - 저가 (1500일 × 13코인)
opens.csv            - 시가 (1500일 × 13코인)
volumes_full.csv     - 거래대금 KRW (1500일 × 13코인)
coin_volumes.csv     - 거래량 코인수량 (1500일 × 13코인)
regime_classification.csv - BTC 기준 국면 분류 (SMA/ADX)
backtest_results_summary.csv - 전략별 백테스트 결과 요약
regime_performance_detail.csv - 국면별 상세 성과
README.txt           - 이 파일
