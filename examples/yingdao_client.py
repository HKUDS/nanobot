"""
影刀RPA端调用示例

将此代码添加到影刀RPA的Python模块中，用于连接nanobot的影刀通道。

使用方法：
1. 在影刀RPA中创建一个Python模块
2. 复制此代码到模块中
3. 调用 send_message 函数发送消息
"""

import json
import queue
import threading
import time
import requests


class NanobotClient:
    """
    nanobot 影刀通道客户端

    用于连接nanobot并发送/接收消息
    """

    def __init__(self, base_url: str = "http://localhost:18791"):
        """
        初始化客户端

        Args:
            base_url: nanobot服务地址 (默认 http://localhost:18791)
        """
        self.base_url = base_url.rstrip("/")
        self.session_id = "default"

    def send_message(
        self,
        content: str,
        sender_id: str = "yingdao_user",
        chat_id: str = None,
        on_progress=None,
        on_final=None,
        timeout: int = 300,
    ):
        """
        发送消息到nanobot并获取回复

        Args:
            content: 消息内容
            sender_id: 发送者ID
            chat_id: 会话ID (可选，默认与sender_id相同)
            on_progress: 进度回调函数 (接收进度消息，如思考过程)
            on_final: 最终消息回调函数 (接收最终回复)
            timeout: 超时时间(秒)

        Returns:
            完整的回复内容字符串
        """
        chat_id = chat_id or sender_id

        url = f"{self.base_url}/message"
        payload = {
            "sender_id": sender_id,
            "chat_id": chat_id,
            "content": content,
        }

        full_response = []
        final_response = []

        try:
            with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
                if resp.status_code != 200:
                    return f"Error: {resp.status_code} - {resp.text}"

                for line in resp.iter_lines():
                    if not line:
                        continue

                    line = line.decode("utf-8")
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type", "")
                    msg_content = data.get("content", "")
                    msg_media = data.get("metadata", {}).get("media", [])

                    if msg_type == "progress":
                        full_response.append(msg_content)
                        if on_progress:
                            on_progress(msg_content, msg_media)

                    elif msg_type == "final":
                        full_response.append(msg_content)
                        final_response.append(msg_content)
                        if on_final:
                            on_final(msg_content, msg_media)

                    elif msg_type == "done":
                        break

                    elif msg_type == "error":
                        return f"Error: {msg_content}"

            return "".join(final_response)

        except requests.exceptions.Timeout:
            return "Error: Request timeout"
        except requests.exceptions.ConnectionError:
            return "Error: Cannot connect to nanobot"
        except Exception as e:
            return f"Error: {str(e)}"


def main(args=None):
    """
    影刀RPA主函数入口

    使用示例：
    - 在影刀RPA中配置输入参数: message_content
    - 调用 send_message 发送消息
    - 获取回复后发送到微信
    """
    client = NanobotClient(base_url="http://localhost:18791")

    message_content = args.get("message_content", "你好") if args else "你好"

    print(f"[nanobot] 发送消息: {message_content}")

    def handle_progress(msg, media):
        print(f"[nanobot 思考中] {msg}")

    def handle_final(msg, media):
        print(f"[nanobot 回复] {msg}")
        if media:
            print(f"[nanobot 收到文件] {media}")
            for file_path in media:
                print(f"  文件路径: {file_path}")

    response = client.send_message(
        content=message_content,
        sender_id="wechat_user_001",
        on_progress=handle_progress,
        on_final=handle_final,
    )

    print(f"[nanobot] 最终回复: {response}")

    return response


if __name__ == "__main__":
    result = main({"message_content": "你好，请介绍一下自己"})
    print(f"\n最终结果: {result}")
