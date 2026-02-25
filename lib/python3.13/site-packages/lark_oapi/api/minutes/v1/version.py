from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.minute: Minute = Minute(config)
        self.minute_media: MinuteMedia = MinuteMedia(config)
        self.minute_statistics: MinuteStatistics = MinuteStatistics(config)
        self.minute_transcript: MinuteTranscript = MinuteTranscript(config)
