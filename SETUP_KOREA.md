# 한국 IP 서버 세팅 가이드 (해외 차단 사이트 실시간 감시)

GitHub Actions(해외 IP)에서 차단·불안정한 한국 정부사이트를 **한국 IP에서 직접**
감시하기 위한 가이드입니다. 현재 대상:
- **서울정보소통광장(opengov.seoul.go.kr) 결재문서** — 서버 키워드 검색으로
  서울시 본청 + 사업소 + 25개 자치구를 모두 커버
  (10개 키워드: 재개발·재건축·신속통합·모아타운·도심복합·정비계획·정비구역·정비사업·후보지·동의서)

> 정보공개포털(open.go.kr)은 서울 문서에 한해 opengov와 같은 내용의 중복 창구라
> 연동하지 않습니다(orginlInfoList.ajax가 브라우저 외 요청을 491로 거부하는 점도 확인).

- GitHub Actions는 지금처럼 그대로 둡니다(블로그·부리니·카페·잘 되는 구청들).
- 한국 서버에서는 `check_korea.py`만 cron으로 돌립니다.
- 알림은 **같은 텔레그램 봇**으로 가서, 사용자는 같은 채팅에서 함께 받습니다.
- 상태 파일 `seen_korea.json`은 이 서버 로컬에만 저장됩니다(git 커밋 안 함).

---

## A. 오라클 클라우드 서울 리전 무료 VM 만들기

> 회사는 미국이지만 **리전을 "서울(South Korea Central, ap-seoul-1)"로 고르면 한국 IP**를 받습니다.

1. https://www.oracle.com/kr/cloud/free/ 에서 무료 계정 가입 (신용카드 인증 필요, 무료 티어는 청구 안 됨).
2. 가입 중 **홈 리전을 "대한민국 중부(춘천)" 또는 "대한민국(서울)"** 으로 선택.
   (둘 다 한국 IP입니다. 서울이 없으면 춘천으로.)
3. 콘솔 로그인 → **Compute → Instances → Create Instance**
   - Image: **Ubuntu 22.04** (또는 24.04)
   - Shape: **Always Free 대상** — `VM.Standard.E2.1.Micro`(AMD) 권장.
     (ARM `A1.Flex`는 무료지만 "용량 부족"이 잦음. Micro가 무난.)
   - **SSH 키**: "Generate a key pair for me" 선택 후 **개인키 다운로드**(꼭 저장).
   - Create 클릭 → 1~2분 뒤 **Public IP** 확인.

## B. 서버 접속 + 환경 준비

```bash
# 내 PC에서 (다운로드한 키 경로로)
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<서버_Public_IP>

# 서버 안에서
sudo apt update && sudo apt install -y python3-pip git
git clone https://github.com/para333311/realty-telegram-bot.git
cd realty-telegram-bot
pip3 install requests beautifulsoup4
```

## C. 텔레그램 시크릿 설정

GitHub에 등록한 것과 **같은 값**을 쓰면 같은 채팅으로 옵니다.

```bash
# ~/realty-telegram-bot/.env 파일 생성
cat > ~/realty-telegram-bot/.env <<'EOF'
BOARD_BOT_TOKEN=여기에_재재보드봇_토큰
TELEGRAM_CHAT_ID=여기에_채팅ID
EOF
pip3 install python-dotenv   # .env 자동 로드용
```

## D. 먼저 디버그로 실제 페이지 구조 확인 (중요)

opengov 페이지 구조를 서버(한국 IP)에서 한 번 확인합니다. **알림/저장 안 하고 출력만** 합니다.

```bash
cd ~/realty-telegram-bot
DEBUG=1 python3 check_korea.py
```

- `HTTP 200`이 뜨고 `id=... [날짜] 제목`들이 출력되면 **접속·파싱 성공**입니다.
- 이 출력(특히 `[DEBUG] 첫 행 원본텍스트 예:`)을 저(클로드)에게 붙여주시면,
  파싱이 어긋난 부분이 있으면 정밀 튜닝해서 커밋하겠습니다.
- 만약 `HTTP 403`이나 문서가 0개면, opengov가 데이터센터 IP도 막는 경우라
  집 서버(가정용 IP) 방식으로 전환해야 합니다 — 그 결과도 알려주세요.

