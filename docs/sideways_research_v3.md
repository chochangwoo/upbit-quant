# 횡보장 대응 리서치 → 라우터 v3 (2026-04-07)

> 한 줄 요약: 횡보장 대응 신규 전략 4종을 walk-forward 검증한 결과, **신규 전략은 모두 폐기**하고
> 기존 baseline 에 **BTC SMA200 + 30일 모멘텀 -3%** 하락 필터를 추가한 **라우터 v3** 를 채택.
> WF 21fold 평균: 수익 +6.56% → +9.94%, MDD -18.5% → -12.7%, worst -41.9% → -24.3%.

---

## 0. 출발점 — 풀고 싶었던 문제

라우터 v2 (ADX 국면 + 거래량돌파) 의 약점:
- ADX 하락장 필터가 늦게 반응 → 큰 손실 fold 다수 발생
- 횡보장에서 거래량돌파가 휩소 손실
- 검증 방법론: in-sample 백테스트만 → 과적합 의심

목표:
1. 횡보장에 효과적인 다른 전략 후보 검증
2. Walk-forward 로 OOS 안정성 확보
3. **MDD 낮추면서 ROI 도 같이 올릴 수 있는 방향** 탐색

---

## 1. 인프라 구축 (재사용 가능한 백테스트 자산)

| 파일 | 역할 |
|---|---|
| `backtest/walk_forward.py` | 범용 walk-forward 하네스 (`split_walk_forward`, `run_walk_forward`) |
| `backtest/regime/sideways_filter.py` | ADX + BB-width + 박스폭 합성 횡보 마스크 |
| `backtest/strategies/keltner_squeeze.py` | TTM Squeeze 단순판 |
| `backtest/strategies/grid_trading.py` | 일봉 high/low 근사 그리드 |
| `backtest/run_sideways_wf.py` | 마스크/전 구간 walk-forward 비교 CLI |
| `backtest/run_baseline_sensitivity.py` | SMA × mom30 격자 민감도 분석 |
| `backtest/metrics.py` | `calc_profit_factor` 추가 |

설정: `train=120일, test=60일, step=60일 (비겹침), 21 fold`, 데이터 1500일 13코인.

---

## 2. 전략 후보별 검증 결과 (시간순)

### 2-1. BB+RSI 평균회귀 — 폐기

기존 `BBRSIMeanReversionBT` 재활용. 횡보 마스크 한정 walk-forward.

| 지표 | 값 |
|---|---|
| 평균 수익률 | **-1.48%** |
| 평균 Sharpe | -0.42 |
| 거래수 | 49 |

**판단**: 메모리상 기존 평가("횡보 전용 비추, 하락 반등에만 유효")와 일치. 13개 KRW 코인이 BTC 와
고상관이라 mean reversion 자산으로 부적합. **폐기**.

### 2-2. Keltner Squeeze — 폐기 (생존편향)

TTM Squeeze 단순판. squeeze ON→OFF 전환 + 양 모멘텀 진입.

**횡보 마스크 한정** WF: 평균 +1.86%, Sharpe 0.58 — baseline 보다 좋아 보였음.
**마스크 제거 전 구간** WF: 평균 **-0.88%**, Sharpe 0.79.

**판단**: 마스크가 squeeze 후 상승 fold 만 운 좋게 골라낸 **생존편향**. 본질적으로 횡보 전략이
아니라 "변동성 확장 시작점" 진입 전략이라 횡보 한정 평가가 부적절했음. **폐기**.

### 2-3. Grid Trading — 폐기 (분산 효과 없음)

13코인 독립 그리드. spacing 2.5%, 5 levels, 30일 reanchor. 일봉 high/low 근사 체결.

| 지표 | 값 |
|---|---|
| 평균 수익률 | -0.03% |
| 평균 MDD | **-5.8%** (3종 중 최저) |
| Worst fold | **-8.67%** (3종 중 최저) |
| 거래수 | 11,075 |

