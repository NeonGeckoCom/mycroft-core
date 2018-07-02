from mycroft.util.log import LOG
from mycroft.configuration import Configuration, LocalConf, USER_CONFIG
import wave
import mycroft as mycroft_core
import mycroft.configuration
from pydub import AudioSegment
from mycroft.device import device
from mycroft.util.signal import (
    check_for_signal,
    create_signal
)
import datetime
import os
import csv

__author__ = "reginaneon"


class Transcribe(object):
    """
    Name: Transcribe
    Purpose: Writes the transcription and CSV files.
    Imports data to the new, more precise text file, containing
             the lines needed.
    """

    def __init__(self):
        # Retrieve user's permissions:
        self.text_permission = create_signal('transcribe_text_permission')
        self.audio_permission = create_signal('keep_audio_permission')
        user_config = LocalConf(USER_CONFIG)

        if not user_config.get('prof_name'):
            new_config = {
                'prof_name': "Not Specified"
                }
            user_config.merge(new_config)
            user_config.store()
        else:
            self.profile_name = user_config.get('prof_name')

        LOG.info(self.profile_name)

        # Setup the headers for the CSV:
        self.list_transcription_headers = ["Date", "Time", "Profile", "Device",
                                           "Input", "Location", "Wav_Length"]

        # Specify transcription location based on the device used:
        self.transcripts_folder = str(mycroft_core.__file__).replace("mycroft/__init__.py", "NGI/Documents/")

        # Make sure that all of the directories are in place:
        self.check_dir("ts_transcript_audio_segments/")
        self.check_dir("ts_transcripts/")

        self.csv_path = self.transcripts_folder + "csv_files/"

        if not self.check_dir("csv_files/"):
                LOG.info("CSV location specified.")

                # Initialize the CSV files:
                self.update_csv(self.list_transcription_headers, "full_ts.csv")
                LOG.info("CSV full transcription initialized.")

                if os.path.isdir(mycroft.configuration.Configuration.get()['skills_dir'] + "/skill-i-like-brands"):
                    self.list_selected_headers = ["Date", "Profile", "Device", "Phrase", "Instance",
                                                  "Brand"]
                    self.update_csv(self.list_selected_headers, "selected_ts.csv")
                    LOG.info("CSV selected transcription initialized.")

    def write_transcribed_files(self, audio, text):
        globstamp = str(datetime.datetime.now())
        globdate = str(datetime.date.today())
        details = [globdate, globstamp[11:]]

        if check_for_signal('skip_wake_word', -1) and not self.profile_name == "":
            details.append(self.profile_name)
        else:
            details.append("Not Specified")
            LOG.info(self.profile_name)

        details.append(device)

        if check_for_signal('transcribe_text_permission', -1):
            self.check_dir("ts_transcript_audio_segments/" + globdate)
            # if trans_values.text_permission:
            filename1 = self.transcripts_folder + "ts_transcripts/" + \
                        globdate + ".txt"

            with open(filename1, 'a+') as filea:
                filea.write(globstamp + " " + text + "\n")
                details.append(text)
                LOG.info("Transcribing Permission Granted: "
                         "Text Input of '" + text + "' Saved Successfully")

        else:
            LOG.warning("Transcribing Permission Denied. CSV are not available.")

        if check_for_signal('keep_audio_permission', -1):
            LOG.info("Audio Save Permission Granted")

            filename = self.transcripts_folder + "ts_transcript_audio_segments/" + \
                       globdate + "/" + (globstamp + " " + text) + " .wav"
            details.append(self.transcripts_folder + "ts_transcript_audio_segments/" + globdate)

            if len(filename) > 250:
                filename = (filename[:150] + "... .wav")

            try:
                waveFile = wave.open(filename, 'wb')
                waveFile.setnchannels(1)
                waveFile.setsampwidth(2)
                waveFile.setframerate(16000)
                waveFile.writeframes(audio)
                waveFile.close()

                LOG.info(
                    "Transcribing Permission Granted: The Audio Recording of "
                    "User's Input Saved in Full Format")
            except IOError as e:
                LOG.error("The Audio Recording associated with the utterance was not saved."
                          "Check the truncating function:")
                LOG.error(e)

        else:
            LOG.info("Audio Save Permission Denied")

        try:
            self.change_db(filename, details)
        except IOError as e:
            LOG.error(e)

    def update_csv(self, info, location):
        try:
            with open(self.csv_path + location, 'a+') as to_write:
                writer = csv.writer(to_write)
                writer.writerow(info)
        except IOError as e:
            LOG.error("Problem with CSV file!")
            LOG.error(e)

    def change_db(self, name, details):
        song = AudioSegment.from_wav(name)
        details.append(song.duration_seconds)

        LOG.info(song.dBFS)
        LOG.info(name)

        if song.dBFS != -18.0:
            change_needed = -18.0 - song.dBFS
            song = song.apply_gain(change_needed)
            song.export(name, format="wav", tags={'artist': self.profile_name,
                                                  'album': str(details[0]),
                                                  'comments': str(details[3])})
            LOG.info(song.dBFS)

        self.update_csv(details, "full_ts.csv")

    def check_dir(self, location):
        loc_temp = self.transcripts_folder + location
        bool_temp = os.path.isdir(loc_temp)

        if not bool_temp:
            try:
                os.makedirs(loc_temp)
            except OSError:
                if not os.path.isdir(loc_temp):
                    raise

        return bool_temp