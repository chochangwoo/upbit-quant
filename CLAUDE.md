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
