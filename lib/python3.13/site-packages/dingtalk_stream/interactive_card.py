# -*- coding:utf-8 -*-

import copy, uuid

"""
这里是卡片模板库，提供一些必要的卡片组件组合。
INTERACTIVE_CARD_JSON_SAMPLE_1 极简卡片组合：title-text-image-button
INTERACTIVE_CARD_JSON_SAMPLE_2 较丰富的组件卡片，title-text-image-section-button
INTERACTIVE_CARD_JSON_SAMPLE_3 较丰富的组件卡片，title-image-markdown-button
高阶需求请至卡片搭建平台：https://card.dingtalk.com/card-builder
"""


'''
实用卡片模板：多行文本
'''
INTERACTIVE_CARD_JSON_SAMPLE_MULTI_TEXT_LINE = {
    "config": {
        "autoLayout": True,
        "enableForward": True
    },
    "header": {
        "title": {
            "type": "text",
            "text": "钉钉卡片"
        },
        "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"
    },
    "contents": [
        {
            "type": "markdown",
            "text": "钉钉正在为各行各业提供专业解决方案，沉淀钉钉1900万企业组织核心业务场景，提供专属钉钉、教育、医疗、新零售等多行业多维度的解决方案。",
            "id": "markdown_1686281949314"
        },
        {
            "type": "divider",
            "id": "divider_1686281949314"
        }
    ]
}


def generate_multi_text_line_card_data(title: str, logo: str, texts: [str]) -> dict:
    card_data = copy.deepcopy(INTERACTIVE_CARD_JSON_SAMPLE_MULTI_TEXT_LINE)

    if title != "":
        card_data["header"]["title"]["text"] = title

    if logo != "":
        card_data["header"]["logo"] = logo

    card_data["contents"] = []
    for text in texts:
        text_line = {
            "type": "markdown",
            "text": text,
            "id": "text_" + str(uuid.uuid1())
        }
        divider_line = {
            "type": "divider",
            "id": "divider_" + str(uuid.uuid1())
        }
        card_data["contents"].append(text_line)
        card_data["contents"].append(divider_line)

    return card_data


'''
实用卡片模板，多行文本+多图组合
'''
INTERACTIVE_CARD_JSON_SAMPLE_MULTI_TEXT_IMAGE = {
    "config": {
        "autoLayout": True,
        "enableForward": True
    },
    "header": {
        "title": {
            "type": "text",
            "text": "钉钉卡片"
        },
        "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"
    },
    "contents": [
        {
            "type": "markdown",
            "text": "钉钉正在为各行各业提供专业解决方案，沉淀钉钉1900万企业组织核心业务场景，提供专属钉钉、教育、医疗、新零售等多行业多维度的解决方案。",
            "id": "markdown_1686281949314"
        },
        {
            "type": "divider",
            "id": "divider_1686281949314"
        },
        {
            "type": "imageList",
            "images": [
                "@lADPDe7s2ySi18PNA6XNBXg",
                "@lADPDf0i1beuNF3NAxTNBXg",
                "@lADPDe7s2ySRnIvNA6fNBXg"
            ],
            "id": "imageList_1686283179480"
        }
    ]
}


def generate_multi_text_image_card_data(title: str, logo: str, texts: [str], images: [str]) -> dict:
    card_data = copy.deepcopy(INTERACTIVE_CARD_JSON_SAMPLE_MULTI_TEXT_IMAGE)

    if title != "":
        card_data["header"]["title"]["text"] = title

    if logo != "":
        card_data["header"]["logo"] = logo

    card_data["contents"] = []
    for text in texts:
        text_line = {
            "type": "markdown",
            "text": text,
            "id": "text_" + str(uuid.uuid1())
        }
        divider_line = {
            "type": "divider",
            "id": "divider_" + str(uuid.uuid1())
        }
        card_data["contents"].append(text_line)
        card_data["contents"].append(divider_line)

    image_list = {
        "type": "imageList",
        "images": images,
        "id": "imageList_" + str(uuid.uuid1())
    }
    card_data["contents"].append(image_list)

    return card_data


'''
极简卡片组合：title-text-image-button
'''
INTERACTIVE_CARD_JSON_SAMPLE_1 = {
    "config": {
        "autoLayout": True,
        "enableForward": True
    },
    "header": {
        "title": {
            "type": "text",
            "text": "钉钉卡片"
        },
        "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"
    },
    "contents": [
        {
            "type": "markdown",
            "text": "钉钉，让进步发生！\n 更新时间：2023-06-06 12:00",
            "id": "text_1686025745169"
        },
        {
            "type": "image",
            "image": "@lADPDetfXH_Pn3HNAbrNBDg",
            "id": "image_1686025745169"
        },
        {
            "type": "action",
            "actions": [
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "打开链接",
                        "id": "text_1686025745289"
                    },
                    "actionType": "openLink",
                    "url": {
                        "all": "https://www.dingtalk.com"
                    },
                    "status": "primary",
                    "id": "button_1646816888247"
                },
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "回传请求",
                        "id": "text_1686025745208"
                    },
                    "actionType": "request",
                    "status": "primary",
                    "id": "button_1646816888257"
                }
            ],
            "id": "action_1686025745169"
        }
    ]
}

