# Conversations

Types:

```python
from openai.types.conversations import (
    ComputerScreenshotContent,
    Conversation,
    ConversationDeleted,
    ConversationDeletedResource,
    Message,
    SummaryTextContent,
    TextContent,
    InputTextContent,
    OutputTextContent,
    RefusalContent,
    InputImageContent,
    InputFileContent,
)
```

Methods:

- <code title="post /conversations">client.conversations.<a href="./src/openai/resources/conversations/conversations.py">create</a>(\*\*<a href="src/openai/types/conversations/conversation_create_params.py">params</a>) -> <a href="./src/openai/types/conversations/conversation.py">Conversation</a></code>
- <code title="get /conversations/{conversation_id}">client.conversations.<a href="./src/openai/resources/conversations/conversations.py">retrieve</a>(conversation_id) -> <a href="./src/openai/types/conversations/conversation.py">Conversation</a></code>
- <code title="post /conversations/{conversation_id}">client.conversations.<a href="./src/openai/resources/conversations/conversations.py">update</a>(conversation_id, \*\*<a href="src/openai/types/conversations/conversation_update_params.py">params</a>) -> <a href="./src/openai/types/conversations/conversation.py">Conversation</a></code>
- <code title="delete /conversations/{conversation_id}">client.conversations.<a href="./src/openai/resources/conversations/conversations.py">delete</a>(conversation_id) -> <a href="./src/openai/types/conversations/conversation_deleted_resource.py">ConversationDeletedResource</a></code>

## Items

Types:

```python
from openai.types.conversations import ConversationItem, ConversationItemList
```

Methods:

- <code title="post /conversations/{conversation_id}/items">client.conversations.items.<a href="./src/openai/resources/conversations/items.py">create</a>(conversation_id, \*\*<a href="src/openai/types/conversations/item_create_params.py">params</a>) -> <a href="./src/openai/types/conversations/conversation_item_list.py">ConversationItemList</a></code>
- <code title="get /conversations/{conversation_id}/items/{item_id}">client.conversations.items.<a href="./src/openai/resources/conversations/items.py">retrieve</a>(item_id, \*, conversation_id, \*\*<a href="src/openai/types/conversations/item_retrieve_params.py">params</a>) -> <a href="./src/openai/types/conversations/conversation_item.py">ConversationItem</a></code>
- <code title="get /conversations/{conversation_id}/items">client.conversations.items.<a href="./src/openai/resources/conversations/items.py">list</a>(conversation_id, \*\*<a href="src/openai/types/conversations/item_list_params.py">params</a>) -> <a href="./src/openai/types/conversations/conversation_item.py">SyncConversationCursorPage[ConversationItem]</a></code>
- <code title="delete /conversations/{conversation_id}/items/{item_id}">client.conversations.items.<a href="./src/openai/resources/conversations/items.py">delete</a>(item_id, \*, conversation_id) -> <a href="./src/openai/types/conversations/conversation.py">Conversation</a></code>
