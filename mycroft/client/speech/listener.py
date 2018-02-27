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
from threading import Thread
import sys
import multiprocessing

import speech_recognition as sr
from pyee import EventEmitter
from requests import HTTPError
from requests.exceptions import ConnectionError

import pwd
import os, shutil
import mycroft.dialog
from mycroft.client.speech.hotword_factory import HotWordFactory
from mycroft.client.speech.mic import MutableMicrophone, ResponsiveRecognizer
from mycroft.configuration import Configuration
from mycroft.metrics import MetricsAggregator, Stopwatch, report_timing
from mycroft.session import SessionManager
from mycroft.stt import STTFactory
from mycroft.util.log import LOG
if sys.version_info[0] < 3:
    from Queue import Queue, Empty
else:
    from queue import Queue, Empty
from mycroft.client.speech.pocketsphinx_audio_consumer \
    import PocketsphinxAudioConsumer
from mycroft.util import (create_signal, check_for_signal)
from mycroft.client.speech.transcribe import Transcribe
from speech_recognition import (
    AudioData
)
from socketIO_client import SocketIO
import glob


# os.sys.path.append('/usr/lib/python2.7/dist-packages')
# os.sys.path.append('/usr/local/lib/python2.7/dist-packages')
import sox


class AudioProducer(Thread):
    """
    AudioProducer
    given a mic and a recognizer implementation, continuously listens to the
    mic for potential speech chunks and pushes them onto the queue.
    """

    def __init__(self, state, queue, mic, recognizer, emitter):
        super(AudioProducer, self).__init__()
        self.daemon = True
        self.state = state
        self.queue = queue
        self.mic = mic
        self.recognizer = recognizer
        self.emitter = emitter

    def run(self):
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source)
            while self.state.running:
                try:
                    # audio = self.recognizer.listen(source, self.emitter)

                    if not (self.utterance_is_min_len_silence(audio, source)):
                        self.queue.put(audio)
                    else:
                        LOG.debug('STT bypassed... SILENCE...')
                except IOError as e:
                    # NOTE: Audio stack on raspi is slightly different, throws
                    # IOError every other listen, almost like it can't handle
                    # buffering audio between listen loops.
                    # The internet was not helpful.
                    # http://stackoverflow.com/questions/10733903/pyaudio-input-overflowed
                    self.emitter.emit("recognizer_loop:ioerror", e)


    def utterance_is_min_len_silence(self, audio, source):
        filename = "/tmp/mycroft_utterance.wav"
        with open(filename, 'wb') as filea:
            filea.write(audio.get_wav_data())

        LOG.debug("self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE = " + str(self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE))
        LOG.debug("sox.file_info.duration = " + str(self.truncate(sox.file_info.duration(filename),1)))
        # LOG.debug("sox.file_info.silent = " + str(sox.file_info.silent(filename, source.energy_threshold)))
        LOG.debug("sox.file_info.silent = " + str(sox.file_info.silent(filename, 0.015)))

        LOG.debug('bool = '+ str(bool(sox.file_info.silent(filename, 0.015) and
                    (str(self.truncate(sox.file_info.duration(filename),1)) ==
                     str(self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE)))))

        return bool(sox.file_info.silent(filename, 0.015) )

        # return bool(sox.file_info.silent(filename, 0.015)
        #             and
        #             (str(self.truncate(sox.file_info.duration(filename),1)) ==
        #              str(self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE)))

        # check_audio = AudioSegment.from_raw(filename, sample_width=2, frame_rate=16000, channels=1)
        # # silence1 = silence.detect_nonsilent(check_audio, min_silence_len=2000, silence_thresh=-24)
        # silence1 = silence.detect_silence(check_audio, min_silence_len=1000, silence_thresh=-0)
        #
        # silence1 = [((start), (stop)) for start, stop in silence1]  # convert to sec
        # # silence1 = [((start / 1000), (stop / 1000)) for start, stop in silence1]  # convert to sec
        # LOG.debug("silence1 = " + str(silence1))
        # LOG.debug("len(audio.frame_data) = " + str(len(audio.frame_data)))
        # silence_boundary = self.truncate((float(len(audio.frame_data)) / (
        #     audio.sample_rate * audio.sample_width)) * 1000, 0)
        #
        # LOG.debug("silence_boundary[0:4] = " + str(silence_boundary[0:4]))
        #
        # if self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE == 1.0:
        #     length = 32770
        #     # silence_boundary = 1024
        # elif self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE == 2.0:
        #     length = 65538
        # elif self.recognizer.RECORDING_TIMEOUT_WITH_SILENCE == 3.0:
        #     length = 96258
        #
        # LOG.debug("test = " + str(bool(silence1 == [(0, int(silence_boundary[0:4]))] and\
        #                             len(audio.frame_data) == length)))
        #
        # return bool(silence1 == [(0, int(silence_boundary[0:4]))] and\
        #                             len(audio.frame_data) == length)


    def truncate(self, f, n):
        '''Truncates/pads a float f to n decimal places without rounding'''
        s = '{}'.format(f)
        if 'e' in s or 'E' in s:
            return '{0:.{1}f}'.format(f, n)
        i, p, d = s.partition('.')
        return '.'.join([i, (d + '0' * n)[:n]])


    def stop(self):
        """
            Stop producer thread.
        """
        self.state.running = False
        self.recognizer.stop()


