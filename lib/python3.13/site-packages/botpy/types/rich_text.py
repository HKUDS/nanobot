from typing import TypedDict, Literal, List

# 1：帖子 2：评论 3：回复
AuditType = Literal[1, 2, 3]
# 1：普通文本 2：at信息 3：url信息 4：表情 5：#子频道 10：视频 11：图片
RichType = Literal[1, 2, 3, 4, 5, 10, 11]
# 1：at特定的人 2：at角色组所有人 3：at频道所有人
AtType = Literal[1, 2, 3]
# 1：文本 2：图片 3：视频 4：url
ElemType = Literal[1, 2, 3, 4]
# 0：左对齐 1：居中 2：右对齐
Alignment = Literal[0, 1, 2]


class ParagraphProps(TypedDict):
    alignment: Alignment


class URLElem(TypedDict):
    url: str
    desc: str


class ImageElem(TypedDict):
    third_url: str
    width_percent: float


class PlatImage(TypedDict):
    url: str
    width: int
    height: int
    image_id: str


class VideoElem(TypedDict):
    third_url: str


class PlatVideo(TypedDict):
    url: str
    width: int
    height: int
    video_id: str
    duration: int
    cover: PlatImage


class TextProps(TypedDict):
    font_bold: bool
    italic: bool
    underline: bool


class TextElem(TypedDict):
    text: str
    props: TextProps


class Elem(TypedDict):
    text: TextElem
    image: ImageElem
    video: VideoElem
    url: URLElem
    type: ElemType


class Paragraph(TypedDict):
    elems: List[Elem]
    props: ParagraphProps


class RichText(TypedDict):
    paragraphs: Paragraph


class ChannelInfo(TypedDict):
    channel_id: int
    channel_name: str


class EmojiInfo(TypedDict):
    id: str
    type: str
    name: str
    url: str


class URLInfo(TypedDict):
    url: str
    display_text: str


class AtGuildInfo(TypedDict):
    guild_id: str
    guild_name: str


class AtRoleInfo(TypedDict):
    role_id: int
    name: str
    color: int


class AtUserInfo(TypedDict):
    id: str
    nick: str


class AtInfo(TypedDict):
    type: AuditType
    user_info: AtUserInfo
    role_info: AtRoleInfo
    guild_info: AtGuildInfo


class TextInfo(TypedDict):
    text: str


class RichObject(TypedDict):
    type: RichType
    text_info: TextInfo
    at_info: AtInfo
    url_info: URLInfo
    emoji_info: EmojiInfo
    channel_info: ChannelInfo

