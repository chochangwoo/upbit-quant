# 업비트 자동매매 시스템 - 프로젝트 규칙

## 프로젝트 개요
- **목적**: 업비트 암호화폐 자동매매 봇
- **언어**: Python 3.13
- **OS**: Windows 11
- **시작 전략**: 변동성 돌파 전략 (Volatility Breakout)

## 기술 스택
| 역할 | 도구 |
|------|------|
| 거래소 API | pyupbit |
| 데이터베이스 | Supabase (PostgreSQL) |
| 알림 | 텔레그램 봇 |
| 스케줄링 | schedule 라이브러리 |
| 로깅 | loguru |
| 설정 관리 | config/settings.yaml |

## 폴더 구조
```
upbit-quant/
├── src/
│   ├── api/              # 업비트 API 연동 코드
│   ├── strategies/       # 매매 전략 (실거래용)
│   ├── database/         # Supabase DB 연동 코드
│   ├── notifications/    # 기존 텔레그램 알림 코드
│   └── utils/            # 공통 유틸리티 함수
├── notify/               # [추가] 알림 고도화 모듈
│   ├── telegram_bot.py   # 기존 알림 봇 (기능 확장)
│   └── daily_report.py   # 일일 리포트 자동 전송 봇
├── backtest/             # [추가] 전략 백테스팅 엔진
│   ├── engine.py         # 백테스팅 핵심 엔진
│   ├── report.py         # 결과 시각화 및 리포트 생성
│   └── strategies/       # 백테스팅용 전략 구현체
│       ├── volatility_breakout.py
│       ├── dual_momentum.py
│       ├── rsi_bollinger.py
│       └── ma_cross.py
├── config/
│   ├── settings.py       # Python 설정 (기존)
│   └── settings.yaml     # [추가] 전체 설정값 통합 관리 파일
├── logs/                 # 실행 로그 파일 저장
├── tests/                # 테스트 코드
├── main.py               # 프로그램 시작 진입점
├── requirements.txt      # 필요 라이브러리 목록
├── .env                  # 실제 API 키 (절대 공유 금지!)
├── .env.example          # API 키 양식 (공유 가능)
└── CLAUDE.md             # 이 파일
```

## 코딩 규칙
1. 모든 주석 및 docstring은 한국어로 작성
2. API 키, 비밀번호는 반드시 .env 파일에서만 관리
3. 전략 파라미터 등 설정값은 config/settings.yaml에서 관리
4. 실제 매매 전 반드시 LIVE_TRADING=false로 시뮬레이션 테스트
5. 에러 발생 시 텔레그램으로 즉시 알림 전송
6. 모든 매매 내역은 Supabase DB에 기록
7. loguru로 로그 파일 저장 (logs/ 폴더)
8. Windows 환경 기준으로 작성

---

## 기능 1: 변동성 돌파 자동매매 (완료)

### 전략 설명
- **원리**: 당일 시가 + (전일 고가 - 전일 저가) × K 값을 돌파하면 매수
- **매도**: 매일 오전 8시 50분에 전량 매도
- **K값**: 0.5가 기본 (낮을수록 매매 빈도 높음, 위험도 높음)
- **사이클**: 매일 오전 9시 초기화 → 목표가 돌파 시 매수 → 다음날 8:50 매도

### 관련 파일
- `main.py` - 메인 루프 (1분마다 조건 체크)
- `src/api/upbit_client.py` - 매수/매도 API 호출
- `src/strategies/volatility_breakout.py` - 목표가 계산 및 매수 조건

---

## 기능 2: 퀀트 전략 일일 리포트 텔레그램 봇 (개발 예정)

### 기능 설명
매일 정해진 시간에 텔레그램으로 아래 내용을 자동 전송합니다.
- 오늘 적용 중인 퀀트 전략 설명 (쉬운 말로)
- 전략별 성능 지표 요약:
  - 누적 수익률
  - 최대 낙폭 (MDD)
  - 승률
  - 샤프 지수
- 어제 실행된 매매 내역 요약
- 오늘 시장 상황 간단 코멘트

### 관련 파일
- `notify/telegram_bot.py` - 기존 알림 봇 (기능 확장)
- `notify/daily_report.py` - 일일 리포트 전용 봇

### 설정 위치
`config/settings.yaml` → `report:` 섹션

---

## 기능 3: 전략별 백테스팅 엔진 (개발 예정)

### 구현할 전략 순서
1. 변동성 돌파 전략 (k값 조정 가능)
2. 듀얼 모멘텀 전략
3. RSI + 볼린저밴드 전략
4. 이동평균 크로스 전략