class AudioConsumer(Thread):
    """
    AudioConsumer
    Consumes AudioData chunks off the queue
    """

    # In seconds, the minimum audio size to be sent to remote STT
    MIN_AUDIO_SIZE = 0.5

    MAX_LOCAL_TRANSCRIBE_PROCESSES = 8
    MIN_LOCAL_TRANSCRIBE_PROCESSES = 2

    def __init__(self, state, queue, emitter, stt,
                 wakeup_recognizer, wakeword_recognizer):
        super(AudioConsumer, self).__init__()
        self.daemon = True
        self.queue = queue
        self.state = state
        self.emitter = emitter
        self.stt = stt
        self.wakeup_recognizer = wakeup_recognizer
        self.wakeword_recognizer = wakeword_recognizer
        self.metrics = MetricsAggregator()
        self.transcribe_jobs = []
        self.audioFilename = ''
        # css = SocketIO('https://localhost:8888', verify=False)
        css = SocketIO('https://localhost', 8888, verify=False)
        # css = SocketIO('https://0000.us', 8888,
        #                # verify='server.crt',
        #                # cert=('/var/www/html/klatchat/fullchain.pem', '/var/www/html/klatchat/privkey.pem')
        #                proxies={'https': 'https://0000.us:8888'}
        #                )
        # self.css.emit('mycroft stt connected')
        # self.css.on('mycroft stt', self.handle_mycroft_stt)
        # self.css.wait()

    # def handle_mycroft_stt(self, chat_socketid, shoutId, audioFilename):
    #     LOG.debug('chat_socketid = ' + chat_socketid)
    #     LOG.debug('shoutId = ' + shoutId)
    #     LOG.debug('audioFilename = ' + audioFilename)
    #     self.chat_socketid = chat_socketid
    #     self.shoutId = shoutId
    #     self.audioFilename = audioFilename
    #     create_signal('FileInputToSTT')

    def run(self):
        while self.state.running:
            self.read()
            if isinstance(self.stt, PocketsphinxAudioConsumer):
                if len(multiprocessing.active_children()) \
                        > self.MAX_LOCAL_TRANSCRIBE_PROCESSES:
                    for j in self.transcribe_jobs:
                        LOG.debug("waiting for process to end, j.ident  = " +
                                  str(j.ident))
                        j.join()
                        self.transcribe_jobs.remove(j)
                        LOG.debug("Process ended, j.ident = " + str(j.ident))
                        if len(multiprocessing.active_children()) \
                                <= self.MIN_LOCAL_TRANSCRIBE_PROCESSES:
                            break
                    LOG.debug("after joining, " +
                              "multiprocessing.active_children() = " +
                              str(len(multiprocessing.active_children())))
                    LOG.debug("len(transcribe_jobs) = " +
                              str(len(self.transcribe_jobs)))
                for j in self.transcribe_jobs:
                    if not j.is_alive():
                        self.transcribe_jobs.remove(j)

    def read(self):
        audio = None
        try:
            if check_for_signal('FileInputToSTT', -1):
                # raw_data = open("/var/log/STTInput.ogg", "rb").read()
                # self.flac_filename = self.audioFilename
                self.flac_filename = self.get_most_recent('/var/www/html/klatchat/app/files/chat_audio/sid-*.flac') # .92
                # self.flac_filename = self.get_most_recent('/var/www/html/sites/default/files/chat_audio/sid-*.flac') # .223
                if not self.flac_filename:
                    check_for_signal('FileInputToSTT')
                    return
                try:
                    LOG.debug(''' flac_filename to read = ''' + str(self.flac_filename))

                    audio = AudioData(open(self.flac_filename, "rb").read(), 16000, 1)

                    # audio = AudioData(open("/var/log/STTInput.flac", "rb").read(), 16000, 1)
                    # LOG.debug(''' audio.frame_data ''' + str(audio.frame_data))
                except Exception as e:
                    LOG.debug('''audio file open error == ''' + str(e))
                finally:
                    BASEDIR = os.path.abspath(
                        os.path.join(os.path.dirname(__file__),
                                     '..', '..', '..')
                    )
                    LOG.debug('BASEDIR = ' + BASEDIR)
                    try:
                        # uid = pwd.getpwnam('guy')[2]
                        # LOG.debug('''laptop root uid ==''' + str(uid))
                        # os.setuid(uid)
                        # os.system('/etc/init.d/mycroft-speech-client stop;
                        #   /etc/init.d/mycroft-speech-client start')
                        LOG.debug(''' username = ''' +
                                  pwd.getpwuid(os.getuid()).pw_name)
                        # os.system('sudo rm ' + self.flac_filename)

                        # sudoPassword = 'neongecko22k' # guys laptop

                        # sudoPassword = 'ne0ngeck0' # 223
                        # mvToDirectory = ' /home/mycroft/mycroft-core/scripts/logs/chat_audio/'

                        sudoPassword = 'ceX+w6S=2[qB?a'  # .92
                        mvToDirectory = ' /home/guydaniels1953/mycroft-core/scripts/logs/chat_audio/'

                        command = 'mv ' + self.flac_filename \
                                  + mvToDirectory \
                                  + os.path.basename(self.flac_filename)
                        # command = 'rm ' + self.flac_filename
                        p = os.system('echo %s|sudo -S %s' % (sudoPassword, command))
                    except Exception as e:
                        LOG.debug('''error == ''' + str(e))

                    # os.rename(self.flac_filename,self.flac_filename.replace('.flac','.saveflac'))
                    # with open(self.flac_filename, 'wb') as f:
                    #     f.write('/home/mycroft/mycroft-core/scripts/logs/chat_audio' + os.path.basename(self.flac_filename))
                    # os.rename(self.flac_filename, '/home/mycroft/mycroft-core/scripts/logs/chat_audio' + os.path.basename(self.flac_filename))
            else:
                audio = self.queue.get(timeout=0.5)
        except Empty:
            return

        if audio is None:
            return

        if self.state.sleeping:
            self.wake_up(audio)
        else:
            if isinstance(self.stt, PocketsphinxAudioConsumer):

                process = multiprocessing.Process(target=self.process,
                                                  args=([audio]))

                process.start()

                self.transcribe_jobs.append(process)

                LOG.debug("listener.py, read str(self.transcribe_jobs) = " +
                          str(self.transcribe_jobs))
            else:
                self.process(audio)

    def get_most_recent(self, path):
        list_of_files = glob.glob(path)  # * means all if need specific format then *.csv
        if list_of_files:
            latest_file = max(list_of_files, key=os.path.getctime)
            return latest_file
        else:
            return False

    # TODO: Localization
    def wake_up(self, audio):
        if self.wakeup_recognizer.found_wake_word(audio.frame_data):
            SessionManager.touch()
            self.state.sleeping = False
            self.emitter.emit('recognizer_loop:awoken')
            self.metrics.increment("mycroft.wakeup")

    @staticmethod
    def _audio_length(audio):
        return float(len(audio.frame_data)) / (
            audio.sample_rate * audio.sample_width)

    # TODO: Localization
    def process(self, audio):
        SessionManager.touch()
        payload = {
            'utterance': self.wakeword_recognizer.key_phrase,
            'session': SessionManager.get(self.flac_filename).session_id,
        }
        self.emitter.emit("recognizer_loop:wakeword", payload)

        if self._audio_length(audio) < self.MIN_AUDIO_SIZE:
            LOG.warning("Audio too short to be processed")
        else:
            # if len(audio.frame_data) != 65538:  # 2 seconds (silence)
                # if len(audio.frame_data) != 96258:  # 3 seconds silence
                if isinstance(self.stt, PocketsphinxAudioConsumer):
                    # LOG.debug("test phrase decode/transcribe")
                    hyp = self.stt.transcribe(audio.frame_data)
                    # hyp = self.stt.wake_word_recognizer.transcribe(
                    # audio.frame_data)
                    if hyp:
                        if hyp.hypstr > '':
                            payload = {
                                'utterances': [hyp.hypstr.lower()],
                                'lang': self.stt.lang,
                                'session': SessionManager.get(self.flac_filename).session_id
                            }
                            self.emitter.emit("recognizer_loop:utterance",
                                              payload)
                            self.metrics.attr('utterances',
                                              [hyp.hypstr.lower()])

                else:
                    stopwatch = Stopwatch()
                    with stopwatch:
                        transcription = self.transcribe(audio)
                    if transcription:
                        ident = str(stopwatch.timestamp) + str(hash(transcription))
                        # STT succeeded, send the transcribed speech on for processing

                        payload = {
                            'utterances': [transcription],
                            'lang': self.stt.lang,
                            'session': SessionManager.get().session_id,
                            'ident': ident,
                            'flac_filename': self.flac_filename
                        }
                        self.emitter.emit("recognizer_loop:utterance", payload)
                        self.metrics.attr('utterances', [transcription])
                        Transcribe.write_transcribed_files(audio.frame_data, transcription)
                        self.emitter.emit('recognizer_loop:chatUser_return_stt', transcription, self.flac_filename)
                    else:
                        ident = str(stopwatch.timestamp)
                    # Report timing metrics
                    report_timing(ident, 'stt', stopwatch,
                                  {'transcription': transcription,
                                   'stt': self.stt.__class__.__name__})


    def transcribe(self, audio):
            text = None
            # filename = os.path.basename(self.flac_filename)
            # parts = filename.split('-')
            # shoutId = parts[1]
            # socketId = parts[2]
            # nickname = parts[3][0:-5]
            try:
                # Invoke the STT engine on the audio clip
                text = self.stt.execute(audio).lower().strip()
                LOG.debug("STT: " + text)
            except sr.RequestError as e:
                LOG.error("Could not request Speech Recognition {0}".format(e))
            except ConnectionError as e:
                LOG.error("Connection Error: {0}".format(e))
                self.emitter.emit("recognizer_loop:no_internet")
            except HTTPError as e:
                if e.response.status_code == 401:
                    text = "pair my device"  # phrase to start the pairing process
                    LOG.warning("Access Denied at mycroft.ai")
            except Exception as e:
                self.emitter.emit('recognizer_loop:speech.recognition.unknown')
                LOG.error(e)
                LOG.error("Speech Recognition could not understand audio")
            return text
            # if text:
            #     # STT succeeded, send the transcribed speech on for processing
            #     payload = {
            #         'utterances': [text],
            #         'lang': self.stt.lang,
            #         'session': SessionManager.get().session_id,
            #         'flac_filename': self.flac_filename
            #     }
            #     payload2 = {
            #         'utterances': text,
            #         'lang': self.stt.lang,
            #         'session': SessionManager.get(self.flac_filename).session_id,
            #         'flac_filename': self.flac_filename
            #     }
            #     self.emitter.emit("recognizer_loop:utterance", payload)
            #     self.metrics.attr('utterances', [text])
            #     Transcribe.write_transcribed_files(audio.frame_data, text)
            #     self.emitter.emit('recognizer_loop:chatUser_return_stt', text, self.flac_filename)

    def __speak(self, utterance):
        payload = {
            'utterance': utterance,
            'session': SessionManager.get(self.flac_filename).session_id
        }
        self.emitter.emit("speak", payload)


