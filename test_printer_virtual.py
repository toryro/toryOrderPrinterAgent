"""
가상 프린터 테스트 스크립트
- 5가지 프린터 연결 방식 설명
- ESC/POS Dummy 프린터로 바이트 크기 검증
- 주방 주문서 / 영수증 / 취소 알림 미리보기
"""

from datetime import datetime
from escpos.printer import Dummy

# ─────────────────────────────────────────────
# 5가지 프린터 타입 정보
# ─────────────────────────────────────────────
PRINTER_TYPES = [
    {
        "no": 1,
        "type": "NETWORK (LAN/Wi-Fi 소켓통신)",
        "connection": "TCP/IP → IP:9100 (raw socket)",
        "examples": "Epson TM-T88VI, Star TSP100III, Bixolon SRP-350III",
        "env": ["PRINTER_TYPE=NETWORK", "PRINTER_HOST=192.168.0.100", "PRINTER_PORT=9100"],
        "pros": "설치 간편, 멀티 PC 공유 가능, 거리 제한 없음",
        "cons": "IP 고정 필요, 공유기 설정 필요",
    },
    {
        "no": 2,
        "type": "SERIAL (시리얼/USB-Serial 통신)",
        "connection": "RS-232 또는 USB-to-Serial → COM3 / /dev/ttyUSB0",
        "examples": "Epson TM-U220, Bixolon SRP-275, Star SP700",
        "env": ["PRINTER_TYPE=SERIAL", "PRINTER_PORT=COM3", "PRINTER_BAUD=9600"],
        "pros": "신뢰성 높음, 구형 POS 환경에 적합",
        "cons": "연결된 PC 전용, 거리 제한 15m, 드라이버 필요",
    },
    {
        "no": 3,
        "type": "USB Direct (USB 클래스 프린터)",
        "connection": "USB → /dev/usb/lp0 (Linux) / WinUSB (Windows)",
        "examples": "Epson TM-T20III, Star TSP143III, HOIN HOP-E200",
        "env": ["PRINTER_TYPE=FILE", "PRINTER_PORT=/dev/usb/lp0"],
        "pros": "Linux에서 드라이버 불필요, 빠른 응답",
        "cons": "연결된 PC 전용, Windows는 드라이버 설치 필요",
    },
    {
        "no": 4,
        "type": "FILE (Linux 디바이스 파일 직접 쓰기)",
        "connection": "파일 쓰기 → /dev/usb/lp0 또는 /tmp/printer.bin",
        "examples": "라즈베리파이 연결 모든 ESC/POS 프린터",
        "env": ["PRINTER_TYPE=FILE", "PRINTER_PORT=/dev/usb/lp0"],
        "pros": "라즈베리파이 등 임베디드 최적, 설정 단순",
        "cons": "Linux 전용, 파일 권한(chmod) 설정 필요",
    },
    {
        "no": 5,
        "type": "Bluetooth (무선 BT-Serial SPP)",
        "connection": "Bluetooth SPP → /dev/rfcomm0 (Linux) / COM6 (Windows)",
        "examples": "Star SM-L200, Epson TM-P20, HOIN HOP-E200BT",
        "env": ["PRINTER_TYPE=SERIAL", "PRINTER_PORT=/dev/rfcomm0", "PRINTER_BAUD=9600"],
        "pros": "무선, 모바일 운영에 적합, 케이블 불필요",
        "cons": "거리 제한 10m, 연결 불안정 가능, 페어링 필요",
    },
]

# ─────────────────────────────────────────────
# 샘플 주문 데이터
# ─────────────────────────────────────────────
ORDER = {
    "daily_number": 42,
    "table_name": "A-3",
    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "order_type": "DINE_IN",
    "is_post_pay": True,
    "items": [
        {"menu_name": "아메리카노",  "quantity": 2, "unit_price": 4500, "options": "HOT, 샷 추가"},
        {"menu_name": "카페라떼",    "quantity": 1, "unit_price": 5000, "options": "ICE"},
        {"menu_name": "치즈케이크",  "quantity": 1, "unit_price": 7000, "options": ""},
    ],
}

CANCEL = {
    "order_id": 42,
    "is_partial": False,
}

# ─────────────────────────────────────────────
# 용지 렌더러
# ─────────────────────────────────────────────
W = 38  # 용지 출력 너비 (문자 수)

