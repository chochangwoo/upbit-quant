# 코인 선별 전략 백테스팅 시스템 구현 요청

## 배경

현재 `upbit-quant` 프로젝트에서 MA Cross 5/20 전략으로 KRW-BTC 단일 코인 자동매매를 Railway.app에서 운영 중이다. 이제 **"어떤 코인을 매매할 것인가"**를 자동으로 선별하는 퀀트 전략을 추가하려 한다.

기존 시스템이 "하나의 코인 안에서 타이밍을 잡는" 전략이라면, 이번에 구현할 것은 **"Upbit 상장 코인 중 단기적으로 상승 가능성이 높은 코인을 자동으로 골라내는"** 전략이다.

---

## 구현 요청 사항

### 1. 코인 선별 전략 4종 구현

아래 4가지 코인 선별(Screening) 전략을 각각 독립된 클래스로 구현해줘.

#### 전략 A: 모멘텀 스크리닝 (Momentum Screening)
- Upbit KRW 마켓 전체 코인 대상
- 최근 N일(기본 7일) 수익률을 계산
- 수익률 상위 K개(기본 5개) 코인을 선별
- 매 리밸런싱 주기마다 상위 코인을 교체
- 핵심 지표: `(현재가 - N일전 종가) / N일전 종가`

#### 전략 B: 거래량 급증 감지 (Volume Surge Detection)  
- 각 코인의 20일 평균 거래량 대비 당일 거래량 비율(Volume Ratio) 계산
- Volume Ratio가 높은 상위 K개 코인 선별
- 거래량 급증은 가격 변동의 선행 신호로 활용
- 핵심 지표: `당일 거래량 / 20일 평균 거래량`

#### 전략 C: 평균회귀 (Mean Reversion)
- RSI(14) 기준으로 과매도 상태인 코인을 선별
- RSI가 가장 낮은(과매도) 상위 K개 코인 매수
- 단기 과도 하락 후 반등을 기대하는 역추세 전략
- 핵심 지표: `RSI(14)` — 낮을수록 우선순위 높음

#### 전략 D: 복합 스코어링 (Composite Scoring)
- 모멘텀(50%) + 거래량(30%) + 저변동성(20%) 가중 합산
- 각 지표별 순위(rank)를 매긴 뒤 가중 합산하여 종합 점수 산출
- 변동성은 20일 일간 수익률의 표준편차 사용 (낮을수록 좋음)
- 핵심: `composite_score = momentum_rank × 0.5 + volume_rank × 0.3 + volatility_rank × 0.2`

---

### 2. 백테스팅 엔진 구현

#### 데이터 수집
```
- Upbit API(`pyupbit`)로 KRW 마켓 전체 코인의 일봉(day candle) 데이터 수집
- 수집 기간: 최소 120일 (설정 가능)
- 수집 항목: 날짜, 시가, 고가, 저가, 종가, 거래량
- API 호출 제한 준수: 코인당 0.15초 sleep
- 수집된 데이터를 로컬 CSV 또는 Supabase에 캐싱하여 재사용
```

#### 백테스팅 로직
```
- 초기 자본금: 설정 가능 (기본 1,000,000원)
- 리밸런싱 주기: 설정 가능 (매일 / 3일 / 7일)
- 선별 코인 수(K): 설정 가능 (기본 5개)
- 매매 방식: 리밸런싱 시점에 기존 보유 전량 매도 → 선별된 K개 코인에 균등 분배 매수
- 수수료: 매수/매도 각 0.05% 반영
- 슬리피지: 0.1% 추가 반영 (선택)
```

#### 성과 지표 계산
```
- 총 수익률 (Total Return %)
- 최대 낙폭 (MDD: Maximum Drawdown %)
- 샤프 비율 (Sharpe Ratio, 연환산, 무위험이자율 3.5%)
- 승률 (Win Rate %): 매도 시 매수가 대비 수익인 비율
- 총 거래 횟수
- 일별 포트폴리오 가치 (equity curve)
- 전략별 최근 매매 내역 (코인명, 날짜, 스코어)
```

---

### 3. 전략 비교 리포트 생성

4가지 전략을 동일 조건(기간, 코인 수, 리밸런싱 주기)으로 백테스팅한 뒤:

1. **콘솔 요약 리포트**: 전략별 수익률/MDD/샤프/승률을 표 형태로 출력
2. **그래프 저장**: matplotlib으로 4가지 전략의 누적 수익률 곡선을 하나의 차트에 겹쳐서 `backtest/results/` 폴더에 PNG 저장
3. **Supabase 저장**: `backtest_results` 테이블에 각 전략의 결과 지표 저장
4. **텔레그램 전송**: 비교 결과 요약 + 그래프 이미지를 텔레그램으로 전송
5. **CSV 내보내기**: 전략별 일별 equity curve를 CSV로 저장

---

### 4. 파일 구조

기존 프로젝트 구조에 맞춰서 아래 파일들을 생성/수정해줘:

