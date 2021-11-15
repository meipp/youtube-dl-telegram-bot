import os
import re
import time
import subprocess
import urllib
import logging
import requests
from telegram.error import BadRequest
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

def download(update, context, task, format, merge='separately'):
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id, text=format+' '+merge)

    playlist_title = task['playlist_title']
    playlist_thumbnail = task['playlist_thumbnail']
    all_results = task['all_results']

    progress_logger = TelegramProgressLogger(chat_id, context, headlines=['<b>Progress</b>'], bold_headlines=[0])
    ydl = youtube_dl.YoutubeDL({
        'outtmpl': './downloads/%(title)s.%(ext)s',
        'no_color': True,
        'format': 'worst',
        'keepvideo': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3'
        }],
        'logger': progress_logger
    })

    if playlist_title is not None:
        message = 'The playlist \'' + playlist_title + '\' will be downloaded:'
        progress_logger.set_headlines(message.split('\n'), [0])
        progress_logger.set_subtasks([x['title'] for x in all_results])
    else:
        message = 'The following videos will be downloaded:'
        progress_logger.set_headlines(message.split('\n'), [0])
        progress_logger.set_subtasks([x['title'] for x in all_results])

    for i, result in enumerate(all_results):
        try:
            progress_logger.set_current_subtask(i)
            status = ydl.download([result['webpage_url']])
            if status != 0:
                raise DownloadError('Unknown error while downloading ' + result['webpage_url'])

            thumbnail_path = './downloads/' + result['title'].replace('/', '_') + '.jpg'
            urllib.request.urlretrieve(select_thumbnail(result['thumbnails']), thumbnail_path)
            subprocess.call(['mogrify', '-format', 'jpg', thumbnail_path])
        except DownloadError as e:
            send(chat_id, context, text=str(e))
    progress_logger.set_current_subtask(-1)

    if format == 'video':
        media_videos = [InputMediaVideo(open('./downloads/' + x['title'].replace('/', '_') + '.' + result['ext'], 'rb'), thumb=open('./downloads/' + x['title'].replace('/', '_') + '.jpg', 'rb'), caption=x['title']) for x in all_results]
        context.bot.send_media_group(chat_id=chat_id, media=media_videos)
    if format == 'audio':
        media_audios = [InputMediaAudio(open('./downloads/' + x['title'].replace('/', '_') + '.mp3', 'rb'), thumb=open('./downloads/' + x['title'].replace('/', '_') + '.jpg', 'rb'), caption=x['title']) for x in all_results]
        context.bot.send_media_group(chat_id=chat_id, media=media_audios)

