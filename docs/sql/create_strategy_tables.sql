-- 전략 전환 이력 테이블 (v2: ADX 기반)
-- StrategyRouter 국면 전환 시 기록
CREATE TABLE strategy_switches (
    id              BIGSERIAL PRIMARY KEY,
    prev_regime     TEXT NOT NULL,       -- 'bull', 'bear', 'sideways'
    new_regime      TEXT NOT NULL,
    prev_strategy   TEXT NOT NULL,
    new_strategy    TEXT NOT NULL,
    btc_price       NUMERIC,
    sma50           NUMERIC,             -- v1 호환 (nullable)
    momentum_20d    NUMERIC,             -- v1 호환 (nullable)
    adx             NUMERIC,             -- v2: ADX 값
    plus_di         NUMERIC,             -- v2: +DI 값
    minus_di        NUMERIC,             -- v2: -DI 값
    positions_closed JSONB,              -- 청산된 포지션 정보
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스 생성
CREATE INDEX idx_strategy_switches_created_at ON strategy_switches (created_at DESC);

-- v1 → v2 마이그레이션 (기존 테이블이 있는 경우)
-- ALTER TABLE strategy_switches ADD COLUMN IF NOT EXISTS adx NUMERIC;
-- ALTER TABLE strategy_switches ADD COLUMN IF NOT EXISTS plus_di NUMERIC;
-- ALTER TABLE strategy_switches ADD COLUMN IF NOT EXISTS minus_di NUMERIC;
