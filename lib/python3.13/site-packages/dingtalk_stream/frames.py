import json


class Headers(object):
    CONTENT_TYPE_APPLICATION_JSON = 'application/json'

    def __init__(self):
        self.app_id = None
        self.connection_id = None
        self.content_type = None
        self.message_id = None
        self.time = None
        self.topic = None
        self.extensions = {}
        # event fields start
        self.event_born_time = None
        self.event_corp_id = None
        self.event_id = None
        self.event_type = None
        self.event_unified_app_id = None
        # event fields end

    def __str__(self):
        fields = {
            'app_id': self.app_id,
            'connection_id': self.connection_id,
            'content_type': self.content_type,
            'message_id': self.message_id,
            'time': self.time,
            'topic': self.topic,
            'extensions': self.extensions,
        }
        if self.event_id is not None:
            fields['event_born_time'] = self.event_born_time
            fields['event_id'] = self.event_id
            fields['event_corp_id'] = self.event_corp_id
            fields['event_type'] = self.event_type
            fields['event_unified_app_id'] = self.event_unified_app_id
        return 'Headers(%s)' % ', '.join(['%s=%s' % (k, v) for k, v in fields.items()])

    def to_dict(self):
        result = self.extensions.copy()
        if self.app_id is not None:
            result['appId'] = self.app_id
        if self.connection_id is not None:
            result['connectionId'] = self.connection_id
        if self.content_type is not None:
            result['contentType'] = self.content_type
        if self.message_id is not None:
            result['messageId'] = self.message_id
        if self.topic is not None:
            result['topic'] = self.topic
        if self.time is not None:
            result['time'] = str(self.time)
        return result

    @classmethod
    def from_dict(cls, d):
        headers = Headers()
        for name, value in d.items():
            if name == 'appId':
                headers.app_id = value
            elif name == 'connectionId':
                headers.connection_id = value
            elif name == 'contentType':
                headers.content_type = value
            elif name == 'messageId':
                headers.message_id = value
            elif name == 'topic':
                headers.topic = value
            elif name == 'time':
                headers.time = int(value)
            elif name == 'eventBornTime':
                headers.event_born_time = int(value)
            elif name == 'eventCorpId':
                headers.event_corp_id = value
            elif name == 'eventId':
                headers.event_id = value
            elif name == 'eventType':
                headers.event_type = value
            elif name == 'eventUnifiedAppId':
                headers.event_unified_app_id = value
            else:
                headers.extensions[name] = value
        return headers


class EventMessage(object):
    TYPE = 'EVENT'

    def __init__(self):
        self.spec_version = ''
        self.type = EventMessage.TYPE
        self.headers = Headers()
        self.data = {}
        self.extensions = {}

    def __str__(self):
        return 'EventMessage(spec_version=%s, type=%s, headers=%s, data=%s, extensions=%s)' % (
            self.spec_version,
            self.type,
            self.headers,
            self.data,
            self.extensions)

    @classmethod
    def from_dict(cls, d):
        msg = EventMessage()
        data = ''
        for name, value in d.items():
            if name == 'specVersion':
                msg.spec_version = value
            elif name == 'data':
                data = value
            elif name == 'type':
                pass
            elif name == 'headers':
                msg.headers = Headers.from_dict(value)
            else:
                msg.extensions[name] = value
        if data:
            msg.data = json.loads(data)
        return msg

class CallbackMessage(object):
    TYPE = 'CALLBACK'

    def __init__(self):
        self.spec_version = ''
        self.type = CallbackMessage.TYPE
        self.headers = Headers()
        self.data = {}
        self.extensions = {}

    def __str__(self):
        return 'CallbackMessage(spec_version=%s, type=%s, headers=%s, data=%s, extensions=%s)' % (
            self.spec_version,
            self.type,
            self.headers,
            self.data,
            self.extensions)

    @classmethod
    def from_dict(cls, d):
        msg = CallbackMessage()
        data = ''
        for name, value in d.items():
            if name == 'specVersion':
                msg.spec_version = value
            elif name == 'data':
                data = value
            elif name == 'type':
                pass
            elif name == 'headers':
                msg.headers = Headers.from_dict(value)
            else:
                msg.extensions[name] = value
        if data:
            msg.data = json.loads(data)
        return msg

class SystemMessage(object):
    TYPE = 'SYSTEM'
    TOPIC_DISCONNECT = 'disconnect'

    def __init__(self):
        self.spec_version = ''
        self.type = SystemMessage.TYPE
        self.headers = Headers()
        self.data = {}
        self.extensions = {}

        @classmethod
        def from_dict(cls, d):
            msg = SystemMessage()
            data = ''
            for name, value in d.items():
                if name == 'specVersion':
                    msg.spec_version = value
                elif name == 'data':
                    data = value
                elif name == 'type':
                    pass
                elif name == 'headers':
                    msg.headers = Headers.from_dict(value)
                else:
                    msg.extensions[name] = value
            if data:
                msg.data = json.loads(data)
            return msg

    def __str__(self):
        return 'SystemMessage(spec_version=%s, type=%s, headers=%s, data=%s, extensions=%s)' % (
            self.spec_version,
            self.type,
            self.headers,
            self.data,
            self.extensions,
        )

    @classmethod
    def from_dict(cls, d):
        msg = SystemMessage()
        data = ''
        for name, value in d.items():
            if name == 'specVersion':
                msg.spec_version = value
            elif name == 'data':
                data = value
            elif name == 'type':
                pass
            elif name == 'headers':
                msg.headers = Headers.from_dict(value)
            else:
                msg.extensions[name] = value
        if data:
            msg.data = json.loads(data)
        return msg


class AckMessage(object):
    STATUS_OK = 200
    STATUS_BAD_REQUEST = 400
    STATUS_NOT_IMPLEMENT = 404
    STATUS_SYSTEM_EXCEPTION = 500

    def __init__(self):
        self.code = AckMessage.STATUS_OK
        self.headers = Headers()
        self.message = ''
        self.data = {}

    def to_dict(self):
        return {
            'code': self.code,
            'headers': self.headers.to_dict(),
            'message': self.message,
            'data': json.dumps(self.data),
        }
