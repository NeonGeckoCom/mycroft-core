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
from mycroft.util.log import LOG
import websocket
# from socketio import SocketIO
from socketIO_client import SocketIO

class ChatSocket(SocketIO):
    def __init__(self):
        self.running = True
        self.sleeping = False
        LOG.info("0.1 >>> Connecting to Chat Server!")
        self.socketio = SocketIO('https://3333.us', 8888,
                            # verify='server.crt',
                            # cert=('client.crt', 'client.key'),
                            proxies={'http': 'https://3333.us:8888'})


# def main():
#     # import logging
#     # logging.getLogger('requests').setLevel(logging.WARNING)
#     # logging.basicConfig(level=logging.DEBUG)
#
#     LOG.info("0.1 >>> Connecting to Chat Server!")
#
#     # socketIO = SocketIO(
#     #     'https://64.34.187.223', 8888,
#     #     # params={'q': 'qqq'},
#     #     # headers={'Authorization': 'Basic ' + b64encode('username:password')},
#     #     # cookies={'a': 'aaa'},
#     #     proxies={'https': 'https://3333.us:8888'})
#
#     global socketio
#
#     socketio = SocketIO('https://3333.us', 8888,
#                         # verify='server.crt',
#                         # cert=('client.crt', 'client.key'),
#                     proxies={'http': 'https://3333.us:8888'})
#     # socketIO = SocketIO('3333.us', 8888, LoggingNamespace)
#     LOG.info("1 >>> Connected to Chat Server!")
#     # socketIO.emit('from mycroft', 'test One')
#     LOG.info("2 >>> Connected to Chat Server!")
#     # socketIO.
#     # socketIO.disconnect()
#     # socketIO.wait(seconds=1)
#
#
#     # Node.js connection
#     # sio = SocketIO()
#     # sio.send("log_event", "Chat socket.io connected!")
#
#     # global csws     # chat server web socket connection
#     #
#     # try:
#     #     websocket.enableTrace(True)
#     #     csws = websocket.WebSocketApp("tcp://3333.us:8888",
#     #                                   on_message=csws_on_message,
#     #                                   on_error=csws_on_error,
#     #                                   on_close=csws_on_close)
#     #
#     #     csws.on_open = csws_on_open
#     #
#     #     csws.run_forever()
#     #
#     # except Exception as e:
#     #     LOG.exception(e)
#     #     sys.exit()
#
# # """Creates a python socket client that will interact with javascript."""
# # import socket
#
# # socket_path = '"ws://3333.us:8888"'
# # # connect to the unix local socket with a stream type
# # client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
# # client.connect(socket_path)
# # # send an initial message (as bytes)
# # client.send(b'python connected')
# # # start a loop
# # while True:
# #     # wait for a response and decode it from bytes
# #     msg = client.recv(2048).decode('utf-8')
# #     LOG.info(msg)
# #     # print(msg)
# #     if msg == 'hi':
# #         client.send(b'hello')
# #     elif msg == 'end':
# #         # exit the loop
# #         break
# #
# # # close the connection
# # client.close()
#
# if __name__ == "__main__":
#     main()
