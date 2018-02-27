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
import sys
import os
import time
from threading import Thread, Lock

from mycroft.client.enclosure.api import EnclosureAPI
from mycroft.client.speech.listener import RecognizerLoop
from mycroft.configuration import Configuration
from mycroft.identity import IdentityManager
from mycroft.lock import Lock as PIDLock  # Create/Support PID locking file
from mycroft.messagebus.client.ws import WebsocketClient
from mycroft.messagebus.message import Message
from mycroft.util.log import LOG
from mycroft.util import (
    check_for_signal)
from socketIO_client import SocketIO


ws = None
lock = Lock()
loop = None

config = Configuration.get()

chatUsers = []
css = SocketIO('https://localhost:8888', verify=False)
# css = SocketIO('https://localhost', 8888, verify=False)
# css = SocketIO('localhost', 8888)
# css = SocketIO('https://0000.us', 8888,
#                # verify='server.crt',
#                # cert=('/var/www/html/klatchat/fullchain.pem', '/var/www/html/klatchat/privkey.pem')
#                proxies={'https': 'https://0000.us:8888'}
#                )


def handle_record_begin():
    LOG.info("Begin Recording...")
    ws.emit(Message('recognizer_loop:record_begin'))


def handle_record_end():
    LOG.info("End Recording...")
    ws.emit(Message('recognizer_loop:record_end'))


def handle_no_internet():
    LOG.debug("Notifying enclosure of no internet connection")
    ws.emit(Message('enclosure.notify.no_internet'))


def handle_awoken():
    """ Forward mycroft.awoken to the messagebus. """
    LOG.info("Listener is now Awake: ")
    ws.emit(Message('mycroft.awoken'))


def handle_wakeword(event):
    if not check_for_signal('skip_wake_word', -1):
        LOG.info("Wakeword Detected: " + event['utterance'])
    else:
        LOG.info("Wakeword skipped: ")
    ws.emit(Message('recognizer_loop:wakeword', event))


def handle_utterance(event):
    LOG.info("Utterance: " + str(event['utterances']))
    context = {'client_name': 'mycroft_listener'}
    if 'ident' in event:
        ident = event.pop('ident')
        context['ident'] = ident
    ws.emit(Message('recognizer_loop:utterance', event, context))


def handle_unknown():
    ws.emit(Message('mycroft.speech.recognition.unknown'))

# 1st try websocket to chat_server.js
    # chat_ws = create_connection("ws://localhost:8888")
    # LOG.info("Sending 'user message to chat'...")
    # chat_ws.send("user message", str(event['utterances']))
    # LOG.info("Sent")
    # LOG.info("Receiving...")
    # result = chat_ws.recv()
    # LOG.info("Received '%s'" % result)
    # chat_ws.close()



def handle_speak(event):
    """
        Forward speak message to message bus.
    """
    # chatUser = chatUsers.pop()
    # LOG.debug("chatUser[1]['flac_filename'] = " + chatUser[1]['flac_filename'])
    # event.data['chatUserFilename'] = chatUser[1]['flac_filename']
    # LOG.debug("event.data['chatUserFilename'] = " + event.data['chatUserFilename'])
    LOG.debug(">>>>> event.data = " + str(event.data))
    LOG.debug(">>>>> event.data['flac_filename'] = " + event.data['flac_filename'])
    ws.emit(Message('speak', event))


def handle_complete_intent_failure(event):
    LOG.info("Failed to find intent.")
    chatUser = chatUsers.pop()
    # TODO: Localize
    if not check_for_signal('skip_wake_word', -1):
        data = {
            'utterance':
            "Sorry, I didn't catch that. " +
            "Please rephrase your request."
            ,'chatUserFilename': chatUser[1]['flac_filename']}
        ws.emit(Message('speak', data))


def handle_sleep(event):
    loop.sleep()


def handle_wake_up(event):
    loop.awaken()


def handle_mic_mute(event):
    loop.mute()


def handle_mic_unmute(event):
    loop.unmute()


def handle_restart(event):
    loop.restart()


def handle_reload(event):
    loop.reload()


def handle_paired(event):
    IdentityManager.update(event.data)


def handle_audio_start(event):
    """
        Mute recognizer loop
    """
    loop.mute()


def handle_audio_end(event):
    """
        Request unmute, if more sources has requested the mic to be muted
        it will remain muted.
    """
    loop.unmute()  # restore


def handle_stop(event):
    """
        Handler for mycroft.stop, i.e. button press
    """
    loop.force_unmute()


def handle_open():
    # TODO: Move this into the Enclosure (not speech client)
    # Reset the UI to indicate ready for speech processing
    EnclosureAPI(ws).reset()


def handle_chatUser_return_stt(text, flac_filename):
    # filename = os.path.basename(flac_filename)
    # parts = filename.split('-')
    # shoutId = parts[1]
    # socketId = parts[2]
    # nickname = parts[3][0:-5]
    # timestamp = str(time.time())
    # # LOG.debug('chatUser shoutId = ' + parts[1])
    # # LOG.debug('chatUser socketId = ' + parts[2])
    # # LOG.debug('chatUser nickname = ' + parts[3][0:-5])
    # # LOG.debug('chatUser timestamp = ' + str(timestamp))
    # # LOG.debug('chatUser sessionId = ' + str(sessionId))
    # chatUser = [nickname, {'shoutId': shoutId
    #     , 'socketId': socketId
    #     , 'nickname': nickname
    #     , 'responseReceived': False
    #     , 'utterance': text
    #     , 'timestamp': time.time()
    #     , 'sessionId': sessionId
    #     , 'flac_filename': flac_filename}]
    # if nickname not in chatUsers:
    #     chatUsers.append(chatUser)
    # else:
    #     chatUsers.remove(chatUser)
    #     chatUsers.append(chatUser)
    # ws.emit(Message('chatUserToAudio', {'text': text, 'flac_filename': flac_filename, 'sessionId':sessionId}) )
    # LOG.debug('chatUsers = ' + str(chatUsers))
    css.emit('stt from mycroft', text, flac_filename)