수익은 break-even 이지만 **MDD/worst 가 압도적으로 낮음** → baseline 과 결합 시 분산 효과 가능성 검토.

**상관계수 분석** (21 fold OOS 수익률):

| | baseline | baseline_live | grid |
|---|---|---|---|
| baseline | 1.000 | 0.908 | 0.673 |
| baseline_live | 0.908 | 1.000 | **0.574** |
| grid | 0.673 | 0.574 | 1.000 |

50:50 결합 시 표준편차 절감률 **3.9%** (단순합 23.19% → 결합 22.27%).
mean/std 비율 0.157 → 0.146 으로 **악화**.

**원인**: grid 도 long-only 라 시장 베타에 노출. BTC 약세장에서 baseline 과 동시에 손실.
업비트 KRW 마켓에서 진짜 음의 상관 자산을 만들려면 short 가능 거래소 필요. **폐기**.

---

## 3. 진짜 레버는 baseline 에 있었다

신규 전략으로 분산이 안 된다면 → **baseline 자체의 약점**을 파야 함.

### 3-1. 손실 fold 진단

baseline_live (라우터 v2 동등: ADX bear → cash) worst 9 fold 분석:

| Fold | 손실 | ADX bear 발동 | BTC<SMA200 | mom30<-5% |
|---|---|---|---|---|
| 2022-09 | **-41.86%** | 5/60 | **60/60** | 18/60 |
| 2025-12 | **-22.71%** | 44/60 | **60/60** | 31/60 |
| 2024-03 | -28.67% | 14/60 | 0/60 | 17/60 |
| 2023-07 | -27.94% | 20/60 | 22/60 | 32/60 |
| 2024-05 | -12.08% | 19/60 | 2/60 | 25/60 |
| 2025-05 | -13.00% | 2/60 | 0/60 | 3/60 |

**핵심 발견**: 가장 큰 손실 두 fold (-41.86, -22.71) 는 **BTC<SMA200 이 100% 커버**.
ADX bear 는 lag 가 커서 못 잡음. SMA200 + mom30 보조 필터 추가가 자명한 처방.

### 3-2. 변형 3종 walk-forward (전 구간)

| 전략 | 평균 수익률 | 평균 MDD | Worst | 거래 |
|---|---|---|---|---|
| baseline_live (ADX 만) | +6.56% | -18.5% | -41.86% | 1,245 |
| baseline + SMA200 | +8.65% | -14.6% | -28.67% | 1,042 |
| baseline + mom30(-5%) | +7.28% | -16.8% | -36.80% | 1,138 |
| **baseline + SMA200 + mom30** | **+8.91%** | **-13.2%** | **-28.67%** | **966** |

combo (SMA200 OR mom30) 가 **모든 지표에서 우월**. 거래수 -22% 로 수수료 부담도 감소.

### 3-3. 민감도 격자 (overfitting 체크)

SMA period {150, 200, 250} × mom30 threshold {-3%, -5%, -7%} = 9개 조합:

| SMA | mom | 평균수익 | 평균MDD | worst |
|---|---|---|---|---|
| 150 | -3% | +9.88% | -13.2% | -26.4% |
| 200 | -3% | **+9.94%** | **-12.7%** | -24.3% |
| 200 | -5% | +8.91% | -13.2% | -23.3% |
| 250 | -3% | +11.06% | -13.2% | -24.3% |
| ... | ... | ... | ... | ... |

**관찰**:
- 9개 격자 **모두** baseline_live (+6.56%, -18.5%) 압도 → 견고함
- 격자 내 평균수익 표준편차 ≈ 0.78%p, 평균 MDD 표준편차 ≈ 0.6%p → 임계값 운 의존도 낮음
- mom30 임계값 -3% > -5% > -7% 단조 우세 (작을수록 민감 → 손실 회피 효과 큼)
- SMA250 가 single best 지만 1%p 차이 → **과적합 위험으로 학계 표준 200dma 채택**

**최종 선택**: `SMA200 + mom30(-3%)` — 수익 극대화 + 학계 표준값.

