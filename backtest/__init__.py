"""
backtest/ - 멀티 코인 포트폴리오 백테스트 패키지

모듈 구성:
  - data_collector: 업비트 API 데이터 수집 (13개 코인, 800일)
  - strategies/   : 3가지 포트폴리오 전략 (12개 파라미터 조합)
  - engine        : Walk-Forward 롤링 윈도우 백테스트 엔진
  - metrics       : 8가지 성과 지표 계산
  - validators    : 통계적 검증 (몬테카를로, 부트스트랩, 레짐분석)
  - report        : 시각화 (5종 차트) + 텔레그램 + DB 저장
  - run_backtest  : 메인 실행 스크립트

실행:
  python backtest/run_backtest.py
"""
