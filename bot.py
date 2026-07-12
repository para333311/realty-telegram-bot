import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import naver_blog
import storage

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "600"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "네이버블로그 새 글 알림 봇입니다.\n\n"
        "/subscribe <블로그아이디 또는 주소> - 구독 추가\n"
        "/unsubscribe <블로그아이디> - 구독 해제\n"
        "/list - 구독중인 블로그 목록"
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "사용법: /subscribe 블로그아이디 또는 https://blog.naver.com/아이디"
        )
        return

    blog_id = naver_blog.extract_blog_id(context.args[0])
    if not blog_id:
        await update.message.reply_text("블로그 주소를 인식할 수 없습니다.")
        return

    try:
        blog_name, posts = naver_blog.fetch_posts(blog_id)
    except Exception:
        logger.exception("failed to fetch blog %s", blog_id)
        await update.message.reply_text("블로그 정보를 가져오지 못했습니다. 주소를 확인해주세요.")
        return

    chat_id = update.effective_chat.id
    storage.add_subscription(chat_id, blog_id, blog_name)
    if posts:
        storage.update_last_link(chat_id, blog_id, posts[0]["link"])

    await update.message.reply_text(
        f"'{blog_name}' 블로그 구독을 시작했습니다. 새 글이 올라오면 알려드릴게요."
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("사용법: /unsubscribe 블로그아이디")
        return

    blog_id = naver_blog.extract_blog_id(context.args[0]) or context.args[0]
    removed = storage.remove_subscription(update.effective_chat.id, blog_id)
    if removed:
        await update.message.reply_text("구독을 해제했습니다.")
    else:
        await update.message.reply_text("구독중이지 않은 블로그입니다.")


async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = storage.list_subscriptions(update.effective_chat.id)
    if not subs:
        await update.message.reply_text("구독중인 블로그가 없습니다.")
        return
    body = "\n".join(f"- {s['blog_name']} ({s['blog_id']})" for s in subs)
    await update.message.reply_text(f"구독중인 블로그:\n{body}")


async def check_all_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    for sub in storage.all_subscriptions():
        try:
            blog_name, posts = naver_blog.fetch_posts(sub["blog_id"])
        except Exception as e:
            logger.warning("failed to fetch %s: %s", sub["blog_id"], e)
            continue

        if not posts:
            continue

        last_link = sub["last_link"]
        if last_link is None:
            storage.update_last_link(sub["chat_id"], sub["blog_id"], posts[0]["link"])
            continue

        new_posts = []
        for post in posts:
            if post["link"] == last_link:
                break
            new_posts.append(post)

        if new_posts:
            for post in reversed(new_posts):  # 오래된 글부터 순서대로 발송
                text = f"🔔 [{blog_name}] 새 글 등록\n{post['title']}\n{post['link']}"
                await context.bot.send_message(chat_id=sub["chat_id"], text=text)
            storage.update_last_link(sub["chat_id"], sub["blog_id"], posts[0]["link"])


def main():
    storage.init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("list", list_subscriptions))

    application.job_queue.run_repeating(
        check_all_subscriptions, interval=CHECK_INTERVAL_SECONDS, first=CHECK_INTERVAL_SECONDS
    )

    application.run_polling()


if __name__ == "__main__":
    main()
