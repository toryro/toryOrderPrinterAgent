import websocket
import json
import threading
import time

# --- 설정값 ---
STORE_ID = 4
WS_URL = f"ws://127.0.0.1:8000/ws/{STORE_ID}"

# --- 영수증 출력 함수 (업그레이드 버전) ---
def print_receipt(order_data):
    print("\n" + "▒"*30) # 조금 더 영수증 느낌나게
    print(f"      [ 주 문 서 ]      ")
    print("▒"*30)
    print(f"주문번호 : {order_data['order_id']}")
    print(f"테 이 블 : {order_data['table_id']}번")
    print(f"주문시간 : {order_data['created_at'][:19]}") # 초 단위까지만 자르기
    print("-" * 30)
    
    # [수정] 메뉴 리스트 출력 부분
    print(f"{'메뉴명':<10} {'수량':^5} {'금액':>7}")
    print("-" * 30)
    
    items = order_data.get('items', [])
    for item in items:
        # 한글 정렬은 터미널마다 다르므로 단순 나열 방식으로 출력
        # 예: 야채김밥 (2) ... 7000
        name = item['menu_name']
        qty = item['quantity']
        price = item['subtotal']
        
        print(f"{name} ({qty}개)") 
        print(f"{' ':<18} ￦{price:,}") # 천단위 콤마 찍기

    print("-" * 30)
    print(f"총 결제금액 :       ￦{order_data['total_price']:,}")
    print("-" * 30)
    print("      주방으로 전달됨      ")
    print("▒"*30 + "\n")

# --- WebSocket 이벤트 핸들러 ---
def on_message(ws, message):
    try:
        data = json.loads(message)
        # print(f"[디버그] 수신 데이터: {data}") # 데이터 확인하고 싶으면 주석 해제

        if data.get("type") == "NEW_ORDER":
            print("🔔 찌이익~ (주문이 도착해 출력합니다)")
            print_receipt(data)
            
    except Exception as e:
        print(f"에러 발생: {e}")

def on_error(ws, error):
    print(f"[에러] {error}")

def on_close(ws, close_status_code, close_msg):
    print("[종료] 서버와 연결이 끊어졌습니다.")

def on_open(ws):
    print(f"[연결] Store {STORE_ID}번 프린터 에이전트 가동 (Ctrl+C로 종료)")

# --- 메인 실행부 ---
if __name__ == "__main__":
    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(WS_URL,
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()