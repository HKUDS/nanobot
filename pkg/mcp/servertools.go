package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"slices"

	"github.com/google/jsonschema-go/jsonschema"
)

type NoResponse *struct{}

// HandleCancelled processes a "notifications/cancelled" message by cancelling the
// corresponding in-flight request on the current session. Built-in MCP servers
// should call this from their OnMessage switch to avoid returning a method-not-found error.
func HandleCancelled(ctx context.Context, msg Message) {
	var payload CancelledNotification
	if len(msg.Params) > 0 {
		_ = json.Unmarshal(msg.Params, &payload)
	}
	SessionFromContext(ctx).StopAllFromRequestID(payload.RequestID, new(payload.Reason))
}

// Invoke is a generic function to handle invoking a handler with a message and payload. R should really be a pointer
// to a type, not the type itself. And a nil response will be treated as a call that does not have a response, like a
// notification handler. In such situation a response signature like (*struct{}, error) is enough. A help type
// NoResponse is just an alias to *struct{}
func Invoke[T any, R comparable](ctx context.Context, msg Message, handler func(ctx context.Context, req Message, payload T) (R, error)) {
	var payload T
	if len(msg.Params) > 0 && !bytes.Equal(msg.Params, []byte("null")) {
		if err := json.Unmarshal(msg.Params, &payload); err != nil {
			msg.SendError(ctx, err)
			return
		}
	}
	var defR R
	r, err := handler(ctx, msg, payload)
	if errors.Is(err, ErrNoResponse) {
		// no response expected, return
	} else if err != nil {
		msg.SendError(ctx, err)
	} else if _, noResponse := any(r).(NoResponse); noResponse {
		// no response expected, return
	} else if r != defR {
		err := msg.Reply(ctx, r)
		if err != nil {
			msg.SendError(ctx, err)
		}
	}
}

type ServerTools map[string]ServerTool

func (s ServerTools) Call(ctx context.Context, msg Message, payload CallToolRequest) (*CallToolResult, error) {
	tool, ok := s[payload.Name]
	if !ok {
		return nil, fmt.Errorf("unknown tool %s", payload.Name)
	}

	return tool.Invoke(ctx, msg, payload)
}

type ServerTool interface {
	Definition() Tool
	Invoke(ctx context.Context, msg Message, call CallToolRequest) (*CallToolResult, error)
}

type serverTool[In, Out any] struct {
	tool Tool
	f    func(ctx context.Context, in In) (Out, error)
}

func (s *serverTool[In, Out]) Definition() Tool {
	return s.tool
}

func (s *serverTool[In, Out]) Invoke(ctx context.Context, _ Message, call CallToolRequest) (*CallToolResult, error) {
	var in In
	if len(call.Arguments) > 0 {
		if err := JSONCoerce(call.Arguments, &in); err != nil {
			return nil, err
		}
	}

	out, err := s.f(ctx, in)
	if err != nil {
		return nil, fmt.Errorf("error invoking tool %s: %w", s.tool.Name, err)
	}

	return callResult(out, err)
}

func NewServerTools(tools ...ServerTool) ServerTools {
	if len(tools) == 0 {
		return map[string]ServerTool{}
	}

	result := make(ServerTools, len(tools))
	for _, tool := range tools {
		result[tool.Definition().Name] = tool
	}
	return result
}

func NewServerTool[In, Out any](name, description string, handler func(ctx context.Context, in In) (Out, error)) ServerTool {
	inSchema, err := jsonschema.For[In](nil)
	if err != nil {
		panic(err)
	}
	inputData, err := json.Marshal(inSchema)
	if err != nil {
		panic(err)
	}

	return &serverTool[In, Out]{
		tool: Tool{
			Name:        name,
			Description: description,
			InputSchema: inputData,
		},
		f: handler,
	}
}

func callResult(object any, err error) (*CallToolResult, error) {
	if err != nil {
		return nil, err
	}

	if _, ok := object.(Content); ok {
		// If the object is already a Content, we can return it directly
		return &CallToolResult{
			IsError: false,
			Content: []Content{object.(Content)},
		}, nil
	}
	if _, ok := object.(*Content); ok {
		// If the object is already a Content, we can return it directly
		return &CallToolResult{
			IsError: false,
			Content: []Content{*(object.(*Content))},
		}, nil
	}
	if _, ok := object.([]Content); ok {
		// If the object is already a slice of Content, we can return it directly
		return &CallToolResult{
			IsError: false,
			Content: object.([]Content),
		}, nil
	}
	if _, ok := object.(*CallToolResult); ok {
		// If the object is already a CallToolResult, we can return it directly
		return object.(*CallToolResult), nil
	}
	if res, ok := object.(*Resource); ok {
		return &CallToolResult{
			Content: []Content{
				{
					Type:        "resource_link",
					Name:        res.Name,
					Description: res.Description,
					URI:         res.URI,
					MIMEType:    res.MimeType,
				},
			},
		}, nil
	}
	if res, ok := object.(Resource); ok {
		return &CallToolResult{
			Content: []Content{
				{
					Type:        "resource_link",
					Name:        res.Name,
					Description: res.Description,
					URI:         res.URI,
					MIMEType:    res.MimeType,
				},
			},
		}, nil
	}
	if res, ok := object.(string); ok {
		return &CallToolResult{
			Content: []Content{
				{
					Type: "text",
					Text: res,
				},
			},
		}, nil
	}

	dataBytes, err := json.Marshal(object)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal thread data: %w", err)
	}

	return &CallToolResult{
		IsError:           false,
		StructuredContent: object,
		Content: []Content{
			{
				Type: "text",
				Text: string(dataBytes),
			},
		},
	}, nil
}

func (s ServerTools) List(_ context.Context, _ Message, _ ListToolsRequest) (*ListToolsResult, error) {
	// purposefully not set to nil, so that we can return an empty list
	tools := []Tool{}
	for _, key := range slices.Sorted(maps.Keys(s)) {
		tools = append(tools, s[key].Definition())
	}

	return &ListToolsResult{
		Tools: tools,
	}, nil
}

func JSONCoerce[T any](in any, out *T) error {
	switch s := any(out).(type) {
	case *string:
		if inStr, ok := in.(string); ok {
			*s = inStr
			return nil
		}
		data, err := json.Marshal(in)
		if err != nil {
			return err
		}
		*s = string(data)
		return nil
	}

	if v, ok := in.(T); ok {
		*out = v
		return nil
	}

	var data []byte
	if inBytes, ok := in.([]byte); ok {
		data = inBytes
	} else if inStr, ok := in.(string); ok {
		data = []byte(inStr)
	} else if inStrP, ok := in.(*string); ok && inStrP != nil {
		data = []byte(*inStrP)
	} else {
		var err error
		data, err = json.Marshal(in)
		if err != nil {
			return err
		}
	}
	return json.Unmarshal(data, out)
}