## E. 정상 확인되면 실제 실행 + cron 등록

```bash
# 실제 1회 실행 (첫 실행은 "감시 시작" 안내만 오고 기준선 저장)
cd ~/realty-telegram-bot && python3 check_korea.py

# 30분마다 자동 실행 등록
crontab -e
# 편집기가 열리면 아래 한 줄 추가 후 저장:
*/30 * * * * cd /home/ubuntu/realty-telegram-bot && /usr/bin/python3 check_korea.py >> /home/ubuntu/korea.log 2>&1
```

- 로그는 `~/korea.log`에 쌓입니다: `tail -f ~/korea.log`
- **알림 링크가 항상 네이버 검색 링크로 옵니다**(2026-07-28부터 기본값): 정보소통광장은
  상세페이지(`/sanction/{번호}`)뿐 아니라 자체 목록 검색 링크(`/sanction/list?
  searchKeyword=...`)로 바꿔도 외부(텔레그램)에서 오는 클릭은 경로에 상관없이
  `ERR_EMPTY_RESPONSE`로 막는 것을 실사용으로 확인했습니다. opengov.seoul.go.kr
  도메인 자체로는 어떤 링크를 만들어도 신뢰할 수 없다고 보고, 확실히 열리는
  네이버 검색(`"제목" site:opengov.seoul.go.kr`)으로 안내를 바꿨습니다 —
  알림의 링크를 누르면 네이버 검색 결과가 뜨고, 거기서 정보소통광장 결과를
  누르면 됩니다(opengov 자체 접속이 막힌 상태라면 네이버 스니펫으로도 내용
  확인이 가능한 경우가 많습니다).
- `OPENGOV_LINK_MODE` 환경변수로 방식을 바꿀 수 있습니다 — `search`(기본, 항상
  네이버 검색) / `direct`(항상 opengov 문서 주소 — 안 열릴 가능성 높음) /
  `auto`(사전확인 후 결정 — 신뢰도 낮아 권장 안 함).
- 지금 어느 쪽으로 나가는지 확인: `DEBUG=1 python3 check_korea.py` 출력의
  `알림에 넣을 링크` 줄을 보면 됩니다.
- **코드 업데이트는 자동입니다**: `check_korea.py`가 실행될 때마다 스스로 `git pull`을
  하고, 새 코드가 있으면 그 자리에서 새 코드로 재실행합니다. VM에 접속해서
  수동으로 `git pull` 할 필요가 없습니다. (네트워크 오류 등으로 pull이 실패해도
  감시는 기존 코드로 계속 동작합니다.)

---

## 참고: 무료 티어 한도 (넉넉함)
- 오라클 Always Free: VM 무기한 무료, 저장 200GB, 월 트래픽 10TB.
- 이 스크립트는 30분마다 페이지 몇 개만 읽어 트래픽/CPU 거의 안 씀 → 한도 걱정 없음.

## 참고: 나중에 확장
open.go.kr은 이미 check_korea.py에 포함됐습니다(2026-07-17). 추가로 필요하면
만성 타임아웃 구청(동대문·광진·양천)도 한국 IP로 옮길 수 있습니다.

## 코드 업데이트 방법
**자동입니다.** `check_korea.py`가 실행될 때마다(30분 주기) 스스로 `git pull`을
하고, 새 코드가 받아지면 즉시 새 코드로 재실행합니다. 수동으로 할 일이 없습니다.
새 감시 대상이 추가된 경우 첫 회차는 알림 없이 "감시 시작" 안내만 오고
기준선을 저장합니다.

> 로컬에서 파일을 직접 수정해 두면 `git pull --ff-only`가 실패하면서 자동
> 업데이트가 건너뛰어집니다(로그에 표시됨). 그 경우 한 번만
> `git checkout . && git pull` 해주면 이후 다시 자동으로 돌아갑니다.

---

## 방법 2: 집 PC(윈도우)에서 상시 실행 — 오라클 대신 이걸 쓸 때

오라클 무료 리전이 한국은 자리가 없는 경우가 흔합니다. 집 PC(윈도우)가 항상 켜져
있다면 이게 더 간단하고 확실합니다(가입 절차 없음, 확실한 한국 IP).