# def handle_chatUser_response(message):
#     # chatUser = find_chatUser_by_utterance(message.data['utterance'])
#     # chatUser = find_chatUser(3.5)
#     # chatUser = chatUsers.pop()
#     # LOG.debug('handle_chatUser_response, chatUser = ' + str(chatUser))
#
#     try:
#         # uid = pwd.getpwnam('guy')[2]
#         # LOG.debug('''laptop root uid ==''' + str(uid))
#         # os.setuid(uid)
#         # os.system('/etc/init.d/mycroft-speech-client stop;
#         #   /etc/init.d/mycroft-speech-client start')
#         # LOG.debug(''' username = ''' +
#         #           pwd.getpwuid(os.getuid()).pw_name)
#         # os.system('sudo rm ' + self.flac_filename)
#         # sudoPassword = 'neongecko22k'
#         sudoPassword = 'ne0ngeck0'
#         command = 'mv ' + message.data['wav_file'] \
#                   + ' /var/www/html/sites/default/files/chat_audio/' \
#                   + os.path.basename(message.data['wav_file'])
#         # command = 'rm ' + self.flac_filename
#         p = os.system('echo %s|sudo -S %s' % (sudoPassword, command))
#     except Exception as e:
#         LOG.debug('''error == ''' + str(e))
#
#     if check_for_signal('MatchIntentandRespond', -1):
#         css.emit('mycroft response', message.data['sentence'], os.path.basename(message.data['wav_file']))
#
#     # chatUsers.remove(chatUser)



def find_chatUser(secs):
    timeNow = time.time()
    for cu in chatUsers:
        if cu[1]['timestamp'] <= timeNow and \
                cu[1]['timestamp'] > timeNow - secs:
            LOG.debug('timeNow - secs = ' + str(timeNow - secs))
            LOG.debug('timeNow = ' + str(timeNow))
            LOG.debug('cu[1]["timestamp"] = ' + str(cu[1]['timestamp']))
            return cu

def find_chatUser_by_utterance(utterance):
    for cu in chatUsers:
        if cu[1]['utterance'] == utterance:
            return cu

def find_chatUser2(sessionId):
    for cu in chatUsers:
        if cu[1]['sessionId'] == sessionId:
            return cu


def connect():
    ws.run_forever()

def main():
    global ws
    global loop
    global config
    # global css     # chat server socket connection
    lock = PIDLock("voice")
    ws = WebsocketClient()
    config = Configuration.get()
    Configuration.init(ws)
    loop = RecognizerLoop()

    loop.on('recognizer_loop:utterance', handle_utterance)
    loop.on('recognizer_loop:speech.recognition.unknown', handle_unknown)
    loop.on('speak', handle_speak)
    loop.on('recognizer_loop:record_begin', handle_record_begin)
    loop.on('recognizer_loop:awoken', handle_awoken)
    loop.on('recognizer_loop:wakeword', handle_wakeword)
    loop.on('recognizer_loop:record_end', handle_record_end)
    loop.on('recognizer_loop:no_internet', handle_no_internet)
    loop.on('recognizer_loop:restart', handle_restart)
    loop.on('recognizer_loop:reload', handle_reload)
    loop.on('recognizer_loop:chatUser_return_stt', handle_chatUser_return_stt)
    # loop.on('recognizer_loop:chatUser_response', handle_chatUser_response)
    # loop.on('recognizer_loop:chatUser_response1', handle_chatUser_response1)
    ws.on('open', handle_open)
    ws.on('complete_intent_failure', handle_complete_intent_failure)
    ws.on('recognizer_loop:sleep', handle_sleep)
    ws.on('recognizer_loop:wake_up', handle_wake_up)
    ws.on('recognizer_loop:restart', handle_restart)
    ws.on('recognizer_loop:reload', handle_reload)
    # ws.on('recognizer_loop:chatUser_utterance', handle_chatUser_utterance)
    # ws.on('recognizer_loop:chatUser_response', handle_chatUser_response)
    # ws.on('recognizer_loop:chatUser_response1', handle_chatUser_response1)
    ws.on('mycroft.mic.mute', handle_mic_mute)
    ws.on('mycroft.mic.unmute', handle_mic_unmute)
    ws.on("mycroft.paired", handle_paired)
    ws.on('recognizer_loop:audio_output_start', handle_audio_start)
    ws.on('recognizer_loop:audio_output_end', handle_audio_end)
    ws.on('mycroft.stop', handle_stop)
    ws.on('speak', handle_speak)
    event_thread = Thread(target=connect)
    event_thread.setDaemon(True)
    event_thread.start()

    try:
        loop.run()
    except KeyboardInterrupt as e:
        LOG.exception(e)
        sys.exit()

if __name__ == "__main__":
    main()
