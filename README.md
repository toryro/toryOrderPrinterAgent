# toryOrder 프린터 에이전트 실행 가이드

매장 PC에서 실행하는 로컬 프로그램으로, toryOrder 백엔드 서버에 WebSocket으로 연결해  
신규 주문·수납 완료·주문 취소 발생 시 ESC/POS 열화지 프린터로 자동 출력합니다.

---

## 목차

1. [출력 양식](#1-출력-양식)
2. [동작 흐름](#2-동작-흐름)
3. [요구사항](#3-요구사항)
4. [설치](#4-설치)
5. [설정 (.env)](#5-설정-env)
6. [프린터 연결 방식](#6-프린터-연결-방식)
7. [실행](#7-실행)
8. [백그라운드 자동 실행](#8-백그라운드-자동-실행)
9. [가상 출력 미리보기 (테스트)](#9-가상-출력-미리보기-테스트)
10. [문제 해결](#10-문제-해결)

---

## 1. 출력 양식

| 이벤트 | 출력물 | 조건 |
|--------|--------|------|
| 신규 주문 접수 | **주방 주문서** | `auto_kitchen_print = ON` |
| 선불 주문 완료 | 주방 주문서 + **영수증** | 동시 출력 |
| 후불 수납 완료 | **영수증** | 결제수단·합계·부가세 포함 |
| 주문 취소 | **취소 알림** | 전체·부분 취소 구분 |

### 주방 주문서
```
==================================
        주  문  서
==================================
  번호 : #42   [매장 / 후불]
  테이블: A-3
  시각  : 2026-05-09 17:00
----------------------------------
  아메리카노  x2
    └ HOT, 샷 추가
  카페라떼  x1
----------------------------------
     ★ 주방 전달 완료 ★
==================================
```

### 영수증
```
====================================
          영  수  증
         토리오더 강남본점
====================================
  영수증번호: #42   [매장]
  일시    : 2026-05-09 17:00
  테이블  : A-3
------------------------------------
  품목              수량            금액
------------------------------------
  아메리카노            2         9,000
  카페라떼             1         5,000
====================================
  부가세(포함)                    1,272
====================================
  합  계  :  14,000원
  결제수단:  카드
------------------------------------
     감사합니다. 또 방문해주세요!
====================================
```

### 취소 알림
```
==================================
       !! 주문 취소 !!
==================================
  주문번호: #42
  취소유형: 전체 취소
  시각    : 17:05:30
----------------------------------
  조리를 중단해 주세요.
==================================
```

---

## 2. 동작 흐름

```
매장 PC (agent.py)
    │
    ├─ 시작 시 ──▶ 로그인 (EMAIL / PASSWORD)
    │            ──▶ 매장 설정 조회 (printer_config, auto_kitchen_print)
    │            ──▶ 프린터 초기화 (NETWORK / SERIAL / FILE)
    │            ──▶ WebSocket 연결
    │
    ├─ 주문 접수 ──▶ NEW_ORDER 수신
    │               ├─ printer_config = NONE  → 건너뜀
    │               ├─ auto_kitchen_print OFF → 건너뜀
    │               ├─ is_post_pay = true     → 주방 주문서 출력
    │               └─ is_post_pay = false    → 주방 주문서 + 영수증 출력
    │
    ├─ 수납 완료 ──▶ PAYMENT_COLLECTED 수신 → 영수증 출력
    │
    ├─ 주문 취소 ──▶ ORDER_CANCELLED 수신  → 취소 알림 출력
    │
    └─ 연결 끊김 ──▶ 자동 재접속 (3초 → 최대 60초 지수 백오프)
```

매장 설정(`printer_config`, `auto_kitchen_print`)은 **60초마다 자동 갱신**되므로  
관리자 페이지에서 변경한 설정이 재시작 없이 반영됩니다.

---

## 3. 요구사항

| 항목 | 최소 버전 |
|------|-----------|
| Python | 3.9 이상 |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 |
| 네트워크 | 백엔드 서버 접근 가능 |

---

## 4. 설치

```bash
# 1. 저장소 클론
git clone https://github.com/toryro/toryOrderPrinterAgent.git
cd toryOrderPrinterAgent

# 2. 가상환경 생성 및 활성화
python3 -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. 패키지 설치
pip install -r requirements.txt
```

---

## 5. 설정 (.env)

`.env.example`을 복사해 `.env` 파일을 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

### 필수 설정

| 항목 | 설명 | 예시 |
|------|------|------|
| `SERVER_URL` | 백엔드 서버 주소 | `https://order.manytory.com` |
| `STORE_ID` | 매장 ID (관리자 페이지 URL 숫자) | `1` |
| `EMAIL` | 매장 계정 이메일 | `owner@example.com` |
| `PASSWORD` | 매장 계정 비밀번호 | `mypassword` |

### 프린터 설정

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `PRINTER_TYPE` | 연결 방식 (`NETWORK` / `SERIAL` / `FILE` / 빈칸) | 빈칸 (콘솔) |
| `PRINTER_HOST` | 프린터 IP (NETWORK 전용) | |
| `PRINTER_PORT` | 포트 / 장치 경로 | `9100` |
| `PRINTER_BAUD` | 전송속도 (SERIAL 전용) | `9600` |

### 기타 설정

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `SETTINGS_POLL_INTERVAL` | 매장 설정 재조회 주기 (초) | `60` |

---

## 6. 프린터 연결 방식

### ① NETWORK — LAN / Wi-Fi 소켓 통신 *(가장 보편적)*

열화지 프린터에 LAN 케이블 또는 Wi-Fi를 연결하고 고정 IP를 할당합니다.

```env
PRINTER_TYPE=NETWORK
PRINTER_HOST=192.168.0.100
PRINTER_PORT=9100
```

**대표 기기**: Epson TM-T88VI, Star TSP100III, Bixolon SRP-350III  
**장점**: 설치 간편, 여러 PC에서 공유 가능  
**단점**: 프린터 IP 고정 필요, 공유기 설정 필요

---

### ② SERIAL — RS-232 / USB-Serial 통신

DB9 시리얼 케이블 또는 USB-to-Serial 어댑터로 PC에 직접 연결합니다.

```env
# Windows
PRINTER_TYPE=SERIAL
PRINTER_PORT=COM3
PRINTER_BAUD=9600

# Linux / macOS
PRINTER_TYPE=SERIAL
PRINTER_PORT=/dev/ttyUSB0
PRINTER_BAUD=9600
```

**장치 경로 확인**

```bash
# Windows: 장치 관리자 → 포트(COM & LPT)
# Linux
ls /dev/ttyUSB* /dev/ttyS*
# macOS
ls /dev/tty.usb*
```

**대표 기기**: Epson TM-U220, Bixolon SRP-275, Star SP700  
**장점**: 신뢰성 높음, 구형 POS 환경에 적합  
**단점**: 연결된 PC 전용, 거리 제한 15m

---

### ③ USB Direct — Linux 디바이스 파일

Linux에서 USB 프린터를 드라이버 없이 직접 파일로 씁니다.

```env
PRINTER_TYPE=FILE
PRINTER_PORT=/dev/usb/lp0
```

**권한 설정 (최초 1회)**

```bash
sudo usermod -a -G lp $USER
# 또는
sudo chmod 666 /dev/usb/lp0
```

**대표 기기**: Epson TM-T20III, Star TSP143III, HOIN HOP-E200  
**장점**: 드라이버 불필요, 라즈베리파이에 최적  
**단점**: Linux 전용

---

### ④ FILE — 파일 직접 쓰기

ESC/POS 명령을 파일 경로에 직접 씁니다. USB Direct와 동일한 방식이며  
`/tmp/printer_test.bin`처럼 임시 파일로 설정하면 테스트에도 활용할 수 있습니다.

```env
PRINTER_TYPE=FILE
PRINTER_PORT=/dev/usb/lp0
```

---

### ⑤ Bluetooth — 무선 BT-Serial SPP

Bluetooth SPP(Serial Port Profile) 페어링 후 가상 시리얼 포트로 연결합니다.

```bash
# Linux: 페어링 및 rfcomm 바인딩
bluetoothctl pair AA:BB:CC:DD:EE:FF
sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF
```

```env
# Linux
PRINTER_TYPE=SERIAL
PRINTER_PORT=/dev/rfcomm0
PRINTER_BAUD=9600

# Windows (장치 관리자에서 COM 번호 확인)
PRINTER_TYPE=SERIAL
PRINTER_PORT=COM6
PRINTER_BAUD=9600
```

**대표 기기**: Star SM-L200, Epson TM-P20, HOIN HOP-E200BT  
**장점**: 무선, 모바일 운영에 적합  
**단점**: 거리 제한 10m, 연결 불안정 가능

---

### ⑥ 콘솔 출력 (테스트용)

`PRINTER_TYPE`을 비워두면 실제 프린터 없이 터미널에 출력합니다.  
프린터 없이 동작을 확인할 때 사용합니다.

```env
PRINTER_TYPE=
```

---

## 7. 실행

```bash
# 가상환경 활성화 후
python agent.py
```

### 정상 실행 로그 예시

```
[인증] 로그인 성공
[설정] printer_config=UNIFIED, auto_kitchen_print=True
[프린터] NETWORK 192.168.0.100:9100 연결 완료
[연결] Store #1 프린터 에이전트 가동 중 (Ctrl+C 로 종료)
       자동출력: ON  |  구성: UNIFIED  |  하드웨어: ESC/POS

[17:00:15] 🔔 새 주문 수신 → 주방 주문서 출력
[17:01:32] 💳 후불 수납 완료 #5 → 영수증 출력
[17:03:10] ❌ 주문 취소 수신 (전체 취소) → 출력 시작
```

종료: `Ctrl + C`

---

## 8. 백그라운드 자동 실행

### Windows — 작업 스케줄러

1. `작업 스케줄러` 열기
2. `기본 작업 만들기` → 트리거: **컴퓨터 시작 시**
3. 동작: **프로그램 시작**
   - 프로그램: `C:\path\to\.venv\Scripts\python.exe`
   - 인수: `agent.py`
   - 시작 위치: `C:\path\to\toryOrderPrinterAgent`

### macOS — launchd

`~/Library/LaunchAgents/com.toryorder.printer.plist` 생성:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.toryorder.printer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/.venv/bin/python3</string>
    <string>/path/to/toryOrderPrinterAgent/agent.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/toryOrderPrinterAgent</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/toryorder_printer.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/toryorder_printer.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.toryorder.printer.plist
```

### Linux — systemd

`/etc/systemd/system/toryorder-printer.service` 생성:

```ini
[Unit]
Description=toryOrder Printer Agent
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/toryOrderPrinterAgent
ExecStart=/home/ubuntu/toryOrderPrinterAgent/.venv/bin/python3 agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable toryorder-printer
sudo systemctl start toryorder-printer

# 로그 확인
journalctl -u toryorder-printer -f
```

---

## 9. 가상 출력 미리보기 (테스트)

실제 프린터 없이 출력 양식을 터미널에서 미리 확인할 수 있습니다.

```bash
python test_printer_virtual.py
```

5가지 프린터 연결 방식 안내와 주방 주문서·영수증·취소 알림 미리보기를 출력합니다.

---

## 10. 문제 해결

### 로그인 실패
```
[오류] 서버 연결 실패: ...
```
- `.env`의 `SERVER_URL`, `EMAIL`, `PASSWORD` 확인
- 서버가 실행 중인지 확인

### 출력이 안 됨 (건너뜀 로그)
```
주문 수신 (printer_config=NONE, 건너뜀)
주문 수신 (자동출력 OFF, 건너뜀)
```
- 관리자 페이지 → 매장 설정에서 **프린터 구성**과 **자동 출력** 활성화
- 설정 변경 후 최대 60초 내 자동 반영 (재시작 불필요)

### 프린터 연결 실패 → 콘솔 모드로 전환
```
[프린터] 연결 실패 → 콘솔 출력 모드로 전환: ...
```
- NETWORK: `PRINTER_HOST` IP 주소 및 방화벽 확인, 포트 9100 개방 여부 확인
- SERIAL: 장치 경로(`COM3`, `/dev/ttyUSB0`) 및 권한 확인
- FILE: 경로 존재 여부 및 쓰기 권한 확인

### SERIAL 권한 오류 (Linux)
```bash
sudo usermod -a -G dialout $USER
# 로그아웃 후 재로그인 필요
```

### WebSocket 연결 끊김 반복
```
[재접속] 6초 후 재시도...
[재접속] 12초 후 재시도...
```
- 네트워크 연결 상태 확인
- 서버 URL이 `https://`인 경우 WebSocket은 자동으로 `wss://` 사용
- 서버 방화벽에서 WebSocket 포트 개방 여부 확인