def paper(lines: list[str], title: str = "") -> str:
    top    = "  ╔" + "═" * W + "╗"
    ttl    = f"  ║ {title:^{W-2}} ║"
    bot    = "  ╚" + "═" * W + "╝"
    rule_t = "  ┌" + "─" * W + "┐"
    rule_b = "  └" + "─" * W + "┘"
    cut    = "     ✂  ✂  ✂  (자동 컷)  ✂  ✂  ✂"

    result = [top, ttl, bot, rule_t]
    for line in lines:
        # 한글 포함 시 디스플레이 폭 계산 (한글 2칸, 영문 1칸)
        display_w = sum(2 if ord(c) > 0x7F else 1 for c in line)
        pad = W - display_w - 2
        result.append(f"  │ {line}{' ' * max(0, pad)} │")
    result += [rule_b, cut]
    return "\n".join(result)

def sep_line(char="-"):
    return char * 30

def center(text: str):
    display_w = sum(2 if ord(c) > 0x7F else 1 for c in text)
    pad = max(0, (W - 2 - display_w) // 2)
    return " " * pad + text

def rjust_amount(label: str, amount: str, total_w: int = 30) -> str:
    label_w = sum(2 if ord(c) > 0x7F else 1 for c in label)
    amount_w = len(amount)
    pad = total_w - label_w - amount_w
    return label + " " * max(1, pad) + amount

# ─────────────────────────────────────────────
# 주방 주문서
# ─────────────────────────────────────────────
def kitchen_order_lines(order: dict) -> list[str]:
    num   = order["daily_number"]
    table = order["table_name"]
    time  = order["created_at"]
    otype = "포장" if order.get("order_type") == "TAKEOUT" else "매장"
    pay   = "후불" if order.get("is_post_pay") else "선불"
    items = order["items"]

    lines = []
    lines.append(center("주  문  서"))
    lines.append(sep_line())
    lines.append(f"번호: #{num}   [{otype} / {pay}]")
    lines.append(f"테이블: {table}")
    lines.append(f"시각: {time}")
    lines.append(sep_line())
    for item in items:
        lines.append(f"{item['menu_name']}  x{item['quantity']}")
        if item.get("options"):
            lines.append(f"  └ {item['options']}")
    lines.append(sep_line())
    lines.append(center("★ 주방 전달 완료 ★"))
    lines.append("")
    return lines

# ─────────────────────────────────────────────
# 영수증
# ─────────────────────────────────────────────
def receipt_lines(order: dict) -> list[str]:
    items    = order["items"]
    subtotal = sum(i["unit_price"] * i["quantity"] for i in items)
    tax      = int(subtotal / 11)
    total    = subtotal

    lines = []
    lines.append(center("영  수  증"))
    lines.append(center("ToryOrder Coffee"))
    lines.append(center("서울시 강남구 테헤란로 123"))
    lines.append(center("TEL: 02-1234-5678"))
    lines.append(sep_line("="))
    lines.append(f"영수증번호: #{order['daily_number']}")
    lines.append(f"일시: {order['created_at']}")
    lines.append(f"테이블: {order['table_name']}")
    lines.append(sep_line())
    lines.append(f"{'품목':<12}{'수량':>4}{'금액':>12}")
    lines.append(sep_line())
    for item in items:
        price = item["unit_price"] * item["quantity"]
        lines.append(f"{item['menu_name']:<12}{item['quantity']:>4}{price:>12,}")
    lines.append(sep_line("="))
    lines.append(rjust_amount("소계", f"{subtotal:,}원"))
    lines.append(rjust_amount("부가세(포함)", f"{tax:,}원"))
    lines.append(sep_line("="))
    lines.append(center(f"[ 합  계:  {total:,}원 ]"))
    lines.append(sep_line("="))
    lines.append(center("감사합니다. 또 방문해주세요!"))
    lines.append(center("* 영수증 분실 시 재발급 불가"))
    lines.append("")
    return lines

# ─────────────────────────────────────────────
# 취소 알림
# ─────────────────────────────────────────────
def cancel_lines(data: dict) -> list[str]:
    label = "부분 취소" if data.get("is_partial") else "전체 취소"
    now   = datetime.now().strftime("%H:%M:%S")

    lines = []
    lines.append(center("!!  취  소  !!"))
    lines.append(sep_line())
    lines.append(f"주문번호: #{data['order_id']}")
    lines.append(f"취소유형: {label}")
    lines.append(f"시각    : {now}")
    lines.append(sep_line())
    lines.append(center("조리를 중단해 주세요."))
    lines.append("")
    return lines

# ─────────────────────────────────────────────
# ESC/POS Dummy 바이트 수 측정
# ─────────────────────────────────────────────
def measure_escpos(order: dict, cancel: dict) -> dict:
    def kitchen(p):
        num, table, time_ = order["daily_number"], order["table_name"], order["created_at"]
        otype = "포장" if order.get("order_type") == "TAKEOUT" else "매장"
        pay = "후불" if order.get("is_post_pay") else "선불"
        p.set(align="center", bold=True, width=2, height=2)
        p.text("주  문  서\n")
        p.set(align="center", bold=False, width=1, height=1)
        p.text("-" * 32 + "\n")
        p.set(align="left", bold=True)
        p.text(f"번호: #{num}   [{otype} / {pay}]\n")
        p.text(f"테이블: {table}\n시각: {time_}\n")
        p.text("-" * 32 + "\n")
        p.set(bold=False)
        for item in order["items"]:
            p.text(f"{item['menu_name']}  x{item['quantity']}\n")
            if item.get("options"):
                p.text(f"  └ {item['options']}\n")
        p.text("-" * 32 + "\n")
        p.set(align="center", bold=True)
        p.text("★ 주방 전달 완료 ★\n\n")
        p.cut()

    def receipt(p):
        items = order["items"]
        subtotal = sum(i["unit_price"] * i["quantity"] for i in items)
        p.set(align="center", bold=True, width=2, height=2)
        p.text("영  수  증\n")
        p.set(align="center", bold=False, width=1, height=1)
        p.text("ToryOrder Coffee\n")
        p.text(f"영수증번호: #{order['daily_number']}\n")
        p.text("=" * 32 + "\n")
        p.set(align="left", bold=False)
        for item in items:
            p.text(f"{item['menu_name']}  x{item['quantity']}  {item['unit_price']*item['quantity']:,}\n")
        p.text("=" * 32 + "\n")
        p.set(align="center", bold=True, width=2, height=1)
        p.text(f"합계: {subtotal:,}원\n")
        p.set(align="center", bold=False, width=1, height=1)
        p.text("감사합니다!\n\n")
        p.cut()

    def cancel_fn(p):
        p.set(align="center", bold=True, width=2, height=2)
        p.text("!! 취  소 !!\n")
        p.set(bold=False, width=1, height=1)
        p.text(f"주문번호: #{cancel['order_id']}\n")
        p.cut()

    p1, p2, p3 = Dummy(), Dummy(), Dummy()
    kitchen(p1)
    receipt(p2)
    cancel_fn(p3)
    return {
        "주방 주문서": len(p1.output),
        "영수증": len(p2.output),
        "취소 알림": len(p3.output),
    }

# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
SEP = "\n" + "━" * 62

def main():
    # 1. 프린터 타입 안내
    print(SEP)
    print("  📠  시중 영수증 프린터 5가지 연결 방식")
    print(SEP)
    for pt in PRINTER_TYPES:
        print(f"\n  [{pt['no']}] {pt['type']}")
        print(f"       연결 : {pt['connection']}")
        print(f"       기기 : {pt['examples']}")
        print(f"       .env : {' / '.join(pt['env'])}")
        print(f"       장점 : {pt['pros']}")
        print(f"       단점 : {pt['cons']}")

    # 2. 주방 주문서
    print(SEP)
    print("  🍳  주방 주문서 출력 미리보기")
    print(SEP + "\n")
    print(paper(kitchen_order_lines(ORDER), title=" 주방 주문서 "))

    # 3. 영수증
    print(SEP)
    print("  🧾  영수증 출력 미리보기")
    print(SEP + "\n")
    print(paper(receipt_lines(ORDER), title="    영  수  증    "))

    # 4. 취소 알림
    print(SEP)
    print("  ❌  주문 취소 알림 출력 미리보기")
    print(SEP + "\n")
    print(paper(cancel_lines(CANCEL), title="  주문 취소 알림  "))

    # 5. ESC/POS 바이트 크기
    print(SEP)
    print("  💾  ESC/POS 원시 바이트 크기 (실제 프린터 전송량)")
    print(SEP)
    sizes = measure_escpos(ORDER, CANCEL)
    for name, size in sizes.items():
        print(f"       {name:<12}: {size:,} bytes")

    print(SEP)
    print("  ✅  가상 테스트 완료")
    print("      실제 프린터 연결 → .env에 PRINTER_TYPE 설정 후 agent.py 실행")
    print(SEP + "\n")


if __name__ == "__main__":
    main()
