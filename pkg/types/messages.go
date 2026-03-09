package types

func ConsolidateTools(allMessages []Message) (result []Message) {
	tools := map[string]struct {
		msgIndex  int
		itemIndex int
	}{}
	for _, msg := range allMessages {
		var processedItems []CompletionItem
		for _, output := range msg.Items {
			if output.ToolCallResult != nil && output.ToolCall == nil {
				if i, ok := tools[output.ToolCallResult.CallID]; ok {
					targetMsg := msg
					if len(result) > i.msgIndex {
						targetMsg = result[i.msgIndex]
					}
					targetMsg.Items[i.itemIndex].ToolCallResult = output.ToolCallResult
					continue
				}
			} else if output.ToolCall != nil && output.ToolCallResult == nil {
				x := tools[output.ToolCall.CallID]
				x.msgIndex = len(result)
				x.itemIndex = len(processedItems)
				tools[output.ToolCall.CallID] = x
			}
			processedItems = append(processedItems, output)
		}
		msg.Items = processedItems
		if len(msg.Items) > 0 {
			result = append(result, msg)
		}
	}

	return
}
