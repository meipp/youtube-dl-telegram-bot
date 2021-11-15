import os
import re
import logging
import requests
from telegram import *
from telegram.ext import *

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

updater = Updater(token=os.environ['TOKEN'])
dispatcher = updater.dispatcher

def send(chat_id, context, text=None, photo=None, disable_notification=True):
    if text is not None and photo is None:
        context.bot.send_message(chat_id=chat_id, text=text, disable_notification=disable_notification)

    if photo is not None and not photo.lower().endswith('.webp'):
        # photo exists and is not a sticker
        context.bot.send_photo(chat_id=chat_id, photo=photo, caption=text, disable_notification=disable_notification)
    if photo is not None and photo.lower().endswith('.webp'):
        # .webp images must be sent with send_stickers
        # additionally, stickers cannot have a caption, so text must be sent separately
        context.bot.send_sticker(chat_id=chat_id, sticker=photo, disable_notification=disable_notification)
        if text is not None:
            context.bot.send_message(chat_id=chat_id, text=text, disable_notification=disable_notification)

def keyboard(buttons):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=str(i))] for i, label in enumerate(buttons)]
    )

def callback_query(update, context):
    query = update.callback_query.data
    update.callback_query.answer()
    downloads = sorted(os.listdir('./downloads'))
    selection = downloads[int(query)]
    context.bot.send_message(chat_id=update.effective_chat.id, text='Uploading \'' + selection + '\'...')

    files = {'document': open('./downloads/' + selection, 'rb')}
    resp = requests.post('https://api.telegram.org/bot' + os.environ['TOKEN'] + '/sendDocument?chat_id=' + str(update.effective_chat.id), files=files)
    print(resp.status_code)
    print(resp.content)

# TODO correct download location with -o flag

def mp3(update, context):
    # TODO split(...)[1]
    query = update.message.text.split(' ')[1]

    context.bot.send_message(chat_id=update.effective_chat.id, text='Downloading...')
    os.system('youtube-dl --extract-audio --audio-format mp3 --output "./downloads/%(title)s.%(ext)s" ' + query)

def mp4(update, context):
    # TODO split(...)[1]
    query = update.message.text.split(' ')[1]

    context.bot.send_message(chat_id=update.effective_chat.id, text='Downloading...')
    os.system('youtube-dl --format mp4 --output "./downloads/%(title)s.%(ext)s" ' + query)

def select_file(update, context):
    downloads = sorted(os.listdir('./downloads'))
    context.bot.send_message(chat_id=update.effective_chat.id, text='Select a file to download', reply_markup=keyboard(downloads))


dispatcher.add_handler(CommandHandler('mp3', mp3))
dispatcher.add_handler(CommandHandler('mp4', mp4))
dispatcher.add_handler(CommandHandler('select_file', select_file))
dispatcher.add_handler(CallbackQueryHandler(callback_query))

updater.start_polling()