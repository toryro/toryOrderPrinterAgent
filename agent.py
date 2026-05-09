"""
toryOrder 프린터 에이전트
- 백엔드 WebSocket에 연결해 NEW_ORDER / ORDER_CANCELLED 이벤트 수신 시 ESC/POS 출력
- NETWORK / SERIAL / FILE 세 가지 프린터 타입 지원
- 매장 설정(auto_kitchen_print, printer_config) 60초마다 자동 갱신
- 연결 끊김 시 지수 백오프 자동 재접속 (성공 시 3초로 리셋)
"""

import os
import json
import time
import threading
import requests
import websocket
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =========================================================
# 설정 로드 (.env 또는 시스템 환경변수)
# =========================================================
SERVER_URL   = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
STORE_ID     = int(os.getenv("STORE_ID", "1"))
EMAIL        = os.getenv("EMAIL", "")
PASSWORD     = os.getenv("PASSWORD", "")

PRINTER_TYPE = os.getenv("PRINTER_TYPE", "").upper()   # NETWORK | SERIAL | FILE | (빈칸=콘솔)
PRINTER_HOST = os.getenv("PRINTER_HOST", "")           # NETWORK 전용: IP 주소
PRINTER_PORT = os.getenv("PRINTER_PORT", "9100")       # NETWORK: 포트 / SERIAL: COM3, /dev/usb/lp0
PRINTER_BAUD = int(os.getenv("PRINTER_BAUD", "9600"))  # SERIAL 전용: 전송속도

SETTINGS_POLL_INTERVAL = int(os.getenv("SETTINGS_POLL_INTERVAL", "60"))  # 매장 설정 재조회 주기(초)

WS_HOST   = SERVER_URL.replace("http://", "").replace("https://", "")
WS_SCHEME = "wss" if SERVER_URL.startswith("https") else "ws"

# =========================================================
# 전역 상태
# =========================================================
_access_token       = None
_auto_kitchen_print = True
_printer_config     = "NONE"   # NONE | UNIFIED | SEPARATE
_printer            = None
_settings_lock      = threading.Lock()
_poller_started     = False