### 백테스팅 결과 지표
- 기간별 누적 수익률 그래프
- MDD (최대 낙폭)
- 승률 / 패율
- 샤프 지수
- 총 거래 횟수
- 평균 보유 기간
- 수수료 반영 (업비트 0.05%)

### 데이터 흐름
1. `backtest/engine.py`가 과거 데이터 로드
2. `backtest/strategies/*.py`에서 전략별 매매 신호 생성
3. `backtest/report.py`가 결과 시각화
4. Supabase `backtest_results` 테이블에 결과 저장
5. 텔레그램으로 결과 요약 자동 전송

### 관련 파일
- `backtest/engine.py` - 백테스팅 핵심 엔진
- `backtest/strategies/` - 전략별 구현체
- `backtest/report.py` - 결과 시각화 및 리포트
- `config/settings.yaml` → `backtest:` 섹션

---

## Supabase 테이블 목록
| 테이블 | 용도 |
|--------|------|
| trades | 실거래 매매 내역 |
| backtest_results | 백테스팅 결과 저장 |

### backtest_results 테이블 생성 SQL (미실행)
```sql
CREATE TABLE backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    total_return    NUMERIC,
    mdd             NUMERIC,
    win_rate        NUMERIC,
    sharpe_ratio    NUMERIC,
    total_trades    INTEGER,
    avg_hold_days   NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 개발 진행 현황
- [x] 프로젝트 구조 생성
- [x] requirements.txt 작성
- [x] .env 파일 API 키 입력 (업비트, Supabase, 텔레그램)
- [x] 업비트 API 연결 테스트
- [x] Supabase DB 연결 테스트 (trades 테이블 생성)
- [x] 텔레그램 봇 연결 테스트
- [x] 변동성 돌파 전략 구현
- [x] 시뮬레이션 모드 실행 확인
- [ ] 실거래 전환 테스트
- [ ] 일일 리포트 봇 구현 (notify/daily_report.py)
- [ ] 백테스팅 엔진 구현 (backtest/engine.py)
- [ ] 백테스팅 전략 구현 (4가지)
- [ ] 백테스팅 결과 시각화 (backtest/report.py)
- [ ] Supabase backtest_results 테이블 생성

## 주의사항
- .env 파일은 절대 GitHub에 올리지 말 것
- 처음에는 반드시 LIVE_TRADING=false로 테스트
- 암호화폐 투자는 원금 손실 가능성 있음

# 업비트 자동매매 시스템 - 프로젝트 규칙

## 프로젝트 개요
- **목적**: 업비트 암호화폐 자동매매 봇
- **언어**: Python 3.13
- **OS**: Windows 11 (개발) / Railway.app (배포 및 24/7 운영)
- **현재 전략**: 전략 라우터 v2 (ADX 국면 + 거래량돌파 중심) ← v2 가이드 기반
- **배포 방식**: GitHub push → Railway.app 자동 배포

## 기술 스택
| 역할 | 도구 |
|------|------|
| 거래소 API | pyupbit |
| 데이터베이스 | Supabase (PostgreSQL) |
| 알림 | 텔레그램 봇 |
| 스케줄링 | schedule 라이브러리 |
| 로깅 | loguru |
| 설정 관리 | config/settings.yaml |
| 배포 | Railway.app |

## 폴더 구조
```
upbit-quant/
├── src/
│   ├── api/              # 업비트 API 연동 코드
│   ├── strategies/       # 매매 전략 (실거래용)
│   │   ├── base.py                  # 전략 추상 클래스
│   │   ├── volatility_breakout.py   # 변동성 돌파 전략
│   │   └── ma_cross.py              # ⭐ 이동평균 크로스 5/20 전략 (현재 메인)
│   ├── database/         # Supabase DB 연동 코드
│   ├── notifications/    # 텔레그램 알림 코드
│   └── utils/            # 공통 유틸리티 함수
├── notify/
│   ├── telegram_bot.py   # 실시간 매매 알림
│   └── daily_report.py   # 일일 리포트 자동 전송 봇
├── backtest/
│   ├── engine.py         # 백테스팅 핵심 엔진
│   ├── report.py         # 결과 시각화 및 리포트 생성
│   └── strategies/       # 백테스팅용 전략 구현체
│       ├── ma_cross.py             # ⭐ 이동평균 크로스 (백테스트 1위)
│       ├── volatility_breakout.py
│       ├── dual_momentum.py
│       └── rsi_bollinger.py
├── config/
│   ├── settings.py       # Python 설정
│   └── settings.yaml     # 전체 설정값 통합 관리
├── logs/                 # 실행 로그 파일 저장
├── tests/                # 테스트 코드
├── main.py               # 프로그램 시작 진입점
├── Procfile              # Railway 실행 진입점
├── railway.json          # Railway 배포 설정
├── runtime.txt           # Python 버전 지정
├── requirements.txt      # 필요 라이브러리 목록
├── .env                  # 실제 API 키 (절대 공유 금지!)
├── .env.example          # API 키 양식 (공유 가능)
└── CLAUDE.md             # 이 파일
```

## 코딩 규칙
1. 모든 주석 및 docstring은 한국어로 작성
2. API 키, 비밀번호는 반드시 .env 파일에서만 관리
3. 전략 파라미터 등 설정값은 config/settings.yaml에서 관리
4. 실제 매매 전 반드시 LIVE_TRADING=false로 시뮬레이션 테스트
5. 에러 발생 시 텔레그램으로 즉시 알림 전송
6. 모든 매매 내역은 Supabase DB에 기록
7. loguru로 로그 파일 저장 (logs/ 폴더)
8. Windows 환경 기준으로 작성, Railway.app 배포 고려

---

## ⭐ 기능 1: 이동평균 크로스 5/20 전략 (최우선 구현)

### 전략 설명
- **원리**: 단기 이동평균(5일)이 장기 이동평균(20일)을 위로 돌파하면 매수 (골든크로스)
- **매도**: 단기 이동평균(5일)이 장기 이동평균(20일)을 아래로 돌파하면 매도 (데드크로스)
- **백테스트 결과**: 4가지 전략 중 가장 우수한 성과

### 핵심 로직
```python
# 골든크로스: MA5가 MA20을 위로 돌파 → 매수
if ma5_prev <= ma20_prev and ma5_current > ma20_current:
    buy()

