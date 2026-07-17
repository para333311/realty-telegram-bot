# 한국 IP 서버 세팅 가이드 (해외 차단 사이트 실시간 감시)

GitHub Actions(해외 IP)에서 차단·불안정한 한국 정부사이트를 **한국 IP에서 직접**
감시하기 위한 가이드입니다. 현재 대상: **서울정보소통광장(opengov) 결재문서 실시간**.

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
- 코드 업데이트가 있으면: `cd ~/realty-telegram-bot && git pull`

---

## 참고: 무료 티어 한도 (넉넉함)
- 오라클 Always Free: VM 무기한 무료, 저장 200GB, 월 트래픽 10TB.
- 이 스크립트는 30분마다 페이지 몇 개만 읽어 트래픽/CPU 거의 안 씀 → 한도 걱정 없음.

## 참고: 나중에 확장
opengov가 잘 되면, 같은 서버에서 만성 타임아웃 구청(동대문·광진·양천)이나
open.go.kr도 한국 IP로 돌려 안정화할 수 있습니다. opengov부터 검증 후 확장합니다.