def callback_query(update, context):
    query = update.callback_query.data
    update.callback_query.answer()

    args = query.split(' ')
    if len(args) == 2 and args[0] in ['video', 'audio']:
        task = context.chat_data['tasks'][args[1]]

        if len(task['all_results']) >= 2:
            # keyboard
            context.bot.send_message(chat_id=update.effective_chat.id, text='Merge files into one or download separately?', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Merge', callback_data=args[0] + ' merge ' + args[1])], [InlineKeyboardButton('Separately', callback_data=args[0] + ' separately ' + args[1])]]))
        else:
            download(update, context, task, format=args[0])

    if len(args) == 3 and args[0] in ['video', 'audio'] and args[1] in ['merge', 'separately']:
        task = context.chat_data['tasks'][args[2]]
        download(update, context, task, format=args[0], merge=args[1])

# TODO correct download location with -o flag

class TelegramProgressLogger:
    def __init__(self, chat_id, context, headlines, bold_headlines=[]):
        self.chat_id = chat_id
        self.context = context
        self.progress_message = context.bot.send_message(chat_id=chat_id, text='Progress placeholder')

        self.headlines = headlines
        self.bold_headlines = bold_headlines
        self.lines = []
        self.set_subtasks([])
        self.last_message_timestamp = 0

    def debug(self, msg):
        print(msg)
        self.edit_progress_message(msg, drop_message=True)

    def warning(self, msg):
        print(msg)
        self.edit_progress_message(msg, drop_message=False)

    def error(self, msg):
        print(msg)
        self.edit_progress_message(msg, drop_message=False)

    def edit_progress_message(self, msg, drop_message=False):
        # Catch download progress
        m = re.search(r'\[download\]\s+(\d+(\.\d+)?%)', msg)
        if m:
            progress = m.group(1)
            self.set_subtask_progress(progress)
            return

        # if msg starts with the magic sequence, the logger wants to overwrite the last line rather than append a new line
        magic_sequence = '\r\x1b[K'
        if msg.startswith(magic_sequence):
            # overwrite last line with message (and delete the magic sequence from beginning of the message)
            self.lines = self.lines[:-1] + [msg[len(magic_sequence):]]
        else:
            self.lines += [msg]
        self.update_message(drop_message=drop_message)

    def update_message(self, drop_message=False):
        lines = []
        for i, headline in enumerate(self.headlines):
            if i in self.bold_headlines:
                lines.append('<b>' + headline + '</b>')
            else:
                lines.append(headline)
        lines.append('')

        lines += self.lines
        lines.append('')

        # Subtask progress
        for i, subtask in enumerate(self.subtasks):
            line = self.subtask_progresses[i] + ' ' + subtask
            if i == self.current_subtask_index:
                lines.append('<b>' + line + '</b>')
            else:
                lines.append(line)

        msg = '\n'.join(lines)
        m = self.progress_message
        if m['text'] != msg:
            # New message
            # If the old message and the edited message are identical, telegram rejects the edit

            if drop_message and time.time() - self.last_message_timestamp < 2:
                # If a message has been sent in the last two seconds, drop this message
                # This measure is necessary so that the bot does exceed telegram's message limit
                return

            try:
                self.progress_message = self.context.bot.edit_message_text(chat_id=self.chat_id, message_id=m['message_id'], text=msg, parse_mode='html')
                self.last_message_timestamp = time.time()
            except BadRequest as e:
                print(e)

    def set_headlines(self, headlines, bold_headlines=[]):
        self.headlines = headlines
        self.bold_headlines = bold_headlines
        self.update_message()

    def set_bold_headlines(self, bold_headlines):
        self.bold_headlines = bold_headlines
        self.update_message()

    def set_subtasks(self, subtasks):
        self.subtasks = subtasks
        self.subtask_progresses = ['0%' for _ in subtasks]
        self.set_current_subtask(0)

    def set_current_subtask(self, current_subtask_index):
        self.current_subtask_index = current_subtask_index
        self.update_message()

    def set_subtask_progress(self, subtask_progress):
        self.subtask_progresses[self.current_subtask_index] = subtask_progress
        self.update_message()

def message(update, context):
    chat_id = update.effective_chat.id
    query = re.split(r'\s+', update.message.text)
    #print(query)

    all_results = []
    playlist_title = None
    playlist_thumbnail = None

    progress_logger = TelegramProgressLogger(chat_id, context, headlines=['<b>Progress</b>'], bold_headlines=[0])
    ydl = youtube_dl.YoutubeDL({
        'outtmpl': './downloads/%(title)s.%(ext)s',
        'no_color': True,
        'format': 'worst',
        'keepvideo': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3'
        }],
        'logger': progress_logger
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

    message_id = str(update.message.message_id)
    if 'tasks' not in context.chat_data:
        context.chat_data['tasks'] = {}
    context.chat_data['tasks'][message_id] = {
        'all_results': all_results,
        'playlist_title': playlist_title,
        'playlist_thumbnail': playlist_thumbnail
    }

    # keyboard
    context.bot.send_message(chat_id=update.effective_chat.id, text='Download video or audio?', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Video', callback_data='video ' + message_id)], [InlineKeyboardButton('Audio', callback_data='audio ' + message_id)]]))

dispatcher.add_handler(CallbackQueryHandler(callback_query))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, message))

updater.start_polling()
