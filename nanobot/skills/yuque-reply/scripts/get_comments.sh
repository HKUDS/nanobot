#!/bin/bash
# 获取语雀文章评论列表
# Usage: bash get_comments.sh

agent-browser eval 'var items = document.querySelectorAll("[class*=rootCommentFloorListItem]"); Array.from(items).map(function(item, i) { var name = item.querySelector("[class*=name_]"); var content = item.querySelector("[class*=content_]"); var time = item.querySelector("[class*=time_]"); return i + ". " + (name ? name.textContent : "?") + " (" + (time ? time.textContent : "") + "): " + (content ? content.textContent.substring(0, 100) : ""); }).join("\n")'
