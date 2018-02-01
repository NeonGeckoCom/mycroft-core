# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import time
import re
import os
import json

from threading import Lock
from mycroft.configuration import Configuration
from mycroft.tts import TTSFactory
from mycroft.util import create_signal, check_for_signal
from mycroft.util.log import LOG
from socketIO_client import SocketIO
from mycroft.session import SessionManager

ws = None  # TODO:18.02 - Rename to "messagebus"
config = None
tts = None
tts_hash = None
lock = Lock()

_last_stop_signal = 0

audioChatUsers = []
css = SocketIO('https://3333.us', 8888,
               # verify='server.crt',
               # cert=('client.crt', 'client.key'),
               proxies={'http': 'https://3333.us:8888'})



def _start_listener(message):
    """
        Force Mycroft to start listening (as if 'Hey Mycroft' was spoken)
    """
    create_signal('startListening')


def handle_speak(event):
    """
        Handle "speak" message

    """
    # session = SessionManager.get()
    # filename = session.flac_filename
    # # filename = SessionManager.get().flac_filename
    #
    # if not filename:
    #     return

    # LOG.debug('audio/speech.py handle_speak event.data.get("chatUserFilename") = ' + str(event.data.get('chatUserFilename')))

    # if len(audioChatUsers) > 0:
    #     chatUser = audioChatUsers.pop()
    #     # chatuser_info = json.loads(chatUser[1])
    #     # filename = chatUser[1].flac_filename
    #     filename = os.path.basename(chatUser[1]['flac_filename'])
    # else:
    #     return
    #     # filename = None

    if event.data.message.data['flac_filename']:
        filename = event.data.message.data['flac_filename']
    else:
        return

    config = Configuration.get()
    Configuration.init(ws)
    global _last_stop_signal

    # Mild abuse of the signal system to allow other processes to detect
    # when TTS is happening.  See mycroft.util.is_speaking()

    # filename = os.path.basename(message.data['flac_filename'])
    # parts = filename.split('-')
    # shoutId = parts[1]
    # socketId = parts[2]
    # nickname = parts[3][0:-5]


    utterance = event.data['utterance']
    # utterance += ' \n<socket sid="' + socketId + '">'
    # utterance += ' \n<socket id="' + socketId + '" ' + 'sid="' + shoutId + '"></socket>'

    if event.data.get('expect_response', False):
        # When expect_response is requested, the listener will be restarted
        # at the end of the next bit of spoken audio.
        ws.once('recognizer_loop:audio_output_end', _start_listener)

    # This is a bit of a hack for Picroft.  The analog audio on a Pi blocks
    # for 30 seconds fairly often, so we don't want to break on periods
    # (decreasing the chance of encountering the block).  But we will
    # keep the split for non-Picroft installs since it give user feedback
    # faster on longer phrases.
    #
    # TODO: Remove or make an option?  This is really a hack, anyway,
    # so we likely will want to get rid of this when not running on Mimic
    # if not config.get('enclosure', {}).get('platform') == "picroft":
    #     start = time.time()
    #     chunks = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s',
    #                       utterance)
    #     for chunk in chunks:
    #         try:
    #             mute_and_speak(chunk, filename)
    #         except KeyboardInterrupt:
    #             raise
    #         except:
    #             LOG.error('Error in mute_and_speak', exc_info=True)
    #         if _last_stop_signal > start or check_for_signal('buttonPress'):
    #             break
    # else:
    mute_and_speak(utterance, filename)

    # mute_and_speak('<socket id="' + socketId + '" ' + 'sid="' + shoutId + '"></socket>', 'chat_data.wav')


def mute_and_speak(utterance, chatUserFilename):
    """
        Mute mic and start speaking the utterance using selected tts backend.

        Args:
            utterance: The sentence to be spoken
    """
    global tts_hash

    lock.acquire()
    # update TTS object if configuration has changed
    if tts_hash != hash(str(config.get('tts', ''))):
        global tts
        # Stop tts playback thread
        tts.playback.stop()
        tts.playback.join()
        # Create new tts instance
        tts = TTSFactory.create()
        tts.init(ws)
        tts_hash = hash(str(config.get('tts', '')))

    LOG.info("Speak: " + utterance)
    try:
        tts.execute(utterance, chatUserFilename)
    finally:
        lock.release()


def handle_stop(event):
    """
        handle stop message
    """
    global _last_stop_signal
    if check_for_signal("isSpeaking", -1):
        _last_stop_signal = time.time()
        tts.playback.clear_queue()
        tts.playback.clear_visimes()


def init(websocket):
    """
        Start speach related handlers
    """

    global ws
    global tts
    global tts_hash
    global config

    ws = websocket
    Configuration.init(ws)
    config = Configuration.get()
    ws.on('mycroft.stop', handle_stop)
    ws.on('mycroft.audio.speech.stop', handle_stop)
    ws.on('speak', handle_speak)
    ws.on('mycroft.mic.listen', _start_listener)
    # ws.on('chatUserToAudio', _handle_chatUser_utterance)
    # ws.on('recognizer_loop:chatUser_utterance', _handle_chatUser_utterance)
    ws.on('recognizer_loop:chatUser_response', _handle_chatUser_response)
    ws.on('mycroft.skill.chat_user_update', _handle_chat_user_update)

    tts = TTSFactory.create()
    tts.init(ws)
    tts_hash = config.get('tts')


