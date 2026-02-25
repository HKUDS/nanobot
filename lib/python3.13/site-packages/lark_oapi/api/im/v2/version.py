from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.app_feed_card: AppFeedCard = AppFeedCard(config)
        self.app_feed_card_batch: AppFeedCardBatch = AppFeedCardBatch(config)
        self.biz_entity_tag_relation: BizEntityTagRelation = BizEntityTagRelation(config)
        self.chat_button: ChatButton = ChatButton(config)
        self.feed_card: FeedCard = FeedCard(config)
        self.tag: Tag = Tag(config)
        self.url_preview: UrlPreview = UrlPreview(config)