# 데드크로스: MA5가 MA20을 아래로 돌파 → 매도
if ma5_prev >= ma20_prev and ma5_current < ma20_current:
    sell()
```

### 설정값 (config/settings.yaml)
```yaml
strategy:
  name: "ma_cross"
  short_window: 5      # 단기 이동평균 기간
  long_window: 20      # 장기 이동평균 기간
  ticker: "KRW-BTC"   # 거래 코인
  invest_ratio: 0.95   # 보유 현금의 95% 투자
```

### 구현 순서
1. `src/strategies/ma_cross.py` 전략 클래스 구현
2. `backtest/strategies/ma_cross.py` 백테스팅용 구현
3. `main.py` 에 MA 크로스 전략 연결
4. 시뮬레이션 모드로 테스트
5. 텔레그램 알림 연동
6. Railway.app 배포

### 관련 파일
- `src/strategies/ma_cross.py` - 실거래용 전략
- `backtest/strategies/ma_cross.py` - 백테스팅용 전략
- `config/settings.yaml` → `strategy:` 섹션

---

## 기능 2: 변동성 돌파 전략 (보조 전략)

### 전략 설명
- **원리**: 당일 시가 + (전일 고가 - 전일 저가) × K 값을 돌파하면 매수
- **매도**: 매일 오전 8시 50분에 전량 매도
- **K값**: 0.5가 기본값

### 관련 파일
- `src/strategies/volatility_breakout.py`

---

## 기능 2.5: 국면별 전략 라우터 v2 (ADX + 거래량돌파) - 구현 완료

### 개요
v2 가이드(crypto_strategy_guide_v2.md) 기반으로 전면 개편:
- 국면 판단: SMA50+모멘텀 → **ADX 기반** (횡보 72%→44%, 전환비용 1%p 절감)
- 전략: BB+RSI 제거, **거래량돌파를 전 국면에서 유지** (횡보장에서도 +25.72%)
- 하락장에서만 현금 전환 (하락장 거래량돌파 -22.76% 방지)

### 국면 판단 기준 (BTC 기준, ADX)
- **상승장(Bull)**: ADX > 25 AND +DI > -DI (강한 상승 추세)
- **하락장(Bear)**: ADX > 25 AND -DI > +DI (강한 하락 추세)
- **횡보장(Sideways)**: ADX <= 25 (추세 약함)

### 전략 매핑
| 국면 | 전략 | 근거 |
|------|------|------|
| 상승장 | 적응형 거래량돌파 | 실측 +179.48% |
| 횡보장 | 적응형 거래량돌파 | 실측 +25.72% (BB+RSI는 -119%) |
| 하락장 | 현금 보유 | 거래량돌파 하락장 -22.76% 방지 |

### 국면 전환 안정성
- 전환 감지 후 2일(confirmation_days) 동일 국면 유지 시에만 실제 전환
- ADX 기반: 연 28.3회 전환 (기존 SMA 39.2회 대비 안정적)

### 관련 파일
- `src/strategies/strategy_router.py` — 전략 라우터 v2 (ADX + calc_adx 함수)
- `src/strategies/adaptive_volume_strategy.py` — 거래량돌파 전략
- `src/strategies/cash_hold.py` — 하락장 방어
- `config/settings.yaml` → `regime_detection:`, `strategies:` 섹션
- `docs/crypto_strategy_guide_v2.md` — 전략 가이드 v2 (근거 문서)

### Supabase 테이블
| 테이블 | 용도 |
|--------|------|
| strategy_switches | 국면 전환 이력 (ADX/+DI/-DI 추가) |

### 설정값 (config/settings.yaml)
```yaml
strategy:
  name: "strategy_router"    # 국면별 자동 스위칭 활성화