```
backtest/
├── coin_screener/                    # ← 새로 생성
│   ├── __init__.py
│   ├── data_collector.py             # Upbit 전체 코인 일봉 데이터 수집 + 캐싱
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_screener.py          # 스크리너 추상 클래스
│   │   ├── momentum_screener.py      # 전략 A: 모멘텀
│   │   ├── volume_screener.py        # 전략 B: 거래량 급증
│   │   ├── mean_reversion_screener.py # 전략 C: 평균회귀
│   │   └── composite_screener.py     # 전략 D: 복합 스코어링
│   ├── backtest_engine.py            # 코인 선별 전략 전용 백테스팅 엔진
│   ├── report_generator.py           # 비교 리포트 생성 (콘솔 + 그래프 + CSV)
│   └── run_backtest.py               # 실행 진입점 (CLI)
```

---

### 5. CLI 인터페이스

`backtest/coin_screener/run_backtest.py`를 실행할 때 아래 옵션을 지원해줘:

```bash
# 기본 실행 (전략 4종 비교)
python -m backtest.coin_screener.run_backtest

# 파라미터 지정
python -m backtest.coin_screener.run_backtest \
  --days 60 \
  --top-n 5 \
  --rebalance 3 \
  --capital 1000000 \
  --fee 0.0005 \
  --strategies momentum,volume,meanrev,composite \
  --save-csv \
  --send-telegram \
  --save-db

# 단일 전략만 테스트
python -m backtest.coin_screener.run_backtest \
  --strategies momentum \
  --days 90 \
  --top-n 3

# 도움말
python -m backtest.coin_screener.run_backtest --help
```

CLI 옵션:
- `--days`: 백테스트 기간 (기본 60)
- `--top-n`: 선별 코인 수 (기본 5)
- `--rebalance`: 리밸런싱 주기 일수 (기본 3)
- `--capital`: 초기 자본금 (기본 1000000)
- `--fee`: 편도 수수료율 (기본 0.0005)
- `--strategies`: 실행할 전략 (콤마 구분, 기본 전체)
- `--save-csv`: CSV 저장 여부
- `--send-telegram`: 텔레그램 전송 여부
- `--save-db`: Supabase 저장 여부
- `--cache-dir`: 데이터 캐시 디렉토리 (기본 backtest/coin_screener/cache/)

---

### 6. 기술 요구사항

- Python 3.11+
- 기존 프로젝트의 `.env` 환경변수 재사용 (UPBIT 키, SUPABASE 키, TELEGRAM 키)
- `pyupbit`으로 데이터 수집
- `pandas`로 데이터 처리 및 지표 계산
- `matplotlib`으로 차트 생성
- `argparse`로 CLI 파싱
- `loguru`로 로깅
- 모든 주석과 docstring은 한국어
- 에러 발생 시 텔레그램 알림 전송
- API 호출 실패 시 3회 재시도 후 스킵
- 데이터 캐싱: 한 번 수집한 데이터는 로컬 파일에 저장하여 반복 실행 시 재수집 방지

---

### 7. 콘솔 출력 예시

```
================================================================
        코인 선별 전략 백테스팅 결과 비교
================================================================
기간: 2025-12-01 ~ 2026-02-28 (90일)
선별 코인 수: 5개 | 리밸런싱: 3일 | 초기자본: 1,000,000원
대상 코인: Upbit KRW 마켓 전체 (수집 완료: 87개)
================================================================

 순위  전략              수익률      MDD       샤프    승률    거래수
─────────────────────────────────────────────────────────────────
  1위  복합 스코어링     +12.45%    -8.32%    1.82    58.3%   90
  2위  모멘텀 스크리닝   +9.78%     -11.56%   1.24    52.1%   90
  3위  거래량 급증       +5.12%     -15.23%   0.67    48.7%   90
  4위  평균회귀          -2.34%     -18.91%   -0.31   41.2%   90
─────────────────────────────────────────────────────────────────

🏆 최우수 전략: 복합 스코어링 (+12.45%)

📊 차트 저장: backtest/results/coin_screening_comparison_20260228.png
📋 CSV 저장: backtest/results/equity_curves_20260228.csv
💾 DB 저장: Supabase backtest_results 테이블 저장 완료
📱 텔레그램 전송 완료
================================================================
```

---

### 8. 추가 고려사항

- 코인 필터링: 일평균 거래량이 너무 적은 코인(예: 1억원 미만)은 제외
- 상장폐지/거래정지 코인 자동 제외
- 데이터 부족 코인(20일 미만) 자동 제외
- 백테스팅 시 미래 데이터 참조(look-ahead bias) 방지
- 리밸런싱 시점의 가격은 해당 날짜 종가 사용

---

## 실행 후 확인 사항

1. `python -m backtest.coin_screener.run_backtest` 실행 시 에러 없이 4가지 전략 비교 결과가 출력되는지 확인
2. `backtest/results/` 폴더에 그래프 PNG와 CSV가 정상 생성되는지 확인
3. 텔레그램으로 결과가 전송되는지 확인 (--send-telegram 옵션)
4. 다른 파라미터 조합으로 재실행 시 결과가 달라지는지 확인
