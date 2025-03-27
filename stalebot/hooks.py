"""Event Hooks"""

import time
from argparse import Namespace
from threading import Thread

from deltabot_cli import BotCli
from deltachat2 import (
    Bot,
    ChatType,
    CoreEvent,
    EventType,
    Message,
    MsgData,
    NewMsgEvent,
    events,
)
from rich.logging import RichHandler

cli = BotCli("stalebot")
cli.add_generic_option(
    "--no-time",
    help="do not display date timestamp in log messages",
    action="store_false",
)


@cli.on_init
def on_init(bot: Bot, args: Namespace) -> None:
    bot.logger.handlers = [
        RichHandler(show_path=False, omit_repeated_times=False, show_time=args.no_time)
    ]
    for accid in bot.rpc.get_all_account_ids():
        if not bot.rpc.get_config(accid, "displayname"):
            bot.rpc.set_config(accid, "displayname", "StaleBot")
            status = "I'm a bot, send /help to me for more info"
            bot.rpc.set_config(accid, "selfstatus", status)
            bot.rpc.set_config(accid, "delete_device_after", "3600")


@cli.on_start
def on_start(bot: Bot, _args: Namespace) -> None:
    Thread(target=check_members, args=(bot,), daemon=True).start()


@cli.on(events.RawEvent)
def log_event(bot: Bot, _accid: int, event: CoreEvent) -> None:
    if event.kind == EventType.INFO:
        bot.logger.debug(event.msg)
    elif event.kind == EventType.WARNING:
        bot.logger.warning(event.msg)
    elif event.kind == EventType.ERROR:
        bot.logger.error(event.msg)


@cli.on(events.NewMessage(command="/invite"))
def _invite(bot: Bot, accid: int, event: NewMsgEvent) -> None:
    msg = event.msg
    if warn_dm(bot, accid, msg):
        return

    bot.rpc.markseen_msgs(accid, [msg.id])
    text = bot.rpc.get_chat_securejoin_qr_code(accid, msg.chat_id)
    bot.rpc.send_msg(accid, msg.chat_id, MsgData(text=text))


@cli.on(events.NewMessage(is_info=False))
def on_message(bot: Bot, accid: int, event: NewMsgEvent) -> None:
    if bot.has_command(event.command):
        return
    warn_dm(bot, accid, event.msg)


@cli.after(events.NewMessage)
def delete_msgs(bot, accid, event):
    bot.rpc.delete_messages(accid, [event.msg.id])


def warn_dm(bot: Bot, accid: int, msg: Message) -> bool:
    chat = bot.rpc.get_basic_chat_info(accid, msg.chat_id)
    if chat.chat_type == ChatType.SINGLE:
        bot.rpc.markseen_msgs(accid, [msg.id])
        send_help(bot, accid, msg.chat_id)
        return True
    return False


def send_help(bot: Bot, accid: int, chatid: int) -> None:
    text = (
        "👋 hi, I'm a bot,"
        " you can add me to groups and I will remove stale inactive users.\n\n"
        "Commands:\n\n"
        "/invite  get the group's invitation link.\n\n"
    )
    bot.rpc.send_msg(accid, chatid, MsgData(text=text))


def check_members(bot: Bot) -> None:
    while True:
        bot.logger.info("[WORKER] Starting to check groups")
        for accid in bot.rpc.get_all_account_ids():
            check_account(bot, accid)
        delay = 60 * 60
        bot.logger.info(f"[WORKER] Sleeping for {delay} seconds")
        time.sleep(delay)


def check_account(bot: Bot, accid: int) -> None:
    chats = bot.rpc.get_chatlist_entries(accid, None, None, None)
    for chatid in chats:
        chat = bot.rpc.get_full_chat_by_id(accid, chatid)
        if chat.chat_type == ChatType.SINGLE or not chat.can_send:
            continue
        month = 60 * 60 * 24 * 30
        for contact in chat.contacts:
            if not contact.last_seen or contact.is_bot:
                continue
            if (time.time() - contact.last_seen) > month:
                bot.rpc.remove_contact_from_chat(accid, chatid, contact.id)
