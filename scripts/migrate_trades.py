"""
Supabase trades 테이블 마이그레이션 스크립트
MA 크로스 전략에 맞게 스키마를 재생성합니다.

실행 방법:
  python scripts/migrate_trades.py
"""
import os
import sys
import requests
from dotenv import load_dotenv

# 프로젝트 루트 기준으로 .env 로드
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 실행할 마이그레이션 SQL
MIGRATION_SQL = """
DROP TABLE IF EXISTS trades;

CREATE TABLE trades (
    id              BIGSERIAL PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL,
    price           NUMERIC NOT NULL,
    amount          NUMERIC NOT NULL,
    signal          TEXT,
    ma5             NUMERIC,
    ma20            NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""


def run_migration_via_rest():
    """
    Supabase Management API를 사용해 SQL을 실행합니다.
    (service_role 키가 필요합니다)
    """
    # project ref 추출: https://XXXX.supabase.co → XXXX
    project_ref = SUPABASE_URL.replace("https://", "").split(".")[0]

    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": MIGRATION_SQL}

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code in (200, 201):
        print("마이그레이션 성공!")
        return True
    else:
        print(f"Management API 실패 (status {response.status_code}): {response.text}")
        return False


def print_manual_instructions():
    """수동 실행 안내를 출력합니다."""
    print("\n" + "=" * 60)
    print("자동 실행에 실패했습니다.")
    print("Supabase 대시보드 → SQL Editor에서 아래 SQL을 실행하세요:")
    print("=" * 60)
    print(MIGRATION_SQL)
    print("=" * 60)


def main():
    # 환경변수 확인
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(".env 파일에 SUPABASE_URL과 SUPABASE_KEY를 입력하세요!")
        print_manual_instructions()
        sys.exit(1)

    print(f"Supabase 프로젝트에 마이그레이션 시도 중...")
    print(f"대상: {SUPABASE_URL}")

    # Management API로 실행 시도
    success = run_migration_via_rest()
    if not success:
        print_manual_instructions()
        sys.exit(1)

    # 테이블 생성 검증
    print("\n테이블 생성 검증 중...")
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        result = client.table("trades").select("id").limit(1).execute()
        print("trades 테이블 확인 완료!")
    except Exception as e:
        print(f"검증 실패 (테이블이 생성됐더라도 정상일 수 있음): {e}")


if __name__ == "__main__":
    main()