---

## 4. 라우터 v3 라이브 적용

### 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `config/settings.yaml` | `bear_filter` 섹션 신설 (enabled=true, sma=200, mom_window=30, mom_threshold=-0.03) |
| `src/strategies/strategy_router.py` | `__init__` bear_filter cfg 로드, `ohlcv_count=230` 확장, `detect_regime` 에 SMA/mom 보조 필터 추가, 텔레그램 메시지에 sma/mom/triggers 노출 |
| `backtest/run_sideways_wf.py` | `_is_cash` 디폴트 mom30 임계값 -5% → -3% |
| `backtest/run_baseline_sensitivity.py` | 신규 (민감도 분석 CLI) |

### v3 룰

```
1. ADX > 25 AND -DI > +DI                            → bear (현금)
2. (1번 통과) AND BTC < SMA200                       → bear (현금)  ← v3 추가
3. (1,2 통과) AND BTC 30일 모멘텀 < -3%              → bear (현금)  ← v3 추가
4. ADX > 25 AND +DI > -DI AND 위 필터 통과           → bull (거래량돌파)
5. ADX <= 25 AND 위 필터 통과                        → sideways (거래량돌파)
```

기존 v2 의 `confirmation_days=2` 는 ADX 전환에만 적용. SMA/mom 필터는 즉시 발동.

### 라이브 검증 (실시간 BTC 데이터, 2026-04-07)

```
BTC 현재가:    102,482,000원
SMA200:        131,535,110원   ← -22% 이격
ADX:           11.91          (< 25, 약추세)
mom30:         +4.74%          (-3% 통과)

v2 판정 → sideways (거래량돌파)
v3 판정 → bear    (BTC<SMA200 발동)
```

**⚠️ 즉, v3 배포 시 봇이 즉시 모든 포지션 청산 후 현금 보유로 진입**. 백테스트 의도와 일치.

---

## 5. 폐기된 가설 정리

| 가설 | 결과 | 폐기 사유 |
|---|---|---|
| BB+RSI 평균회귀가 횡보장 보완 | OOS 평균 -1.48% | 13코인 BTC 고상관, mean reversion 자산 부족 |
| Keltner Squeeze 가 횡보 친화 | 마스크 제거 시 -0.88% | 생존편향 — 본질은 변동성 확장 진입 전략 |
| Grid 가 baseline 과 분산 효과 | ρ=+0.57, std 절감 3.9% | long-only 시장 베타 노출, 음의 상관 자산 부재 |

---

## 6. 남은 과제

1. **chop 손실은 여전히 뚫림** — 2023-07/2024-03/2024-05/2025-05 등 trend 필터로 차단 불가한 범위 손실. 다른 차원(코인 셀렉션, 포지션 사이징, 진입 타이밍)에서 풀어야 함.
2. **σSharpe 65 의 단일 fold 의존** — 2024-11 fold 한 개가 +150% 로 평균을 들어올림. 그 fold 빼면 평균 수익률 큰 폭 하락.
3. **Railway 배포 후 텔레그램 알림 검증** — bear_filter 발동 시 sma/mom/triggers 가 메시지에 정상 표시되는지.
4. **백테스트와 라이브의 차이** — confirmation_days 처리, 리밸런싱 주기, 슬리피지 등 — 라이브 첫 1주 결과를 백테스트와 비교해 캘리브레이션 필요.

---

## 7. 관련 산출물

- 코드:
  - `backtest/walk_forward.py`, `backtest/run_sideways_wf.py`, `backtest/run_baseline_sensitivity.py`
  - `backtest/regime/sideways_filter.py`
  - `backtest/strategies/{keltner_squeeze, grid_trading}.py`
- 결과 CSV (자동 타임스탬프):
  - `backtest/results/sideways_wf_*.csv`
  - `backtest/results/baseline_sensitivity_*.csv`
- 라이브 변경:
  - `src/strategies/strategy_router.py`
  - `config/settings.yaml`