regime_detection:
  adx_period: 14              # ADX 계산 기간
  adx_trend_threshold: 25     # 추세 판단 임계값
  confirmation_days: 2        # 전환 확인 대기일

strategies:
  volume_breakout:            # 상승+횡보 공통
    price_lookback: 4
    vol_ratio: 1.26
    top_k: 5
    rebalance_days: 3
  cash_hold:                  # 하락장
    enabled: true
```

---

## 기능 3: 퀀트 전략 일일 리포트 텔레그램 봇 (개발 예정)

### 기능 설명
매일 오전 9시에 텔레그램으로 자동 전송:
- 현재 적용 중인 전략 (MA 크로스 5/20) 설명
- 전략 성능 지표: 누적 수익률 / MDD / 승률 / 샤프 지수
- 전일 매매 내역 요약 (골든크로스/데드크로스 발생 여부)
- 현재 MA5, MA20 값 및 크로스 임박 여부

### 텔레그램 메시지 예시
```
[업비트 퀀트봇 - 일일 리포트]
📅 2026-02-24

📊 현재 전략: 이동평균 크로스 (5/20)
→ MA5가 MA20 위에 있으면 매수 유지
→ MA5가 MA20 아래로 내려가면 매도

📈 현재 지표
- MA5:  98,500,000원
- MA20: 96,200,000원
- 상태: 매수 포지션 유지 중 ✅

💰 전략 성과
- 누적 수익률: +31.2%
- 최대 낙폭(MDD): -9.4%
- 승률: 62%
- 샤프지수: 1.67

