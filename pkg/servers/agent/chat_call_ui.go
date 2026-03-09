package agent

import (
	"context"
	"fmt"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
)

func (c chatCall) inlineAttachments(ctx context.Context, attachments []any) ([]any, error) {
	newAttachments := make([]any, 0, len(attachments))

	messages, err := GetMessages(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get messages: %w", err)
	}

attachmentsLoop:
	for i, attachment := range attachments {
		newAttachments = append(newAttachments, attachment)
		data, ok := attachment.(map[string]any)
		if !ok {
			continue
		}

		uri, ok := data["url"].(string)
		if !ok {
			continue
		}

		// Keep file attachments as file:/// references. The model receives a hidden
		// instruction message about these paths and uses the read tool as needed.
		if strings.HasPrefix(uri, "file:///") {
			continue
		}

		if strings.HasPrefix(uri, "data:") || strings.HasPrefix(uri, "http://") || strings.HasPrefix(uri, "https://") {
			continue
		}

		for mi := len(messages) - 1; mi >= 0; mi-- {
			for j := len(messages[mi].Items) - 1; j >= 0; j-- {
				item := messages[mi].Items[j]
				if item.ToolCallResult != nil {
					for _, content := range item.ToolCallResult.Output.Content {
						if content.Resource != nil && content.Resource.URI == uri {
							// Drop the attachment from the list
							newAttachments = newAttachments[:i]
							newAttachments = append(newAttachments, map[string]any{
								"url": content.Resource.ToDataURI(),
							})
							continue attachmentsLoop
						}
					}
				}
			}
		}

		clientName := types.CurrentAgent(ctx)

		client, err := c.s.runtime.GetClient(ctx, clientName)
		if err != nil {
			return nil, err
		}

		// Drop the attachment from the list
		newAttachments = newAttachments[:i]

		resource, err := client.ReadResource(ctx, uri)
		if err != nil {
			return nil, err
		}

		for _, content := range resource.Contents {
			dataURI := content.ToDataURI()
			attachmentData := map[string]any{
				"url": dataURI,
			}
			if content.Name != "" {
				attachmentData["name"] = content.Name
			}

			newAttachments = append(newAttachments, attachmentData)
		}
	}

	return newAttachments, nil
}

func (s *Server) describeSession(ctx context.Context, args any) {
	var description string

	session := mcp.SessionFromContext(ctx)
	session = session.Parent
	session.Get(types.DescriptionSessionKey, &description)
	if description == "" && s.agentName != "nanobot.summary" {
		go func() {
			// TODO - the fmt.sprintf creates a message that looks like this:
			// Generate a short title for the a thread that starts with the following user message(s): map[attachments:[] prompt:connect to gmail mcp and list my inbox emails]
			// We can be better about that, but this is working and good enough
			ret, err := s.runtime.Call(session.Context(), "nanobot.summary", "nanobot.summary",
				fmt.Sprintf("Generate a short title for a cht thread that starts with the following user message(s): %s. "+
					"ONLY RESPOND WITH THE TITLE AND NOTHING ELSE. Your response will be directly used to title the thread.", args))
			if err != nil {
				return
			}
			for _, content := range ret.Content {
				if content.Type == "text" {
					description = content.Text
					session.Set(types.DescriptionSessionKey, description)
					break
				}
			}
		}()
	}
}
