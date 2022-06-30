from telethon.sync import TelegramClient, events
from telethon import functions
from telethon.tl.types import ChannelParticipantsSearch
import datetime

import config
import db_funcs

# settings and constants
month_properties = {
    1: (31, 'января'),
    2: (29, 'февраля'),
    3: (31, 'марта'),
    4: (30, 'апреля'),
    5: (31, 'мая'),
    6: (30, 'июня'),
    7: (31, 'июля'),
    8: (31, 'августа'),
    9: (30, 'сентября'),
    10: (31, 'октября'),
    11: (30, 'ноября'),
    12: (31, 'декабря')
}

db_worker = db_funcs.DatabaseWorker(config.DATABASE)
bot = TelegramClient('bot', config.API_ID, config.API_HASH).start(bot_token=config.TOKEN)
bot.parse_mode = 'html'

moscow_timezone = datetime.timezone(datetime.timedelta(hours=3))
previous_check = datetime.datetime.now(tz=moscow_timezone).minute - 1


# useful utils
async def create_mention(user_id):
    user = (await bot(functions.users.GetFullUserRequest(user_id))).user
    return f'<a href="tg://user?id={user_id}">{user.first_name} {user.last_name}</a>'


async def congratulation(mentions, day, month, chat_id):
    word_forms = ['празднуют пользователи', 'их']
    if len(mentions) == 0:
        return
    elif len(mentions) == 1:
        word_forms[0] = 'празднует пользователь'
        word_forms[1] = 'его'

    text = f'В этот замечательный день — {day} {month_properties[month][1]} ' \
           f'День рождения {word_forms[0]} {", ".join(mentions)}!\n\nДавайте вместе {word_forms[1]} поздравим 🎉🎉🎉'

    await bot.send_message(chat_id, text)


def is_date_correct(day, month):
    return (month in month_properties) and (1 <= day <= month_properties[month][0])


def is_time_correct(hours, minutes):
    return (0 <= hours < 24) and (0 <= minutes < 60)


def is_notice_pending():
    global previous_check
    if datetime.datetime.now(tz=moscow_timezone).minute == previous_check:
        return False

    previous_check = datetime.datetime.now(tz=moscow_timezone).minute
    return True


async def is_user_admin(user_id, chat_id):
    try:
        user = (await bot.get_permissions(chat_id, user_id))
        is_user_chat_creator = user.is_creator
        is_user_chat_admin = user.is_admin
        return is_user_chat_admin or is_user_chat_creator
    except ValueError:
        return False


# bot event behavior
@bot.on(events.NewMessage(pattern='^(/start|/help)(|@chatBirthday_bot)$'))
async def greeting(event):
    await event.reply(config.GREETING_MESSAGE)


@bot.on(events.NewMessage(pattern='^/remove_bd(|@chatBirthday_bot)$'))
async def remove_birth_date(event):
    user_id = (await event.get_sender()).id
    db_worker.remove_birth_date(user_id)
    await event.reply('Ваша дата рождения успешно удалена ❌')


@bot.on(events.NewMessage(pattern='^/edit_bd(|@chatBirthday_bot) [0-9][0-9].[0-9][0-9]$'))
async def edit_birth_date(event):
    birth_day, birth_month = map(int, (event.message.text.split())[-1].split('.'))
    sender_id = (await event.get_sender()).id

    if not is_date_correct(birth_day, birth_month):
        await event.reply('К сожалению, введённая дата некорректна 😔')
        return

    db_worker.update_birth_date(sender_id, birth_day, birth_month)
    await event.reply(f'Отлично!\nДата Вашего Дня'
                      f' рождения успешно установлена на {birth_day} {month_properties[birth_month][1]} 🎉')


@bot.on(events.NewMessage(pattern='^/notify_at(|@chatBirthday_bot) [0-9][0-9]:[0-9][0-9]$'))
async def update_notification_time(event):
    sender_id = (await event.get_sender()).id
    chat_id = event.chat.id
    hours, minutes = map(int, (event.message.text.split())[-1].split(':'))

    if not (await is_user_admin(sender_id, chat_id)):
        return

    if not is_time_correct(hours, minutes):
        await event.reply('К сожалению, введённое время суток некорректно 😔')
        return

    db_worker.update_notification_time(chat_id, hours, minutes)
    await event.reply(
        f'Отлично!\nВремя уведомления о наступивших Днях рождения в этом чате'
        f' установлено на {("0" + str(hours))[-2:]}:{("0" + str(minutes))[-2:]} UTC+3 ⏰')


@bot.on(events.NewMessage(pattern='^/dont_notify(|@chatBirthday_bot)$'))
async def disable_notifications(event):
    sender_id = (await event.get_sender()).id
    chat_id = event.chat.id

    if not (await is_user_admin(sender_id, chat_id)):
        return

    db_worker.disable_notification(chat_id)
    await event.reply(f'Уведомления о наступивших Днях рождения в этом чате отключены ❌')


'''
@bot.on(events.NewMessage(pattern='/check'))
async def get_time(event):
    hour, minute = int(datetime.datetime.now(tz=moscow_timezone).hour), int(
        datetime.datetime.now(tz=moscow_timezone).minute)
    day, month = int(datetime.datetime.now(tz=moscow_timezone).day), int(
        datetime.datetime.now(tz=moscow_timezone).month)
    await event.reply(f'{day}.{month} {hour}:{minute}')
'''


# bot notification sending
async def send_notification():
    if not is_notice_pending():
        return

    hour, minute = int(datetime.datetime.now(tz=moscow_timezone).hour), int(
        datetime.datetime.now(tz=moscow_timezone).minute)
    day, month = int(datetime.datetime.now(tz=moscow_timezone).day), int(
        datetime.datetime.now(tz=moscow_timezone).month)

    chats_to_notify = db_worker.get_chats_to_notify(hour, minute)
    users_to_notify = db_worker.get_users_to_notify(day, month)

    for chat_id in chats_to_notify:
        chat_members = await bot(functions.channels.GetParticipantsRequest(
            chat_id, ChannelParticipantsSearch(''), offset=0, limit=10000,
            hash=0
        ))

        users_to_notify_in_chat = list()

        for member in chat_members.users:
            if member.id in users_to_notify:
                users_to_notify_in_chat.append(await create_mention(member.id))

        await congratulation(users_to_notify_in_chat, day, month, chat_id)


# run bot loop
while True:
    bot.loop.run_until_complete(send_notification())