🔄 최근 매매
- 02/20 골든크로스 → BTC 매수 @ 96,000,000원
- 현재 수익: +2.6%
```

### 관련 파일
- `notify/daily_report.py`

---

## 기능 4: 전략별 백테스팅 엔진 (개발 예정)

### 백테스팅 결과 순위 (완료)
| 순위 | 전략 | 수익률 | MDD | 승률 |
|------|------|--------|-----|------|
| 1위 ⭐ | 이동평균 크로스 5/20 | 가장 우수 | - | - |
| 2위 | 변동성 돌파 | - | - | - |
| 3위 | RSI + 볼린저밴드 | - | - | - |
| 4위 | 듀얼 모멘텀 | - | - | - |

### 백테스팅 결과 지표
- 기간별 누적 수익률 그래프
- MDD (최대 낙폭)
- 승률 / 패율
- 샤프 지수
- 총 거래 횟수
- 평균 보유 기간
- 수수료 반영 (업비트 0.05%)

### 관련 파일
- `backtest/engine.py`
- `backtest/strategies/`
- `backtest/report.py`

---

## Railway.app 배포 설정

### 필요 파일
```
Procfile:     worker: python main.py
runtime.txt:  python-3.11.9
railway.json: 배포 및 재시작 정책 설정
```

### 환경변수 (Railway 대시보드 Variables 탭에 입력)
```
UPBIT_ACCESS_KEY=업비트_액세스_키
UPBIT_SECRET_KEY=업비트_시크릿_키
SUPABASE_URL=Supabase_URL
SUPABASE_KEY=Supabase_KEY
TELEGRAM_BOT_TOKEN=텔레그램_봇_토큰
TELEGRAM_CHAT_ID=텔레그램_채팅_ID
LIVE_TRADING=false
```

### 배포 순서
```
1. 코드 수정
2. git add . → git commit → git push
3. Railway 자동 감지 및 배포
4. Railway 대시보드 Deployments 탭에서 로그 확인
```

---

## Supabase 테이블 목록
| 테이블 | 용도 |
|--------|------|
| trades | 실거래 매매 내역 |
| backtest_results | 백테스팅 결과 저장 |

### trades 테이블
```sql
CREATE TABLE trades (
    id              BIGSERIAL PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL,  -- 'buy' or 'sell'
    price           NUMERIC NOT NULL,
    amount          NUMERIC NOT NULL,
    signal          TEXT,           -- 'golden_cross' or 'dead_cross'
    ma5             NUMERIC,
    ma20            NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### backtest_results 테이블
```sql
CREATE TABLE backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    total_return    NUMERIC,
    mdd             NUMERIC,
    win_rate        NUMERIC,
    sharpe_ratio    NUMERIC,
    total_trades    INTEGER,
    avg_hold_days   NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 기능 5: 코인 선별 전략 백테스팅 (구현 완료)

### 전략 4종
| 전략 | 클래스 | 핵심 지표 |
|------|--------|-----------|
| 모멘텀 스크리닝 | MomentumScreener | N일 수익률 상위 |
| 거래량 급증 | VolumeScreener | 20일 평균 대비 거래량 비율 |
| 평균회귀 | MeanReversionScreener | RSI(14) 과매도 |
| 복합 스코어링 | CompositeScreener | 모멘텀50%+거래량30%+저변동성20% |

### 실행 방법
```bash
python -m backtest.coin_screener.run_backtest
python -m backtest.coin_screener.run_backtest --days 90 --top-n 3 --rebalance 7
python -m backtest.coin_screener.run_backtest --strategies momentum,composite --save-csv
```

### 관련 파일
```
backtest/coin_screener/
├── data_collector.py       # Upbit 전체 코인 일봉 데이터 수집 + 캐싱
├── strategies/
│   ├── base_screener.py    # 스크리너 추상 클래스
│   ├── momentum_screener.py
│   ├── volume_screener.py
│   ├── mean_reversion_screener.py
│   └── composite_screener.py
├── backtest_engine.py      # 리밸런싱 방식 백테스팅 엔진
├── report_generator.py     # 비교 리포트 (콘솔+차트+CSV+DB+텔레그램)
└── run_backtest.py         # CLI 실행 진입점
```

---

## 개발 진행 현황
- [x] 프로젝트 구조 생성
- [x] requirements.txt 작성
- [x] .env 파일 API 키 입력 (업비트, Supabase, 텔레그램)
- [x] 업비트 API 연결 테스트
- [x] Supabase DB 연결 테스트
- [x] 텔레그램 봇 연결 테스트
- [x] 변동성 돌파 전략 구현
- [x] 4가지 전략 백테스팅 완료 → MA 크로스 5/20 최우수
- [x] Railway.app 배포 설정 파일 추가
- [x] 코인 선별 전략 4종 구현 (모멘텀/거래량/평균회귀/복합)
- [x] 코인 선별 전용 백테스팅 엔진 구현
- [x] 비교 리포트 생성기 구현
- [x] BB+RSI 평균회귀 전략 구현 (횡보장 대응) → v2에서 제거 (실측 -119%)
- [x] 하락장 방어 전략 (CashHold) 구현
- [x] 전략 라우터 (StrategyRouter) 구현 — 국면별 자동 스위칭
- [x] main.py에 전략 라우터 연결
- [x] BB+RSI 매매 텔레그램 알림 구현 → v2에서 제거
- [x] 국면 전환 텔레그램 알림 구현
- [x] strategy_switches DB 스키마 작성
- [x] **전략 라우터 v2 구현 — ADX 국면 판단 + 거래량돌파 중심 (2026-03-30)**
- [x] **BB+RSI 제거, main.py 단순화 (2026-03-30)**
- [ ] Supabase strategy_switches 테이블에 ADX 컬럼 추가
- [ ] LIVE_TRADING=false에서 전략 라우터 v2 시뮬레이션 테스트
- [ ] Railway.app 배포 및 24/7 운영
- [ ] 일일 국면 리포트 봇 구현
- [ ] 백테스팅 결과 시각화

## 주의사항
- .env 파일은 절대 GitHub에 올리지 말 것 (.gitignore 확인)
- 처음에는 반드시 LIVE_TRADING=false로 테스트
- 암호화폐 투자는 원금 손실 가능성 있음
- Railway 배포 후 반드시 로그 확인하여 정상 작동 검증