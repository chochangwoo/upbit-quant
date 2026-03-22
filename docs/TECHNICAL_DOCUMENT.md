# Upbit-Quant 기술문서

> 암호화폐 자동매매 시스템 (Automated Cryptocurrency Trading System)
>
> 버전: 1.0.0 | 작성일: 2026-03-06

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [기술 스택](#3-기술-스택)
4. [모듈별 상세 명세](#4-모듈별-상세-명세)
5. [매매 전략 상세](#5-매매-전략-상세)
6. [데이터 흐름](#6-데이터-흐름)
7. [데이터베이스 스키마](#7-데이터베이스-스키마)
8. [외부 API 연동 명세](#8-외부-api-연동-명세)
9. [설정 체계](#9-설정-체계)
10. [보안 설계](#10-보안-설계)
11. [로깅 및 모니터링](#11-로깅-및-모니터링)
12. [배포 및 실행 환경](#12-배포-및-실행-환경)
13. [확장 로드맵](#13-확장-로드맵)

---

## 1. 시스템 개요

### 1.1 제품 정의

Upbit-Quant는 업비트 거래소에서 암호화폐를 자동으로 매매하는 퀀트 트레이딩 시스템입니다. 사전에 설정된 수학적 전략에 따라 매수/매도를 자동 실행하며, 텔레그램을 통해 실시간 알림을 제공합니다.

### 1.2 핵심 가치

| 항목 | 설명 |
|------|------|
| **자동화** | 24시간 무인 매매, 사람의 감정 개입 배제 |
| **안전성** | 시뮬레이션 모드로 실제 자산 투입 없이 전략 검증 |
| **투명성** | 모든 매매 내역 DB 기록, 텔레그램 실시간 알림 |
| **확장성** | 전략 플러그인 구조로 다양한 전략 추가 가능 |

### 1.3 주요 기능

- 변동성 돌파 전략 기반 자동매매 (구현 완료)
- 시뮬레이션/실거래 모드 전환
- 텔레그램 실시간 매매 알림
- Supabase 클라우드 DB에 매매 이력 자동 저장
- 일별 자동 로그 파일 관리 (30일 보관)
- 다중 코인 동시 모니터링 지원

---

## 2. 시스템 아키텍처

### 2.1 전체 구조도

```
+----------------------------------------------------------+
|                      main.py (스케줄러)                    |
|  schedule 라이브러리로 1분 주기 메인루프 실행                 |
+----+------------------+------------------+---------------+
     |                  |                  |
     v                  v                  v
+-----------+   +---------------+   +-------------+
| strategies|   | api           |   | notifications|
| 매매 전략  |   | 업비트 API    |   | 텔레그램 알림 |
+-----------+   +---------------+   +-------------+
                       |
                       v
              +---------------+
              | database      |
              | Supabase DB   |
              +---------------+
```

### 2.2 디렉터리 구조

```
upbit-quant/
├── main.py                          # 프로그램 진입점 및 스케줄러
├── config/
│   ├── settings.py                  # 환경변수 기반 전역 설정
│   └── settings.yaml                # YAML 기반 전략 파라미터 설정
├── src/
│   ├── api/
│   │   └── upbit_client.py          # 업비트 거래소 API 래퍼
│   ├── strategies/
│   │   └── volatility_breakout.py   # 변동성 돌파 전략
│   ├── database/
│   │   └── supabase_client.py       # Supabase DB 연동
│   ├── notifications/
│   │   └── telegram_bot.py          # 텔레그램 알림 전송
│   └── utils/                       # 공통 유틸리티 (예약)
├── backtest/                        # 백테스팅 엔진 (개발 예정)
├── notify/                          # 일일 리포트 봇 (개발 예정)
├── logs/                            # 자동 생성 로그 파일
├── tests/                           # 테스트 코드
├── requirements.txt                 # 의존성 목록
├── .env                             # API 키 (비공개)
└── .env.example                     # API 키 양식 (공개)
```

---

## 3. 기술 스택

| 분류 | 기술 | 버전 | 용도 |
|------|------|------|------|
| 언어 | Python | 3.13 | 메인 런타임 |
| 거래소 API | pyupbit | 0.2.33 | 업비트 REST/WebSocket 통신 |
| 데이터베이스 | Supabase (PostgreSQL) | 2.3.5 (SDK) | 매매 내역 영구 저장 |
| 알림 | Telegram Bot API | - | 실시간 매매 알림 |
| HTTP 클라이언트 | requests | 2.31.0 | 텔레그램 API 호출 |
| 스케줄링 | schedule | 1.2.1 | 주기적 작업 실행 |
| 로깅 | loguru | 0.7.2 | 구조화된 로그 관리 |
| 데이터 처리 | pandas / numpy | 2.2.3 / 2.2.3 | OHLCV 데이터 분석 |
| 시각화 | matplotlib | 3.9.4 | 백테스팅 결과 차트 |
| 설정 관리 | python-dotenv / PyYAML | 1.0.0 / 6.0.2 | 환경변수 및 설정 파일 |
| OS | Windows 11 | - | 실행 환경 |

---

## 4. 모듈별 상세 명세

### 4.1 `main.py` - 메인 스케줄러

**역할**: 프로그램 진입점. 1분 주기로 매매 조건을 체크하고, 시간대에 따라 매수/매도를 결정합니다.

**핵심 함수**

| 함수명 | 설명 |
|--------|------|
| `main()` | 스케줄러를 초기화하고 무한루프로 실행 |
| `trading_job()` | 1분마다 호출. 현재 시각 기반으로 매수/매도 분기 |
| `do_buy_check()` | 대상 코인별 매수 조건 확인 및 매수 실행 |
| `do_sell_all()` | 보유 코인 전량 시장가 매도 |
| `print_status()` | 1시간마다 현재 상태 (잔고, 모드) 출력 |

**매매 사이클 타임라인**

```
08:50~08:59  → do_sell_all()     보유 코인 전량 매도
09:00        → bought_today 초기화  새 거래일 시작
09:01~08:49  → do_buy_check()    1분마다 매수 조건 체크
```

**중복 매수 방지**: `bought_today: set`에 당일 매수한 코인을 기록하여 같은 코인을 하루에 두 번 매수하지 않습니다.

---

### 4.2 `src/api/upbit_client.py` - 업비트 API 래퍼

**역할**: pyupbit 라이브러리를 감싸서 업비트 거래소와의 모든 통신을 담당합니다.

**함수 명세**

| 함수명 | 매개변수 | 반환값 | 설명 |
|--------|----------|--------|------|
| `get_upbit_client()` | 없음 | `pyupbit.Upbit` or `None` | API 키로 인증된 클라이언트 생성 |
| `get_current_price(ticker)` | `str` (예: "KRW-BTC") | `float` or `None` | 코인 현재가 조회 |
| `get_ohlcv(ticker, interval, count)` | `str`, `str`, `int` | `DataFrame` or `None` | 캔들차트 데이터 (시가/고가/저가/종가/거래량) |
| `get_balance_krw()` | 없음 | `float` | 보유 원화 잔고 조회 |
| `get_balance_coin(ticker)` | `str` | `float` | 특정 코인 보유 수량 조회 |
| `buy_market_order(ticker, amount_krw)` | `str`, `float` | `dict` or `None` | 시장가 매수 주문 |
| `sell_market_order(ticker, volume)` | `str`, `float` | `dict` or `None` | 시장가 매도 주문 |

**에러 처리 전략**: 모든 함수는 try-except로 예외를 포착하고, loguru로 에러를 기록한 뒤 `None` 또는 `0`을 반환합니다. 호출자는 반환값의 null 체크로 실패를 감지합니다.

---

### 4.3 `src/strategies/volatility_breakout.py` - 변동성 돌파 전략

**역할**: 래리 윌리엄스(Larry Williams)의 변동성 돌파 전략을 구현합니다.

**함수 명세**

| 함수명 | 매개변수 | 반환값 | 설명 |
|--------|----------|--------|------|
| `calculate_target_price(ticker)` | `str` | `float` or `None` | 매수 목표가 계산 |
| `should_buy(ticker)` | `str` | `bool` | 현재가가 목표가 이상인지 판단 |

**목표가 산출 공식**

```
목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
```

- `K`: 변동성 비율 (기본값 0.5, 환경변수 `VOLATILITY_K`로 조정)
- 전일 변동폭 `(고가 - 저가)`가 크면 목표가가 높아져 신중한 매수
- K값이 낮을수록 목표가가 낮아져 매매 빈도 증가, 위험도 상승

**데이터 의존성**: `pyupbit.get_ohlcv()`로 최근 2일치 일봉 데이터를 사용합니다.

---

### 4.4 `src/database/supabase_client.py` - 데이터베이스 연동

**역할**: Supabase (클라우드 PostgreSQL)에 매매 내역을 저장합니다.

**함수 명세**

| 함수명 | 매개변수 | 반환값 | 설명 |
|--------|----------|--------|------|
| `get_supabase_client()` | 없음 | `supabase.Client` or `None` | DB 클라이언트 생성 |
| `save_trade(ticker, trade_type, price, amount, quantity)` | `str`, `str`, `float`, `float`, `float` | `bool` | 매매 내역 INSERT |

**저장 데이터 구조**

```json
{
  "ticker": "KRW-BTC",
  "trade_type": "buy",
  "price": 85000000,
  "amount": 10000,
  "quantity": 0.000118,
  "created_at": "2026-03-06T14:30:00"
}
```

---

### 4.5 `src/notifications/telegram_bot.py` - 텔레그램 알림

**역할**: 매매 이벤트 발생 시 사용자에게 텔레그램 메시지를 전송합니다.

**함수 명세**

| 함수명 | 매개변수 | 설명 |
|--------|----------|------|
| `send_message(message)` | `str` | 범용 메시지 전송 (HTML 파싱 지원) |
| `send_buy_alert(ticker, price, amount)` | `str`, `float`, `float` | 매수 완료 알림 |
| `send_sell_alert(ticker, price, profit_rate)` | `str`, `float`, `float` | 매도 완료 알림 (수익률 포함) |
| `send_error_alert(error_msg)` | `str` | 시스템 오류 알림 |

**통신 방식**: Telegram Bot API의 `sendMessage` 엔드포인트를 `requests.post()`로 호출합니다. HTML 파싱 모드를 사용하여 굵은 글씨(`<b>`) 등 서식을 지원합니다.

---

### 4.6 `config/settings.py` - 전역 설정

**역할**: `.env` 파일의 환경변수를 Python 상수로 변환하여 전체 시스템에서 사용합니다.

**설정 항목**

| 상수명 | 타입 | 기본값 | 설명 |
|--------|------|--------|------|
| `TARGET_COINS` | `list[str]` | `["KRW-BTC"]` | 매매 대상 코인 목록 |
| `ORDER_AMOUNT` | `int` | `10000` | 1회 매수 금액 (원) |
| `VOLATILITY_K` | `float` | `0.5` | 변동성 돌파 K값 |
| `LIVE_TRADING` | `bool` | `False` | 실거래/시뮬레이션 모드 |
| `SELL_HOUR` / `SELL_MINUTE` | `int` | `8` / `50` | 일일 매도 시각 |

---

### 4.7 `config/settings.yaml` - 전략 파라미터 설정

**역할**: 전략별 세부 파라미터, 백테스팅 옵션, 리포트 설정을 YAML 형식으로 관리합니다.

**설정 섹션**

| 섹션 | 용도 |
|------|------|
| `trading` | 매매 대상 코인, 주문 금액, 실거래 여부 |
| `strategy.volatility_breakout` | K값, 매도/초기화 시간 |
| `strategy.dual_momentum` | 모멘텀 계산 기간, 무위험 수익률 |
| `strategy.rsi_bollinger` | RSI 기간/과매수/과매도, 볼린저밴드 기간/표준편차 |
| `strategy.ma_cross` | 단기/장기 이동평균선 기간 |
| `report` | 리포트 전송 시간, 포함 지표, 매매 내역 포함 여부 |
| `backtest` | 테스트 기간, 초기 자본, 수수료율, DB 저장 여부 |

---

## 5. 매매 전략 상세

### 5.1 변동성 돌파 전략 (Volatility Breakout) - 구현 완료

| 항목 | 내용 |
|------|------|
| **원리** | 전일 변동폭을 기준으로 당일 상승 돌파 시 매수 |
| **고안자** | 래리 윌리엄스 (Larry Williams) |
| **매수 조건** | 현재가 >= 당일시가 + (전일고가 - 전일저가) × K |
| **매도 조건** | 매일 08:50 전량 시장가 매도 |
| **거래 주기** | 1일 (오전 9시 리셋) |
| **K값 범위** | 0.3 ~ 0.7 (기본 0.5) |

**전략 수익 구조**

```
매수 시점: 당일 변동성 상향 돌파 → 추세 추종 진입
매도 시점: 익일 08:50 전량 청산 → 오버나이트 리스크 차단
수익 원천: 변동성 돌파 후 추가 상승분
```

### 5.2 확장 예정 전략

| 전략 | 핵심 원리 | 파라미터 |
|------|-----------|----------|
| **듀얼 모멘텀** | 절대/상대 모멘텀 동시 충족 시 매수 | lookback 12일, 무위험수익률 0% |
| **RSI + 볼린저밴드** | RSI 과매도 + 볼린저 하단 터치 시 매수 | RSI 14일, BB 20일/2σ |
| **이동평균 크로스** | 단기MA가 장기MA 상향돌파 시 매수 | 단기 5일, 장기 20일 |

---

## 6. 데이터 흐름

### 6.1 매수 프로세스

```
[1분 스케줄러]
    │
    ├─ for ticker in TARGET_COINS:
    │       │
    │       ├─ 중복 매수 체크 (bought_today set)
    │       │
    │       ├─ should_buy(ticker)
    │       │       │
    │       │       ├─ get_ohlcv() ───→ [업비트 API] 2일치 일봉 조회
    │       │       │
    │       │       ├─ calculate_target_price() ───→ 목표가 산출
    │       │       │
    │       │       ├─ get_current_price() ───→ [업비트 API] 현재가 조회
    │       │       │
    │       │       └─ 현재가 >= 목표가 ? ──→ True / False
    │       │
    │       ├─ (True) get_balance_krw() ───→ 잔고 확인
    │       │
    │       ├─ buy_market_order() ───→ [업비트 API] 시장가 매수
    │       │
    │       ├─ save_trade() ───→ [Supabase] 매매 내역 저장
    │       │
    │       └─ send_buy_alert() ───→ [텔레그램] 매수 알림
```

### 6.2 매도 프로세스

```
[08:50 트리거]
    │
    ├─ for ticker in TARGET_COINS:
    │       │
    │       ├─ get_balance_coin() ───→ 보유 수량 확인
    │       │
    │       ├─ sell_market_order() ───→ [업비트 API] 시장가 매도
    │       │
    │       ├─ save_trade() ───→ [Supabase] 매도 내역 저장
    │       │
    │       └─ send_sell_alert() ───→ [텔레그램] 매도 알림
```

---

## 7. 데이터베이스 스키마

### 7.1 `trades` 테이블 (운영 중)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGSERIAL (PK) | 자동증가 ID |
| `ticker` | TEXT | 코인 식별자 (예: KRW-BTC) |
| `trade_type` | TEXT | "buy" 또는 "sell" |
| `price` | NUMERIC | 체결 가격 (원) |
| `amount` | NUMERIC | 거래 금액 (원) |
| `quantity` | NUMERIC | 거래 수량 (코인) |
| `created_at` | TIMESTAMPTZ | 거래 시각 |

### 7.2 `backtest_results` 테이블 (예정)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGSERIAL (PK) | 자동증가 ID |
| `strategy_name` | TEXT | 전략명 |
| `ticker` | TEXT | 대상 코인 |
| `start_date` / `end_date` | DATE | 테스트 기간 |
| `total_return` | NUMERIC | 누적 수익률 |
| `mdd` | NUMERIC | 최대 낙폭 |
| `win_rate` | NUMERIC | 승률 |
| `sharpe_ratio` | NUMERIC | 샤프 지수 |
| `total_trades` | INTEGER | 총 거래 횟수 |
| `avg_hold_days` | NUMERIC | 평균 보유일수 |
| `created_at` | TIMESTAMPTZ | 결과 생성 시각 |

---

## 8. 외부 API 연동 명세

### 8.1 업비트 (Upbit)

| 항목 | 내용 |
|------|------|
| **프로토콜** | REST API (HTTPS) |
| **인증** | JWT 토큰 (Access Key + Secret Key) |
| **라이브러리** | pyupbit 0.2.33 (공식 래퍼) |
| **호출 빈도** | 1분 주기 (코인 수 × 2~3회/분) |
| **사용 엔드포인트** | 현재가 조회, OHLCV 조회, 잔고 조회, 시장가 주문 |

### 8.2 Supabase

| 항목 | 내용 |
|------|------|
| **프로토콜** | REST API (HTTPS, PostgREST) |
| **인증** | anon public key (Row Level Security) |
| **라이브러리** | supabase-py 2.3.5 |
| **사용 연산** | INSERT (매매 내역 저장) |

### 8.3 Telegram Bot API

| 항목 | 내용 |
|------|------|
| **프로토콜** | HTTPS POST |
| **인증** | Bot Token |
| **메서드** | `sendMessage` |
| **파싱 모드** | HTML |
| **타임아웃** | 10초 |

---

## 9. 설정 체계

시스템은 2계층 설정 구조를 사용합니다.

### 9.1 계층 구조

```
[1계층] .env 파일 (비밀 정보)
    │   API 키, 토큰, DB 접속정보
    │   → python-dotenv로 환경변수로 로드
    │   → config/settings.py에서 Python 상수로 변환
    │
[2계층] config/settings.yaml (전략 파라미터)
        K값, RSI 기간, 백테스팅 설정 등
        → 코드 변경 없이 전략 튜닝 가능
```

### 9.2 환경변수 목록 (.env)

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `UPBIT_ACCESS_KEY` | O | 업비트 API Access Key |
| `UPBIT_SECRET_KEY` | O | 업비트 API Secret Key |
| `SUPABASE_URL` | O | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | O | Supabase anon public Key |
| `TELEGRAM_BOT_TOKEN` | O | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | O | 텔레그램 수신 채팅 ID |
| `TARGET_COINS` | X | 매매 대상 코인 (기본: KRW-BTC) |
| `ORDER_AMOUNT` | X | 1회 매수 금액 (기본: 10000) |
| `VOLATILITY_K` | X | 변동성 K값 (기본: 0.5) |
| `LIVE_TRADING` | X | 실거래 모드 (기본: false) |

---

## 10. 보안 설계

### 10.1 API 키 보호

- 모든 API 키는 `.env` 파일에서만 관리
- `.gitignore`에 `.env` 등록하여 Git 추적 방지
- `.env.example` 파일로 필요한 키 양식만 공유
- 코드 내에 하드코딩된 비밀 정보 없음

### 10.2 실행 안전장치

- 기본 실행 모드가 **시뮬레이션** (`LIVE_TRADING=false`)
- 시뮬레이션 모드에서는 실제 주문 API를 호출하지 않음
- 1회 매수 금액 제한으로 과도한 주문 방지
- 중복 매수 방지 로직 (`bought_today` set)

### 10.3 에러 복원력

- 모든 외부 API 호출에 try-except 예외 처리
- API 실패 시 `None` 반환 → 호출자에서 null 체크로 안전 중단
- 에러 발생 시 텔레그램으로 즉시 알림 전송
- 주문 실패해도 메인 루프는 계속 실행 (단일 코인 실패가 전체에 영향 없음)

---

## 11. 로깅 및 모니터링

### 11.1 로그 설정

| 출력 대상 | 레벨 | 포맷 |
|-----------|------|------|
| 콘솔 (stdout) | INFO | `HH:mm:ss \| LEVEL \| message` (컬러) |
| 파일 (logs/) | DEBUG | `YYYY-MM-DD HH:mm:ss \| LEVEL \| message` |

### 11.2 로그 파일 관리

- **파일명 패턴**: `logs/trading_YYYY-MM-DD.log`
- **로테이션**: 매일 자정 새 파일 생성
- **보관 기간**: 30일 (초과분 자동 삭제)
- **인코딩**: UTF-8

### 11.3 모니터링 포인트

| 이벤트 | 로그 레벨 | 텔레그램 알림 |
|--------|-----------|--------------|
| 매수 신호 감지 | INFO | X |
| 매수 주문 성공 | INFO | O (매수 알림) |
| 매도 주문 성공 | INFO | O (매도 알림) |
| 잔고 부족 | WARNING | X |
| API 호출 실패 | ERROR | O (에러 알림) |
| 주문 실패 | ERROR | O (에러 알림) |
| 시스템 시작/종료 | INFO | O (상태 알림) |

---

## 12. 배포 및 실행 환경

### 12.1 시스템 요구사항

| 항목 | 최소 요구 |
|------|-----------|
| OS | Windows 10 이상 |
| Python | 3.11 이상 |
| 메모리 | 512MB 이상 |
| 네트워크 | 상시 인터넷 연결 필수 |
| 디스크 | 100MB 이상 여유 공간 |

### 12.2 설치 및 실행 절차

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
copy .env.example .env
# .env 파일에 실제 API 키 입력

# 4. 시뮬레이션 모드로 실행
python main.py

# 5. 실거래 전환 (.env 파일에서 변경)
# LIVE_TRADING=true
```

### 12.3 의존성 패키지 (13개)

```
pyupbit==0.2.33          # 업비트 API
python-dotenv==1.0.0     # 환경변수
supabase==2.3.5          # 클라우드 DB
python-telegram-bot==20.7 # 텔레그램
pandas==2.2.3            # 데이터 처리
numpy==2.2.3             # 수치 연산
schedule==1.2.1          # 작업 스케줄링
loguru==0.7.2            # 로깅
requests==2.31.0         # HTTP 클라이언트
matplotlib==3.9.4        # 차트 시각화
pyyaml==6.0.2            # YAML 파싱
```

---

## 13. 확장 로드맵

### Phase 2 - 알림 고도화

| 기능 | 설명 | 관련 파일 |
|------|------|-----------|
| 일일 리포트 봇 | 매일 정해진 시간에 전략 성능, 매매 요약, 시장 코멘트를 텔레그램으로 전송 | `notify/daily_report.py` |
| 성능 지표 포함 | 누적 수익률, MDD, 승률, 샤프 지수 | - |

### Phase 3 - 백테스팅 엔진

| 기능 | 설명 | 관련 파일 |
|------|------|-----------|
| 백테스팅 코어 | 과거 데이터 기반 전략 시뮬레이션 | `backtest/engine.py` |
| 4가지 전략 | 변동성 돌파, 듀얼 모멘텀, RSI+볼린저, 이동평균 크로스 | `backtest/strategies/` |
| 결과 시각화 | 수익률 그래프, MDD, 승률 등 차트 리포트 | `backtest/report.py` |
| DB 저장 | 백테스팅 결과를 Supabase에 영구 보관 | `backtest_results` 테이블 |

### Phase 4 - 상용화 확장 (제안)

| 기능 | 설명 |
|------|------|
| 웹 대시보드 | 실시간 매매 현황, 수익률 차트를 웹으로 제공 |
| 멀티 유저 | 사용자별 독립 설정 및 전략 운용 |
| 전략 마켓플레이스 | 사용자가 전략을 공유/구독하는 플랫폼 |
| 리스크 매니저 | 일일 손실 한도, 포트폴리오 비중 제한 등 위험 관리 |
| SaaS 과금 | 구독 모델 기반 수익화 (무료/프리미엄 티어) |

---

## 부록: 코드 품질 기준

| 항목 | 적용 사항 |
|------|-----------|
| 언어 | 모든 주석 및 docstring 한국어 작성 |
| 에러 처리 | 모든 외부 호출에 try-except 적용 |
| 로깅 | loguru로 통일, DEBUG/INFO/WARNING/ERROR 레벨 구분 |
| 설정 분리 | 비밀 정보(.env)와 전략 파라미터(YAML) 분리 관리 |
| 모듈화 | 기능별 디렉터리 분리 (api, strategies, database, notifications) |