'''
较丰富的组件卡片，title-text-image-section-button
'''
INTERACTIVE_CARD_JSON_SAMPLE_2 = {
    "config": {
        "autoLayout": True,
        "enableForward": True
    },
    "header": {
        "title": {
            "type": "text",
            "text": "钉钉卡片"
        },
        "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"
    },
    "contents": [
        {
            "type": "markdown",
            "text": "钉钉正在为各行各业提供专业解决方案，沉淀钉钉1900万企业组织核心业务场景，提供专属钉钉、教育、医疗、新零售等多行业多维度的解决方案。",
            "id": "text_1686025745169"
        },
        {
            "type": "image",
            "image": "@lADPDetfXH_Pn3HNAbrNBDg",
            "id": "image_1686025745169"
        },
        {
            "type": "divider",
            "id": "divider_1686025745169"
        },
        {
            "type": "section",
            "fields": {
                "list": [
                    {
                        "type": "text",
                        "text": "钉钉发起“C10圆桌派”，旨在邀请各行各业的CIO、CTO等，面对面深入交流数字化建设心得，总结行业…",
                        "id": "text_1686025745205"
                    },
                    {
                        "type": "text",
                        "text": "在后疫情时期，数字化跃升为时代命题之一，混合办公及云上创新逐渐普及，数字化已成为企业发展的必答…",
                        "id": "text_1686025745174"
                    }
                ]
            },
            "extra": {
                "type": "button",
                "label": {
                    "type": "text",
                    "text": "查看详情",
                    "id": "text_1686025745191"
                },
                "actionType": "openLink",
                "url": {
                    "all": "https://alidocs.dingtalk.com/i/p/nb9XJlvOKbAyDGyA/docs/nb9XJo9ogo27lmyA?spm=a217n7.14136887.0.0.499d573fCVWe7p"
                },
                "status": "primary",
                "id": "button_1646816886531"
            },
            "id": "section_1686025745169"
        },
        {
            "type": "action",
            "actions": [
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "打开链接",
                        "id": "text_1686025745289"
                    },
                    "actionType": "openLink",
                    "url": {
                        "all": "https://www.dingtalk.com"
                    },
                    "status": "primary",
                    "id": "button_1646816888247"
                },
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "回传请求",
                        "id": "text_1686025745208"
                    },
                    "actionType": "request",
                    "status": "primary",
                    "id": "button_1646816888257"
                },
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "次级按钮",
                        "id": "text_1686025745206"
                    },
                    "actionType": "openLink",
                    "url": {
                        "all": "https://www.dingtalk.com"
                    },
                    "status": "normal",
                    "id": "button_1646816888277"
                },
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "警示按钮",
                        "id": "text_1686025745195"
                    },
                    "actionType": "openLink",
                    "url": {
                        "all": "https://www.dingtalk.com"
                    },
                    "status": "warning",
                    "id": "button_1646816888287"
                }
            ],
            "id": "action_1686025745169"
        }
    ]
}

'''
较丰富的组件卡片，title-image-markdown-button
'''
INTERACTIVE_CARD_JSON_SAMPLE_3 = {
    "config": {
        "autoLayout": True,
        "enableForward": True
    },
    "header": {
        "title": {
            "type": "text",
            "text": "钉钉小技巧"
        },
        "logo": "@lALPDefR3hjhflFAQA"
    },
    "contents": [
        {
            "type": "image",
            "image": "@lALPDsCJC34CVxzNAYTNArA",
            "id": "image_1686034081551"
        },
        {
            "type": "markdown",
            "text": "🎉 **四招教你玩转钉钉项目**",
            "id": "markdown_1686034081551"
        },
        {
            "type": "markdown",
            "text": "一、创建项目群，重要事项放项目",
            "id": "markdown_1686034081584"
        },
        {
            "type": "markdown",
            "text": "😭  群内信息太碎片？任务交办难跟踪？协作边界很模糊？\n👉  试试创建项目群，把重要事项放在项目内跟踪，可以事半功倍！",
            "id": "markdown_1686034081625"
        },
        {
            "type": "markdown",
            "text": "<font size=12 color=common_level3_base_color>更多精彩内容请查看详情…</font>",
            "id": "markdown_1686034081660"
        },
        {
            "type": "action",
            "actions": [
                {
                    "type": "button",
                    "label": {
                        "type": "text",
                        "text": "查看详情",
                        "id": "text_1686034081551"
                    },
                    "actionType": "openLink",
                    "url": {
                        "all": "https://www.dingtalk.com"
                    },
                    "status": "normal",
                    "id": "button_1647166782413"
                }
            ],
            "id": "action_1686034081551"
        }
    ]
}
