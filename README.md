# naver-blog-telegram-bot

네이버블로그의 새 글을 구독하고, 텔레그램으로 알림을 받는 봇입니다. 사용자별로 원하는 블로그를 자유롭게 구독/해제할 수 있습니다.

## 동작 방식

- 구독한 블로그마다 네이버 공식 RSS(`https://rss.blog.naver.com/{blogId}.xml`)를 주기적으로 확인합니다.
- 마지막으로 확인한 글 이후에 새로 올라온 글이 있으면 구독한 사용자에게 텔레그램 메시지로 알려줍니다.
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