def shutdown():
    global tts
    if tts:
        tts.playback.stop()
        tts.playback.join()


def _handle_chat_user_update(message):
    def find_chatUser_by_utterance(utterance):
        for cu in audioChatUsers:
            if cu[1]['utterance'] == utterance:
                return cu

    chatUser = find_chatUser_by_utterance(message.data['utterance'])
    chatUser[1]['intent_type'] = message.data.intent_type


# def _handle_chatUser_utterance(message):
# # def _handle_chatUser_utterance(text, flac_filename, sessionId):
#     filename = os.path.basename(message.data['flac_filename'])
#     parts = filename.split('-')
#     shoutId = parts[1]
#     socketId = parts[2]
#     nickname = parts[3][0:-5]
#     timestamp = str(time.time())
#     LOG.debug('audioChatUsers flac_filename = ' + message.data['flac_filename'])
#     # LOG.debug('audioChatUsers shoutId = ' + parts[1])
#     # LOG.debug('audioChatUsers socketId = ' + parts[2])
#     # LOG.debug('audioChatUsers nickname = ' + parts[3][0:-5])
#     # LOG.debug('audioChatUsers timestamp = ' + str(timestamp))
#     # LOG.debug('audioChatUsers sessionId = ' + str(sessionId))
#     chatUser = [socketId, {'shoutId': shoutId
#         , 'flac_filename': message.data['flac_filename']
#         , 'socketId': socketId
#         , 'nickname': nickname
#         , 'responseReceived': False
#         , 'utterance': message.data['text']
#         , 'timestamp': time.time()
#         , 'intent_type': ''}]
#     if socketId not in audioChatUsers:
#         audioChatUsers.append(chatUser)
#     else:
#         audioChatUsers.remove(chatUser)
#         audioChatUsers.append(chatUser)
#     LOG.debug('self.audioChatUsers = ' + str(audioChatUsers))


def _handle_chatUser_response(message):
    # chatUser = find_chatUser_by_utterance(message.data['utterance'])
    # chatUser = find_chatUser(3.5)
    # if len(audioChatUsers) > 0:
    #     chatUser = audioChatUsers.pop()
    # LOG.debug('audio _handle_chatUser_response, message = ' + str(message))

    try:
        # uid = pwd.getpwnam('guy')[2]
        # LOG.debug('''laptop root uid ==''' + str(uid))
        # os.setuid(uid)
        # os.system('/etc/init.d/mycroft-speech-client stop;
        #   /etc/init.d/mycroft-speech-client start')
        # LOG.debug(''' username = ''' +
        #           pwd.getpwuid(os.getuid()).pw_name)
        # os.system('sudo rm ' + self.flac_filename)
        # sudoPassword = 'neongecko22k'
        sudoPassword = 'ne0ngeck0'
        command = 'mv ' + message.data['wav_file'] \
                  + ' /var/www/html/sites/default/files/chat_audio/' \
                  + os.path.basename(message.data['wav_file'])
        # command = 'rm ' + self.flac_filename
        p = os.system('echo %s|sudo -S %s' % (sudoPassword, command))
    except Exception as e:
        LOG.debug('''error == ''' + str(e))


    if check_for_signal('MatchIntentandRespond', -1):
        css.emit('mycroft response', message.data['sentence'], os.path.basename(message.data['wav_file']))

    # try:
    #     # uid = pwd.getpwnam('guy')[2]
    #     # LOG.debug('''laptop root uid ==''' + str(uid))
    #     # os.setuid(uid)
    #     # os.system('/etc/init.d/mycroft-speech-client stop;
    #     #   /etc/init.d/mycroft-speech-client start')
    #     # LOG.debug(''' username = ''' +
    #     #           pwd.getpwuid(os.getuid()).pw_name)
    #     # os.system('sudo rm ' + self.flac_filename)
    #     # sudoPassword = 'neongecko22k'
    #     sudoPassword = 'ne0ngeck0'
    #     command = 'mv ' + message.data['wav_file'] \
    #               + ' /var/www/html/sites/default/files/chat_audio/' \
    #               + os.path.basename(message.data['wav_file'])
    #     # command = 'rm ' + self.flac_filename
    #     p = os.system('echo %s|sudo -S %s' % (sudoPassword, command))
    # except Exception as e:
    #     LOG.debug('''error == ''' + str(e))
    #
    # if check_for_signal('MatchIntentandRespond', -1):
    #     css.emit('mycroft response', message.data['sentence'], os.path.basename(message.data['wav_file']), chatUser)
    #
    # chatUsers.remove(chatUser)

