import os
import re
import subprocess
import urllib
import logging
import requests
import youtube_dl
from telegram import *
from telegram.ext import *
from youtube_dl.utils import DownloadError

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

updater = Updater(token=os.environ['TOKEN'])
dispatcher = updater.dispatcher

# from a list of youtube-dl thumbnails, select the largest one that still satisfies telegram's requirements (less than 320px width and height)
def select_thumbnail(thumbnails):
    return max(filter(lambda x: x['width'] < 320 and x['height'] < 320, thumbnails), key=lambda x: x['width']*x['height'])['url']

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
    context.bot.send_message(chat_id=update.effective_chat.id, text='You pressed option ' + query)

# TODO correct download location with -o flag

def message(update, context):
    chat_id = update.effective_chat.id
    query = re.split(r'\s+', update.message.text)
    #print(query)

    all_results = []
    playlist_title = None
    playlist_thumbnail = None

    ydl = youtube_dl.YoutubeDL({
        'outtmpl': './downloads/%(title)s.%(ext)s',
        'no_color': True,
        'format': 'worst',
        'keepvideo': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3'
        }]
    })
    for url in query:
        try:
            result = ydl.extract_info(
                url,
                download=False
            )

            if 'entries' in result:
                # Playlist
                all_results += result['entries']

                playlist_title = result.get('title', None)
                playlist_thumbnail = result.get('thumbnail', None)
            else:
                # Single video
                all_results += [result]
        except DownloadError as e:
            send(chat_id, context, text=str(e))
            return

    if len(query) >= 2:
        playlist_title = None
        playlist_thumbnail = None

    if playlist_title is not None:
        message = 'The playlist \'' + playlist_title + '\' will be downloaded:\n\n' + '\n'.join([x['title'] for x in all_results])
        send(chat_id, context, text=message, photo=playlist_thumbnail)
    else:
        message = 'The following videos will be downloaded:\n\n' + '\n'.join([x['title'] for x in all_results])
        send(chat_id, context, text=message, photo=playlist_thumbnail)

    for result in all_results:
        try:
            status = ydl.download([result['webpage_url']])
            if status != 0:
                raise DownloadError('Unknown error while downloading ' + result['webpage_url'])

            thumbnail_path = './downloads/' + result['title'].replace('/', '_') + '.jpg'
            urllib.request.urlretrieve(select_thumbnail(result['thumbnails']), thumbnail_path)
            subprocess.call(['mogrify', '-format', 'jpg', thumbnail_path])
        except DownloadError as e:
            send(chat_id, context, text=str(e))

    media_videos = [InputMediaVideo(open('./downloads/' + x['title'].replace('/', '_') + '.' + result['ext'], 'rb'), thumb=open('./downloads/' + x['title'].replace('/', '_') + '.jpg', 'rb'), caption=x['title']) for x in all_results]
    context.bot.send_media_group(chat_id=chat_id, media=media_videos)

    media_audios = [InputMediaAudio(open('./downloads/' + x['title'].replace('/', '_') + '.mp3', 'rb'), thumb=open('./downloads/' + x['title'].replace('/', '_') + '.jpg', 'rb'), caption=x['title']) for x in all_results]
    context.bot.send_media_group(chat_id=chat_id, media=media_audios)

dispatcher.add_handler(CallbackQueryHandler(callback_query))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, message))

updater.start_polling()
