#!/usr/bin/env python3

import asyncio
import asyncio.exceptions
import json
import logging
import platform
import time
import requests
import socket
import websockets

from urllib.parse import quote_plus

from .credential import Credential
from .handlers import CallbackHandler
from .handlers import EventHandler
from .handlers import SystemHandler
from .frames import SystemMessage
from .frames import EventMessage
from .frames import CallbackMessage
from .log import setup_default_logger
from .utils import DINGTALK_OPENAPI_ENDPOINT
from .version import VERSION_STRING


class DingTalkStreamClient(object):
    OPEN_CONNECTION_API = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/gateway/connections/open'
    TAG_DISCONNECT = 'disconnect'

    def __init__(self, credential: Credential, logger: logging.Logger = None):
        self.credential: Credential = credential
        self.event_handler: EventHandler = EventHandler()
        self.callback_handler_map = {}
        self.system_handler: SystemHandler = SystemHandler()
        self.websocket = None  # create websocket client after connected
        self.logger: logging.Logger = logger if logger else setup_default_logger('dingtalk_stream.client')
        self._pre_started = False
        self._is_event_required = False
        self._access_token = {}

    def register_all_event_handler(self, handler: EventHandler):
        handler.dingtalk_client = self
        self.event_handler = handler
        self._is_event_required = True

    def register_callback_handler(self, topic, handler: CallbackHandler):
        handler.dingtalk_client = self
        self.callback_handler_map[topic] = handler

    def pre_start(self):
        if self._pre_started:
            return
        self._pre_started = True
        self.event_handler.pre_start()
        self.system_handler.pre_start()
        for handler in self.callback_handler_map.values():
            handler.pre_start()

    async def start(self):
        self.pre_start()

        while True:
            try:
                connection = self.open_connection()

                if not connection:
                    self.logger.error('open connection failed')
                    await asyncio.sleep(10)
                    continue
                self.logger.info('endpoint is %s', connection)

                uri = f'{connection["endpoint"]}?ticket={quote_plus(connection["ticket"])}'
                async with websockets.connect(uri) as websocket:
                    self.websocket = websocket
                    asyncio.create_task(self.keepalive(websocket))
                    async for raw_message in websocket:
                        json_message = json.loads(raw_message)
                        asyncio.create_task(self.background_task(json_message))
            except KeyboardInterrupt as e:
                break
            except (asyncio.exceptions.CancelledError,
                    websockets.exceptions.ConnectionClosedError) as e:
                self.logger.error('[start] network exception, error=%s', e)
                await asyncio.sleep(10)
                continue
            except Exception as e:
                await asyncio.sleep(3)
                self.logger.exception('unknown exception', e)
                continue
            finally:
                pass

    async def keepalive(self, ws, ping_interval=60):
        while True:
            await asyncio.sleep(ping_interval)
            try:
                await ws.ping()
            except websockets.exceptions.ConnectionClosed:
                break

    async def background_task(self, json_message):
        try:
            route_result = await self.route_message(json_message)
            if route_result == DingTalkStreamClient.TAG_DISCONNECT:
                await self.websocket.close()
        except Exception as e:
            self.logger.error(f"error processing message: {e}")

    async def route_message(self, json_message):
        result = ''
        msg_type = json_message.get('type', '')
        ack = None
        if msg_type == SystemMessage.TYPE:
            msg = SystemMessage.from_dict(json_message)
            ack = await self.system_handler.raw_process(msg)
            if msg.headers.topic == SystemMessage.TOPIC_DISCONNECT:
                result = DingTalkStreamClient.TAG_DISCONNECT
                self.logger.info("received disconnect topic=%s, message=%s", msg.headers.topic, json_message)
            else:
                self.logger.warning("unknown message topic, topic=%s, message=%s", msg.headers.topic, json_message)
        elif msg_type == EventMessage.TYPE:
            msg = EventMessage.from_dict(json_message)
            ack = await self.event_handler.raw_process(msg)
        elif msg_type == CallbackMessage.TYPE:
            msg = CallbackMessage.from_dict(json_message)
            handler = self.callback_handler_map.get(msg.headers.topic)
            if handler:
                ack = await handler.raw_process(msg)
            else:
                self.logger.warning("unknown callback message topic, topic=%s, message=%s", msg.headers.topic,
                                    json_message)
        else:
            self.logger.warning('unknown message, content=%s', json_message)
        if ack:
            await self.websocket.send(json.dumps(ack.to_dict()))
        return result

    def start_forever(self):
        while True:
            try:
                asyncio.run(self.start())
            except KeyboardInterrupt as e:
                break
            finally:
                time.sleep(3)

    def open_connection(self):
        self.logger.info('open connection, url=%s' % DingTalkStreamClient.OPEN_CONNECTION_API)
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': ('DingTalkStream/1.0 SDK/%s Python/%s '
                           '(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
                           ) % (VERSION_STRING, platform.python_version()),
        }
        topics = []
        if self._is_event_required:
            topics.append({'type': 'EVENT', 'topic': '*'})
        for topic in self.callback_handler_map.keys():
            topics.append({'type': 'CALLBACK', 'topic': topic})
        request_body = json.dumps({
            'clientId': self.credential.client_id,
            'clientSecret': self.credential.client_secret,
            'subscriptions': topics,
            'ua': 'dingtalk-sdk-python/v%s-union' % VERSION_STRING,
            'localIp': self.get_host_ip()
        }).encode('utf-8')

        try:
            response_text = ''
            response = requests.post(DingTalkStreamClient.OPEN_CONNECTION_API,
                                     headers=request_headers,
                                     data=request_body)
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'open connection failed, error={e}, response.text={response_text}')
            return None
        return response.json()

    def get_host_ip(self):
        """
        查询本机ip地址
        :return: ip
        """
        ip = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
            return ip

    def reset_access_token(self):
        """ reset token if open api return 401 """
        self._access_token = {}

    def get_access_token(self):
        now = int(time.time())
        if self._access_token and now < self._access_token['expireTime']:
            return self._access_token['accessToken']

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        values = {
            'appKey': self.credential.client_id,
            'appSecret': self.credential.client_secret,
        }
        try:
            url = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/oauth2/accessToken'
            response_text = ''
            response = requests.post(url,
                                     headers=request_headers,
                                     data=json.dumps(values))
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'get dingtalk access token failed, error={e}, response.text={response_text}')
            return None

        result = response.json()
        result['expireTime'] = int(time.time()) + result['expireIn'] - (5 * 60)  # reserve 5min buffer time
        self._access_token = result
        return self._access_token['accessToken']

    def upload_to_dingtalk(self, image_content, filetype='image', filename='image.png', mimetype='image/png'):
        access_token = self.get_access_token()
        if not access_token:
            self.logger.error('upload_to_dingtalk failed, cannot get dingtalk access token')
            return None
        files = {
            'media': (filename, image_content, mimetype),
        }
        values = {
            'type': filetype,
        }
        upload_url = f'https://oapi.dingtalk.com/media/upload?access_token={quote_plus(access_token)}'
        try:
            response_text = ''
            response = requests.post(upload_url, data=values, files=files)
            response_text = response.text
            if response.status_code == 401:
                self.reset_access_token()

            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'upload to dingtalk failed, error={e}, response.text={response_text}')
            return None
        if 'media_id' not in response.json():
            self.logger.error('upload to dingtalk failed, error response is %s', response.json())
            raise Exception('upload failed, error=%s' % response.json())
        return response.json()['media_id']