class RecognizerLoopState(object):
    def __init__(self):
        self.running = False
        self.sleeping = False


class RecognizerLoop(EventEmitter):
    """
        EventEmitter loop running speech recognition. Local wake word
        recognizer and remote general speech recognition.
    """

    def __init__(self):
        super(RecognizerLoop, self).__init__()
        self.mute_calls = 0
        self._load_config()

    def _load_config(self):
        """
            Load configuration parameters from configuration
        """
        config = Configuration.get()
        self.config_core = config
        self._config_hash = hash(str(config))
        self.lang = config.get('lang')
        self.config = config.get('listener')
        rate = self.config.get('sample_rate')
        device_index = self.config.get('device_index')
        self.enclosure_config = config.get('enclosure')

        self.microphone = MutableMicrophone(device_index, rate,
                                            mute=self.mute_calls > 0)
        # FIXME - channels are not been used
        self.microphone.CHANNELS = self.config.get('channels')

        if check_for_signal('UseLocalSTT', -1):
            self.wakeword_recognizer = PocketsphinxAudioConsumer(
                self.config, self.lang, self)
        else:
            self.wakeword_recognizer = self.create_wake_word_recognizer()

        self.wakeup_recognizer = self.create_wakeup_recognizer()
        # TODO - localization
        self.wakeup_recognizer = self.create_wakeup_recognizer()
        self.responsive_recognizer = ResponsiveRecognizer(
            self.wakeword_recognizer)
        self.state = RecognizerLoopState()

    def create_wake_word_recognizer(self):
        # Create a local recognizer to hear the wakeup word, e.g. 'Hey Mycroft'
        LOG.info("creating wake word engine")
        word = self.config.get("wake_word", "hey mycroft")
        # TODO remove this, only for server settings compatibility
        phonemes = self.config.get("phonemes")
        thresh = self.config.get("threshold")
        config = self.config_core.get("hotwords", {word: {}})

        if word not in config:
            config[word] = {'module': 'pocketsphinx'}
        if phonemes:
            config[word]["phonemes"] = phonemes
        if thresh:
            config[word]["threshold"] = thresh
        if phonemes is None or thresh is None:
            config = None
        return HotWordFactory.create_hotword(word, config, self.lang)

    def create_wakeup_recognizer(self):
        LOG.info("creating stand up word engine")
        word = self.config.get("stand_up_word", "wake up")
        return HotWordFactory.create_hotword(word, lang=self.lang)

    def start_async(self):
        """
            Start consumer and producer threads
        """
        self.state.running = True
        queue = Queue()

        # self.producer = AudioProducer(self.state, queue, self.microphone,
        #                               self.responsive_recognizer, self)
        # self.producer.start()
        if check_for_signal('UseLocalSTT', -1):
            LOG.info("creating Local SST engine")
            self.consumer = AudioConsumer(self.state, queue, self,
                                          self.wakeword_recognizer,
                                          self.wakeup_recognizer,
                                          self.wakeword_recognizer)
        else:
            LOG.info("creating Remote SST engine")
            self.consumer = AudioConsumer(self.state, queue, self,
                                          STTFactory.create(),
                                          self.wakeup_recognizer,
                                          self.wakeword_recognizer)
        self.consumer.start()

    def stop(self):
        self.state.running = False
        # self.producer.stop()
        # wait for threads to shutdown
        # self.producer.join()
        self.consumer.join()

    def mute(self):
        """
            Mute microphone and increase number of requests to mute
        """
        self.mute_calls += 1
        if self.microphone:
            self.microphone.mute()

    def unmute(self):
        """
            Unmute mic if as many unmute calls as mute calls have been
            received.
        """
        if self.mute_calls > 0:
            self.mute_calls -= 1

        if self.mute_calls <= 0 and self.microphone:
            self.microphone.unmute()
            self.mute_calls = 0

    def force_unmute(self):
        """
            Completely unmute mic dispite the number of calls to mute
        """
        self.mute_calls = 0
        self.unmute()

    def is_muted(self):
        if self.microphone:
            return self.microphone.is_muted()
        else:
            return True  # consider 'no mic' muted

    def sleep(self):
        self.state.sleeping = True

    def awaken(self):
        self.state.sleeping = False

    def run(self):
        self.start_async()
        while self.state.running:
            try:
                time.sleep(1)
                if self._config_hash != hash(
                        str(Configuration().get())):
                    LOG.debug('Config has changed, reloading...')
                    self.reload()
            except KeyboardInterrupt as e:
                LOG.error(e)
                self.stop()
                raise  # Re-raise KeyboardInterrupt

    def reload(self):
        """
            Reload configuration and restart consumer and producer
        """
        self.stop()
        # load config
        self._load_config()
        # restart
        self.start_async()


    def restart(self):
        """
            Restart the speech/voice client
        """
        platform = str(self.enclosure_config.get(
            'platform', 'laptop/desktop platform'))
        LOG.debug('''self.enclosure_config.get('platform') ==''' + platform)
        if platform == "picroft" or platform == "mycroft_mark_1":
            LOG.debug('''my/pi croft platform''')
            try:
                # uid = pwd.getpwnam('mycroft')[2]
                # LOG.debug('''my/pi croft root uid ==''' + str(uid))
                # os.setuid(uid)
                LOG.debug(''' username = ''' +
                          pwd.getpwuid(os.getuid()).pw_name)
                os.system('/etc/init.d/mycroft-speech-client restart')
            except Exception as e:
                LOG.debug('''error == ''' + str(e))
        else:
            LOG.debug('''laptop/desktop platform''')
            BASEDIR = os.path.abspath(
                os.path.join(os.path.dirname(__file__),
                             '..', '..', '..')
            )
            LOG.debug('BASEDIR = ' + BASEDIR)
            try:
                # uid = pwd.getpwnam('guy')[2]
                # LOG.debug('''laptop root uid ==''' + str(uid))
                # os.setuid(uid)
                # os.system('/etc/init.d/mycroft-speech-client stop;
                #   /etc/init.d/mycroft-speech-client start')
                LOG.debug(''' username = ''' +
                          pwd.getpwuid(os.getuid()).pw_name)
                os.system(BASEDIR + '/start-mycroft.sh voice')
            except Exception as e:
                LOG.debug('''error == ''' + str(e))
