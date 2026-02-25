from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.app: App = App(config)
        self.data_source: DataSource = DataSource(config)
        self.data_source_item: DataSourceItem = DataSourceItem(config)
        self.doc_wiki: DocWiki = DocWiki(config)
        self.message: Message = Message(config)
        self.schema: Schema = Schema(config)
