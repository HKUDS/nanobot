from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.export_task: ExportTask = ExportTask(config)
        self.file: File = File(config)
        self.file_comment: FileComment = FileComment(config)
        self.file_comment_reply: FileCommentReply = FileCommentReply(config)
        self.file_statistics: FileStatistics = FileStatistics(config)
        self.file_subscription: FileSubscription = FileSubscription(config)
        self.file_version: FileVersion = FileVersion(config)
        self.file_view_record: FileViewRecord = FileViewRecord(config)
        self.import_task: ImportTask = ImportTask(config)
        self.media: Media = Media(config)
        self.meta: Meta = Meta(config)
        self.permission_member: PermissionMember = PermissionMember(config)
        self.permission_public: PermissionPublic = PermissionPublic(config)
        self.permission_public_password: PermissionPublicPassword = PermissionPublicPassword(config)
