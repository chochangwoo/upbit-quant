"""
연결 테스트 스크립트
실행 방법: python tests/test_connections.py

업비트, Supabase, 텔레그램 연결이 모두 정상인지 확인합니다.
"""
from dotenv import load_dotenv
load_dotenv()

# ========== 1. 업비트 연결 테스트 ==========
print("\n[1/3] 업비트 연결 테스트 중...")
try:
    import pyupbit
    import os

    access = os.getenv("UPBIT_ACCESS_KEY")
    secret = os.getenv("UPBIT_SECRET_KEY")

    upbit = pyupbit.Upbit(access, secret)
    balance = upbit.get_balance("KRW")  # 보유 원화 잔고 조회
    print(f"  ✅ 업비트 연결 성공! 보유 원화: {balance:,.0f}원")
except Exception as e:
    print(f"  ❌ 업비트 연결 실패: {e}")
    print("     → .env 파일의 UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY를 확인하세요")

# ========== 2. Supabase 연결 테스트 ==========
print("\n[2/3] Supabase 연결 테스트 중...")
try:
    from supabase import create_client
    import os

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    client = create_client(url, key)
    # trades 테이블에서 데이터 1개 조회 (테이블이 존재하는지 확인)
    result = client.table("trades").select("*").limit(1).execute()
    print(f"  ✅ Supabase 연결 성공! trades 테이블 확인 완료")
except Exception as e:
    print(f"  ❌ Supabase 연결 실패: {e}")
    print("     → .env 파일의 SUPABASE_URL, SUPABASE_KEY를 확인하세요")
    print("     → Supabase SQL Editor에서 테이블 생성 SQL을 실행했는지 확인하세요")

# ========== 3. 텔레그램 연결 테스트 ==========
print("\n[3/3] 텔레그램 연결 테스트 중...")
try:
    import requests
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, json={
        "chat_id": chat_id,
        "text": "✅ 업비트 자동매매 봇 연결 테스트 성공!\n\n모든 설정이 정상입니다."
    })

    if response.status_code == 200:
        print(f"  ✅ 텔레그램 연결 성공! 봇 메시지를 확인하세요.")
    else:
        print(f"  ❌ 텔레그램 전송 실패: {response.text}")
except Exception as e:
    print(f"  ❌ 텔레그램 연결 실패: {e}")
    print("     → .env 파일의 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 확인하세요")

print("\n==============================")
print("테스트 완료! 위에 ✅만 있으면 다음 단계로 진행하세요.")
print("==============================\n")
