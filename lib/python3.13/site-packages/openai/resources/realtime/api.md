# Realtime

Types:

```python
from openai.types.realtime import (
    AudioTranscription,
    ConversationCreatedEvent,
    ConversationItem,
    ConversationItemAdded,
    ConversationItemCreateEvent,
    ConversationItemCreatedEvent,
    ConversationItemDeleteEvent,
    ConversationItemDeletedEvent,
    ConversationItemDone,
    ConversationItemInputAudioTranscriptionCompletedEvent,
    ConversationItemInputAudioTranscriptionDeltaEvent,
    ConversationItemInputAudioTranscriptionFailedEvent,
    ConversationItemInputAudioTranscriptionSegment,
    ConversationItemRetrieveEvent,
    ConversationItemTruncateEvent,
    ConversationItemTruncatedEvent,
    ConversationItemWithReference,
    InputAudioBufferAppendEvent,
    InputAudioBufferClearEvent,
    InputAudioBufferClearedEvent,
    InputAudioBufferCommitEvent,
    InputAudioBufferCommittedEvent,
    InputAudioBufferDtmfEventReceivedEvent,
    InputAudioBufferSpeechStartedEvent,
    InputAudioBufferSpeechStoppedEvent,
    InputAudioBufferTimeoutTriggered,
    LogProbProperties,
    McpListToolsCompleted,
    McpListToolsFailed,
    McpListToolsInProgress,
    NoiseReductionType,
    OutputAudioBufferClearEvent,
    RateLimitsUpdatedEvent,
    RealtimeAudioConfig,
    RealtimeAudioConfigInput,
    RealtimeAudioConfigOutput,
    RealtimeAudioFormats,
    RealtimeAudioInputTurnDetection,
    RealtimeClientEvent,
    RealtimeConversationItemAssistantMessage,
    RealtimeConversationItemFunctionCall,
    RealtimeConversationItemFunctionCallOutput,
    RealtimeConversationItemSystemMessage,
    RealtimeConversationItemUserMessage,
    RealtimeError,
    RealtimeErrorEvent,
    RealtimeFunctionTool,
    RealtimeMcpApprovalRequest,
    RealtimeMcpApprovalResponse,
    RealtimeMcpListTools,
    RealtimeMcpProtocolError,
    RealtimeMcpToolCall,
    RealtimeMcpToolExecutionError,
    RealtimeMcphttpError,
    RealtimeResponse,
    RealtimeResponseCreateAudioOutput,
    RealtimeResponseCreateMcpTool,
    RealtimeResponseCreateParams,
    RealtimeResponseStatus,
    RealtimeResponseUsage,
    RealtimeResponseUsageInputTokenDetails,
    RealtimeResponseUsageOutputTokenDetails,
    RealtimeServerEvent,
    RealtimeSession,
    RealtimeSessionCreateRequest,
    RealtimeToolChoiceConfig,
    RealtimeToolsConfig,
    RealtimeToolsConfigUnion,
    RealtimeTracingConfig,
    RealtimeTranscriptionSessionAudio,
    RealtimeTranscriptionSessionAudioInput,
    RealtimeTranscriptionSessionAudioInputTurnDetection,
    RealtimeTranscriptionSessionCreateRequest,
    RealtimeTruncation,
    RealtimeTruncationRetentionRatio,
    ResponseAudioDeltaEvent,
    ResponseAudioDoneEvent,
    ResponseAudioTranscriptDeltaEvent,
    ResponseAudioTranscriptDoneEvent,
    ResponseCancelEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreateEvent,
    ResponseCreatedEvent,
    ResponseDoneEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseMcpCallArgumentsDelta,
    ResponseMcpCallArgumentsDone,
    ResponseMcpCallCompleted,
    ResponseMcpCallFailed,
    ResponseMcpCallInProgress,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    SessionCreatedEvent,
    SessionUpdateEvent,
    SessionUpdatedEvent,
    TranscriptionSessionUpdate,
    TranscriptionSessionUpdatedEvent,
)
```

## ClientSecrets

Types:

```python
from openai.types.realtime import (
    RealtimeSessionClientSecret,
    RealtimeSessionCreateResponse,
    RealtimeTranscriptionSessionCreateResponse,
    RealtimeTranscriptionSessionTurnDetection,
    ClientSecretCreateResponse,
)
```

Methods:

- <code title="post /realtime/client_secrets">client.realtime.client_secrets.<a href="./src/openai/resources/realtime/client_secrets.py">create</a>(\*\*<a href="src/openai/types/realtime/client_secret_create_params.py">params</a>) -> <a href="./src/openai/types/realtime/client_secret_create_response.py">ClientSecretCreateResponse</a></code>

## Calls

Methods:

- <code title="post /realtime/calls">client.realtime.calls.<a href="./src/openai/resources/realtime/calls.py">create</a>(\*\*<a href="src/openai/types/realtime/call_create_params.py">params</a>) -> HttpxBinaryResponseContent</code>
- <code title="post /realtime/calls/{call_id}/accept">client.realtime.calls.<a href="./src/openai/resources/realtime/calls.py">accept</a>(call_id, \*\*<a href="src/openai/types/realtime/call_accept_params.py">params</a>) -> None</code>
- <code title="post /realtime/calls/{call_id}/hangup">client.realtime.calls.<a href="./src/openai/resources/realtime/calls.py">hangup</a>(call_id) -> None</code>
- <code title="post /realtime/calls/{call_id}/refer">client.realtime.calls.<a href="./src/openai/resources/realtime/calls.py">refer</a>(call_id, \*\*<a href="src/openai/types/realtime/call_refer_params.py">params</a>) -> None</code>
- <code title="post /realtime/calls/{call_id}/reject">client.realtime.calls.<a href="./src/openai/resources/realtime/calls.py">reject</a>(call_id, \*\*<a href="src/openai/types/realtime/call_reject_params.py">params</a>) -> None</code>
