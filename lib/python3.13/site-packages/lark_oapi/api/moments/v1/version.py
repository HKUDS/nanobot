from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.comment: Comment = Comment(config)
        self.post: Post = Post(config)
        self.post_statistics: PostStatistics = PostStatistics(config)
        self.reaction: Reaction = Reaction(config)