# =========================================================
# 로그인 & 설정 조회
# =========================================================
def login() -> str:
    resp = requests.post(
        f"{SERVER_URL}/token",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    print("[인증] 로그인 성공")
    return resp.json()["access_token"]


def fetch_store_settings(token: str) -> dict:
    resp = requests.get(
        f"{SERVER_URL}/stores/{STORE_ID}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def apply_settings(settings: dict):
    """서버에서 받은 설정을 전역 상태에 반영. 변경된 항목만 로그 출력."""
    global _auto_kitchen_print, _printer_config
    with _settings_lock:
        prev_auto = _auto_kitchen_print
        prev_cfg  = _printer_config
        _auto_kitchen_print = settings.get("auto_kitchen_print", True)
        _printer_config     = settings.get("printer_config", "NONE")

    changed = []
    if prev_auto != _auto_kitchen_print:
        changed.append(f"auto_kitchen_print {prev_auto} → {_auto_kitchen_print}")
    if prev_cfg != _printer_config:
        changed.append(f"printer_config {prev_cfg} → {_printer_config}")
    if changed:
        print(f"[설정 갱신] {', '.join(changed)}")


def _settings_poller():
    """SETTINGS_POLL_INTERVAL 초마다 매장 설정을 재조회해 전역 상태 갱신."""
    while True:
        time.sleep(SETTINGS_POLL_INTERVAL)
        try:
            if not _access_token:
                continue
            settings = fetch_store_settings(_access_token)
            apply_settings(settings)
        except Exception as e:
            print(f"[설정 갱신 실패] {e}")


# =========================================================
# ESC/POS 프린터 초기화
# =========================================================
def init_printer():
    global _printer
    if not PRINTER_TYPE:
        _printer = None
        return

    try:
        if PRINTER_TYPE == "NETWORK":
            from escpos.printer import Network
            _printer = Network(PRINTER_HOST, int(PRINTER_PORT or 9100), timeout=5)
            print(f"[프린터] NETWORK {PRINTER_HOST}:{PRINTER_PORT} 연결 완료")
        elif PRINTER_TYPE == "SERIAL":
            from escpos.printer import Serial
            _printer = Serial(PRINTER_PORT or "COM1", baudrate=PRINTER_BAUD, timeout=5)
            print(f"[프린터] SERIAL {PRINTER_PORT} @{PRINTER_BAUD}bps 연결 완료")
        elif PRINTER_TYPE == "FILE":
            from escpos.printer import File as FilePrinter
            _printer = FilePrinter(PRINTER_PORT)
            print(f"[프린터] FILE {PRINTER_PORT} 연결 완료")
        else:
            print(f"[프린터] 알 수 없는 타입({PRINTER_TYPE}), 콘솔 출력 모드")
            _printer = None
    except Exception as e:
        print(f"[프린터] 연결 실패 → 콘솔 출력 모드로 전환: {e}")
        _printer = None


# =========================================================
# 신규 주문서 출력
# =========================================================
def print_order(data: dict):
    order_num  = data.get("daily_number", data.get("order_id", "?"))
    table_name = data.get("table_name", "포장")
    created_at = data.get("created_at", "")[:16]
    order_type = "포장" if data.get("order_type") == "TAKEOUT" else "매장"
    pay_label  = "후불" if data.get("is_post_pay", False) else "선불"
    items      = data.get("items", [])

    if _printer:
        _print_order_escpos(order_num, table_name, created_at, order_type, pay_label, items)
    else:
        _print_order_console(order_num, table_name, created_at, order_type, pay_label, items)


def _print_order_escpos(order_num, table_name, created_at, order_type, pay_label, items):
    try:
        p = _printer
        p.set(align="center", bold=True, width=2, height=2)
        p.text("주  문  서\n")
        p.set(align="center", bold=False, width=1, height=1)
        p.text("-" * 32 + "\n")
        p.set(align="left", bold=True)
        p.text(f"번호: #{order_num}   [{order_type} / {pay_label}]\n")
        p.text(f"테이블: {table_name}\n")
        p.text(f"시각: {created_at}\n")
        p.text("-" * 32 + "\n")
        p.set(bold=False)
        for item in items:
            name = item.get("menu_name", "")
            qty  = item.get("quantity", 1)
            opts = item.get("options", "")
            p.text(f"{name}  x{qty}\n")
            if opts:
                p.text(f"  └ {opts}\n")
        p.text("-" * 32 + "\n")
        p.set(align="center", bold=True)
        p.text("★ 주방 전달 완료 ★\n\n")
        p.cut()
    except Exception as e:
        print(f"[프린터] ESC/POS 출력 오류: {e}")
        _print_order_console(order_num, table_name, created_at, order_type, pay_label, items)


def _print_order_console(order_num, table_name, created_at, order_type, pay_label, items):
    sep = "=" * 34
    print(f"\n{sep}")
    print(f"        주  문  서        ")
    print(sep)
    print(f"  번호 : #{order_num}   [{order_type} / {pay_label}]")
    print(f"  테이블: {table_name}")
    print(f"  시각  : {created_at}")
    print("-" * 34)
    for item in items:
        name = item.get("menu_name", "")
        qty  = item.get("quantity", 1)
        opts = item.get("options", "")
        print(f"  {name}  x{qty}")
        if opts:
            print(f"    └ {opts}")
    print("-" * 34)
    print("     ★ 주방 전달 완료 ★")
    print(f"{sep}\n")


# =========================================================
# 주문 취소 알림 출력
# =========================================================
def print_cancel(data: dict):
    order_id   = data.get("order_id", "?")
    is_partial = data.get("is_partial", False)
    label      = "부분 취소" if is_partial else "전체 취소"
    now        = datetime.now().strftime("%H:%M:%S")

    if _printer:
        _print_cancel_escpos(order_id, label, now)
    else:
        _print_cancel_console(order_id, label, now)


def _print_cancel_escpos(order_id, label, now):
    try:
        p = _printer
        p.set(align="center", bold=True, width=2, height=2)
        p.text("!! 취  소 !!\n")
        p.set(align="center", bold=False, width=1, height=1)
        p.text("-" * 32 + "\n")
        p.set(align="left", bold=True)
        p.text(f"주문번호: #{order_id}\n")
        p.text(f"취소유형: {label}\n")
        p.text(f"시각    : {now}\n")
        p.text("-" * 32 + "\n")
        p.set(align="center", bold=False)
        p.text("조리를 중단해 주세요.\n\n")
        p.cut()
    except Exception as e:
        print(f"[프린터] ESC/POS 취소 출력 오류: {e}")
        _print_cancel_console(order_id, label, now)


def _print_cancel_console(order_id, label, now):
    sep = "=" * 34
    print(f"\n{sep}")
    print(f"       !! 주문 취소 !!")
    print(sep)
    print(f"  주문번호: #{order_id}")
    print(f"  취소유형: {label}")
    print(f"  시각    : {now}")
    print("-" * 34)
    print("  조리를 중단해 주세요.")
    print(f"{sep}\n")


# =========================================================
# WebSocket 핸들러
# =========================================================
def on_message(ws, message):
    try:
        data     = json.loads(message)
        msg_type = data.get("type")
        ts       = datetime.now().strftime("%H:%M:%S")

        if msg_type == "NEW_ORDER":
            with _settings_lock:
                cfg  = _printer_config
                auto = _auto_kitchen_print

            if cfg == "NONE":
                print(f"[{ts}] 주문 수신 (printer_config=NONE, 건너뜀)")
            elif not auto:
                print(f"[{ts}] 주문 수신 (자동출력 OFF, 건너뜀)")
            else:
                print(f"[{ts}] 🔔 새 주문 수신 → 출력 시작")
                print_order(data)

        elif msg_type == "ORDER_CANCELLED":
            with _settings_lock:
                cfg = _printer_config

            if cfg != "NONE":
                label = "부분 취소" if data.get("is_partial") else "전체 취소"
                print(f"[{ts}] ❌ 주문 취소 수신 ({label}) → 출력 시작")
                print_cancel(data)

    except Exception as e:
        print(f"[오류] 메시지 처리 중 예외: {e}")


def on_error(ws, error):
    print(f"[WebSocket 오류] {error}")


def on_close(ws, code, msg):
    print(f"[연결 종료] code={code}")


def on_open(ws):
    with _settings_lock:
        auto = _auto_kitchen_print
        cfg  = _printer_config
    hw = "ESC/POS" if _printer else "콘솔"
    print(f"[연결] Store #{STORE_ID} 프린터 에이전트 가동 중 (Ctrl+C 로 종료)")
    print(f"       자동출력: {'ON' if auto else 'OFF'}  |  구성: {cfg}  |  하드웨어: {hw}")


# =========================================================
# 메인 루프 (자동 재접속)
# =========================================================
def run():
    global _access_token, _poller_started

    retry_delay = 3

    while True:
        try:
            # 1. 로그인
            _access_token = login()

            # 2. 매장 설정 조회 & 적용
            settings = fetch_store_settings(_access_token)
            apply_settings(settings)
            print(f"[설정] printer_config={_printer_config}, auto_kitchen_print={_auto_kitchen_print}")

            # 3. 설정 폴링 스레드 (최초 1회만 시작)
            if not _poller_started:
                t = threading.Thread(target=_settings_poller, daemon=True)
                t.start()
                _poller_started = True

            # 4. ESC/POS 프린터 초기화
            init_printer()

            # 5. 연결 성공 시 retry_delay 리셋
            retry_delay = 3

            # 6. WebSocket 연결 (블로킹)
            ws_url = f"{WS_SCHEME}://{WS_HOST}/ws/{STORE_ID}?token={_access_token}"
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)

            # run_forever 종료 = 연결 끊김 → 재접속
            print(f"[재접속] {retry_delay}초 후 재시도...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

        except requests.exceptions.RequestException as e:
            print(f"[오류] 서버 연결 실패: {e}  ({retry_delay}초 후 재시도)")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        except KeyboardInterrupt:
            print("\n[종료] 프린터 에이전트를 종료합니다.")
            break


if __name__ == "__main__":
    if not EMAIL or not PASSWORD:
        print("[오류] .env 파일에 EMAIL과 PASSWORD를 설정해주세요.")
        print("       .env.example 파일을 참고하세요.")
        exit(1)
    run()