### 1) Python 설치 확인
PowerShell 열고:
```powershell
python --version
```
버전이 안 뜨면 https://www.python.org/downloads/ 에서 설치.
**설치 화면에서 "Add python.exe to PATH" 체크 필수.**

### 2) Git 설치 (코드 받기 + 나중에 업데이트용)
https://git-scm.com/download/win 다운로드 → 설치(전부 기본값으로 Next).

### 3) 코드 받기
PowerShell에서:
```powershell
cd $HOME\Documents
git clone https://github.com/para333311/realty-telegram-bot.git
cd realty-telegram-bot
pip install requests beautifulsoup4 python-dotenv
```

### 4) 텔레그램 시크릿 파일 생성
`realty-telegram-bot` 폴더에 `.env` 파일을 메모장으로 새로 만들고 아래 내용 저장
(GitHub Secrets와 같은 값 — 잊었으면 BotFather에서 토큰, @userinfobot에서 채팅ID 재확인):
```
BOARD_BOT_TOKEN=여기에_재재보드봇_토큰
TELEGRAM_CHAT_ID=여기에_채팅ID
```

### 5) 디버그로 먼저 확인 (중요)
```powershell
$env:DEBUG="1"; python check_korea.py
```
`HTTP 200`과 문서 목록이 출력되면 성공. 출력을 클로드에게 붙여주면 파싱 튜닝.
`HTTP 403`이나 0건이면 opengov가 가정용 IP도 막는 것 — 그 결과도 알려주세요.

### 6) 정상 확인되면 실제 1회 실행
```powershell
python check_korea.py
```
(첫 실행은 "감시 시작" 안내만 오고 기준선 저장)

### 7) 작업 스케줄러로 30분마다 자동 실행
1. 시작 메뉴 → **"작업 스케줄러"(Task Scheduler)** 검색해서 열기
2. 오른쪽 **"작업 만들기"** 클릭
3. **일반** 탭: 이름 `korea-monitor` 입력, **"가장 높은 권한으로 실행"** 체크
4. **트리거** 탭 → 새로 만들기 → 매일, 반복 간격 **30분**, 기간 **무기한**
5. **동작** 탭 → 새로 만들기 →
   - 프로그램/스크립트: `python` (또는 `python --version`으로 나온 전체경로, 예: `C:\Users\사용자\AppData\Local\Programs\Python\Python312\python.exe`)
   - 인수 추가: `check_korea.py`
   - 시작 위치: `C:\Users\사용자\Documents\realty-telegram-bot` (본인 경로로)
6. **조건** 탭 → **"AC 전원에 연결된 경우에만 시작"** 체크 해제(배터리로도 돌게), 필요시 조정
7. **트리거** 탭에서 **새로 만들기를 한 번 더** → "작업 시작:"을 **시작할 때**로 선택
   → 확인. (노트북을 껐다 켜면 부팅 직후 바로 한 번 돕니다.)
8. **설정** 탭 → **"예약된 시작 시간을 놓친 경우 가능한 한 빨리 작업 시작"** 체크
   (꺼져 있는 동안 놓친 실행을 켜자마자 따라잡습니다.)
9. 확인 → 저장

> 7·8번을 안 하면 노트북을 껐다 켰을 때 다음 실행까지 최대 하루가 비는 경우가
> 있습니다. 둘 다 켜두면 **전원만 켜면 자동으로 다시 감시**합니다.

### 8) 노트북이 잠들지 않게 (중요!)
- **설정 → 시스템 → 전원 및 절전** → "화면 끄기"는 괜찮지만 **"절전 모드"는 "안 함"으로 설정**
  (절전 들어가면 예약 작업이 안 돕니다. 화면만 꺼지는 건 무관.)
- 노트북 덮개(뚜껑)를 닫아도 계속 돌게 하려면:
  **제어판 → 전원 옵션 → 덮개를 닫을 때 하는 동작 → "아무 작업 안 함"**

- 로그 확인: 작업 스케줄러에서 해당 작업 우클릭 → "실행" 으로 수동 테스트 가능
- 코드 업데이트: **자동** — 실행 때마다 스스로 `git pull` 후 새 코드로 재실행
