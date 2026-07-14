# naver-blog-telegram-bot

네이버블로그의 새 글을 구독하고, 텔레그램으로 알림을 받는 봇입니다.

두 가지 방식으로 쓸 수 있습니다:

1. **GitHub Actions 방식 (추천)** — 서버나 내 컴퓨터 없이, GitHub이 30분마다 자동으로 새 글을 확인해서 텔레그램으로 보내줍니다. 완전 무료이며 카드 등록도 필요 없습니다. 구독할 블로그는 `blogs.txt` 파일에 적어서 관리합니다.
2. **봇 상시 실행 방식** — 내 컴퓨터나 서버에서 `python bot.py`를 계속 켜두는 방식. 텔레그램 명령어(`/subscribe`)로 구독을 관리할 수 있습니다.

## 방법 1: GitHub Actions (서버 없이 무료)

1. 이 저장소를 자신의 GitHub 계정으로 fork 하거나 사용합니다.
2. [BotFather](https://t.me/BotFather)에서 봇을 만들고 토큰을 발급받습니다.
3. 텔레그램에서 [@userinfobot](https://t.me/userinfobot)에게 아무 메시지나 보내 내 채팅 ID(숫자)를 확인합니다.
4. GitHub 저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 두 개를 등록합니다:
   - `TELEGRAM_BOT_TOKEN`: BotFather에서 받은 토큰
   - `TELEGRAM_CHAT_ID`: 내 채팅 ID
5. 저장소의 `blogs.txt` 파일을 열어 구독할 블로그 주소(또는 아이디)를 한 줄에 하나씩 적고 커밋합니다.
6. **Actions 탭**에서 워크플로를 활성화하고, "네이버 블로그 새 글 확인" 워크플로의 **Run workflow** 버튼으로 첫 실행을 해봅니다. 텔레그램으로 `✅ 감시를 시작했습니다` 메시지가 오면 성공입니다.

이후 30분 간격으로 자동 확인되며(GitHub 사정에 따라 다소 지연될 수 있음), 새 글이 올라오면 텔레그램으로 알림이 옵니다. 확인한 글 기록은 `seen.json`에 자동 커밋됩니다.

> 주의: 만든 봇과 반드시 한 번은 대화를 시작(`/start`)해두어야 봇이 메시지를 보낼 수 있습니다.

### 구청 게시판(고시공고 등) 새 공고 알림

블로그와 같은 방식으로, 관공서 게시판의 새 공고도 감시할 수 있습니다. 게시판 알림은 블로그 알림과 **별도의 텔레그램 봇**으로 발송됩니다 — BotFather에서 봇을 하나 더 만들고, 그 토큰을 `BOARD_BOT_TOKEN` 시크릿으로 등록하세요. (`TELEGRAM_CHAT_ID`는 블로그 알림과 공용이며, 새 봇에게도 `/start`를 한 번 보내두어야 합니다.)

감시할 게시판은 `boards.txt`에 한 줄에 하나씩 적습니다:

```
이름 | 게시판주소
```

- **이름**: 알림 메시지에 표시될 이름 (예: `마포구 재개발소식`)
- **게시판주소**: 게시판 목록 페이지의 전체 주소
- 특정 단어가 든 공고만 받으려면 맨 뒤에 `| 키워드1,키워드2`를 붙입니다 (생략하면 전체 알림).

확인한 공고는 `seen_boards.json`에 자동 커밋됩니다.

## 방법 2: 봇 상시 실행 (텔레그램 명령어로 구독 관리)

사용자별로 원하는 블로그를 텔레그램 명령어로 자유롭게 구독/해제할 수 있습니다. 단, 실행한 컴퓨터/서버가 켜져 있는 동안만 동작하며, 네트워크에서 `api.telegram.org` 접속이 가능해야 합니다.

## 동작 방식

- 구독한 블로그마다 네이버 공식 RSS(`https://rss.blog.naver.com/{blogId}.xml`)를 주기적으로 확인합니다.
- 이미 확인한 글의 링크를 기억해두고, 목록에 처음 보는 글이 나타나면 구독한 사용자에게 텔레그램 메시지로 알려줍니다. 글이 삭제되거나 여러 글이 한꺼번에 올라와도 중복 알림 없이 동작합니다.
- 구독 정보는 로컬 SQLite 파일(`subscriptions.db`)에 저장됩니다.

## 설치

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 설정

1. [BotFather](https://t.me/BotFather)에서 봇을 만들고 토큰을 발급받습니다.
2. `.env.example`을 복사해 `.env` 파일을 만들고 토큰을 채워넣습니다.

   ```bash
   cp .env.example .env
   # .env 파일을 열어 TELEGRAM_BOT_TOKEN 값을 채워넣기
   ```

   - `CHECK_INTERVAL_SECONDS`: 새 글 확인 주기(초). 기본값 600(10분).

## 실행

```bash
python bot.py
```

## 사용법 (텔레그램에서)

| 명령어 | 설명 |
| --- | --- |
| `/start` | 봇 소개 및 사용법 안내 |
| `/subscribe <블로그아이디 또는 주소>` | 새 글 알림 구독 시작. 예: `/subscribe myblogid` 또는 `/subscribe https://blog.naver.com/myblogid` |
| `/unsubscribe <블로그아이디>` | 구독 해제 |
| `/list` | 현재 구독중인 블로그 목록 확인 |

구독 직후에는 알림 없이 최신 글을 기준선으로 저장하고, 그 다음 확인 주기부터 새 글이 감지되면 알림을 보냅니다.

## 배포

폴링(long polling) 방식이라 별도의 공개 URL/웹훅 설정 없이 어디서든(로컬, VPS, Render Background Worker 등) `python bot.py`를 실행해두면 동작합니다. 장시간 구동을 위해서는 `systemd`, `pm2`, 또는 Render/Fly.io 등의 백그라운드 워커 서비스 사용을 권장합니다.
