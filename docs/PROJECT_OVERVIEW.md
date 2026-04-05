# Upbit Quant - 프로젝트 개요

## 소개

업비트 거래소 기반 암호화폐 자동매매 퀀트 트레이딩 시스템.
ADX 국면 판단으로 시장 상황에 자동 대응하며, Railway.app에서 24/7 운영.

- **저장소**: https://github.com/chochangwoo/upbit-quant
- **배포**: Railway.app (클라우드)
- **기술 스택**: Python 3.13, pyupbit, Supabase, Telegram Bot

---

## 핵심 아키텍처

```
Upbit API (시세/주문)
     ↓
[전략 라우터 v2] ← ADX 국면 판단 (Bull/Sideways/Bear)
     ↓
상승/횡보 → 적응형 거래량돌파 (AdaptiveVolumeStrategy)
하락      → 현금 보유 (CashHoldStrategy)
     ↓
[포트폴리오 실행기] → 매매 → Supabase 기록 → Telegram 알림
```

---

## 프로젝트 구조

```
upbit-quant/
├── src/                        # 실거래 로직
│   ├── api/upbit_client.py     # 업비트 API 래퍼
│   ├── strategies/             # 전략 구현
│   │   ├── strategy_router.py  # ⭐ ADX 국면 라우터 (v2)
│   │   ├── adaptive_volume_strategy.py  # 거래량돌파
│   │   ├── ma_cross.py         # 이동평균 크로스
│   │   ├── cash_hold.py        # 현금 보유
│   │   ├── risk_manager.py     # 리스크 관리
│   │   └── portfolio_strategy.py
│   ├── database/supabase_client.py  # DB 연동
│   ├── notifications/telegram_bot.py
│   └── trading/portfolio_executor.py
├── backtest/                   # 백테스팅 엔진
│   ├── engine.py               # 핵심 엔진
│   ├── strategies/             # 9개 백테스트 전략
│   ├── regime/                 # 국면 판단 백테스트
│   ├── ml/                     # LightGBM 전략
│   ├── optimizer/              # Optuna 최적화
│   └── alt_data/               # 공포탐욕, BTC도미넌스
├── notify/                     # 텔레그램 고도화
├── config/settings.yaml        # 전체 설정
├── main.py                     # 진입점
└── Procfile                    # Railway 배포
```

---

## 전략 체계

### 메인: 국면 라우터 v2 (ADX 기반)

| 국면 | 판단 기준 | 전략 | 백테스트 성과 |
|------|---------|------|-------------|
| 상승장 | ADX > 25, +DI > -DI | 거래량돌파 | +179.48% |
| 횡보장 | ADX ≤ 25 | 거래량돌파 | +25.72% |
| 하락장 | ADX > 25, -DI > +DI | 현금보유 | 손실 방지 |

- **확인 기간**: 2일간 동일 국면 유지 후 전환
- **연간 전환 빈도**: ~28.3회

### 적응형 거래량돌파

- 거래량 1.26배 이상 + 4일 고가 돌파 시 매수
- 대상: 13개 주요 코인 (BTC, ETH, SOL, XRP 등)
- 800일 백테스트: 수익률 +385.85%, 샤프 1.57, MDD -60.54%

### 이동평균 크로스 5/20

- 골든크로스(MA5>MA20) 매수, 데드크로스 매도
- 800일 백테스트: 수익률 +1,275.1%, 승률 31.1%

---

## 기술 스택

| 분야 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| 거래소 | pyupbit 0.2.33 |
| DB | Supabase (PostgreSQL, REST API) |
| 알림 | python-telegram-bot 20.7 |
| 스케줄 | schedule 1.2.1 |
| 로그 | loguru 0.7.2 |
| 데이터 | pandas 2.2.3, numpy 2.2.3 |
| ML | LightGBM 4.3.0, scikit-learn 1.4.0 |
| 최적화 | Optuna 3.5.0+ |

---

## 데이터베이스 스키마

### trades (매매 내역)
```sql
trades (id, strategy_name, ticker, side, price, amount, signal, ma5, ma20, created_at)
```

### strategy_switches (국면 전환)
```sql
strategy_switches (id, old_regime, new_regime, adx, plus_di, minus_di, confidence_days, switched_at)
```

### backtest_results
```sql
backtest_results (id, strategy_name, ticker, start_date, end_date, total_return, mdd, win_rate, sharpe_ratio, total_trades, avg_hold_days, created_at)
```

---

## 실행 방법

### 로컬 실행
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env  # API 키 입력
python main.py          # 시뮬레이션 모드
```

### Railway 배포
```bash
git push origin main    # 자동 배포
```

### 백테스트
```bash
python -m backtest.run_backtest
python -m backtest.run_router_backtest
python -m backtest.run_advanced_backtest
```

---

## 리스크 관리

- 최대 투자 비율: 95%
- 코인당 최대 비중: 30%
- MDD 한도: -15%
- 코인별 손절선: -10%
- 최소 주문 금액: 5,000원

---

## 개발 현황

### 완료
- ✅ ADX 기반 국면 라우터 v2
- ✅ 9개 백테스트 전략 + 4가지 코인 스크리너
- ✅ ML(LightGBM) + Optuna 최적화
- ✅ Railway 24/7 배포
- ✅ Telegram 알림 시스템

### 진행 중
- 🚧 v2 시뮬레이션 검증
- 🚧 일일 국면 리포트 봇

---

## 관련 프로젝트

| 프로젝트 | 역할 |
|----------|------|
| [salkkamalka-backtest](../salkkamalka-backtest/) | 백테스트 웹 플랫폼 |
| [crypto-agent-lab](../crypto-agent-lab/) | 멀티 에이전트 리서치/자동화 |
