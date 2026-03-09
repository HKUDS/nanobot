package responses

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/types"
)

type Status string

const (
	// StatusInProgress indicates that the request is still being processed.
	StatusInProgress Status = "in_progress"
	// StatusCompleted indicates that the request has been completed.
	StatusCompleted Status = "completed"
	// StatusIncomplete indicates that the request is incomplete.
	StatusIncomplete Status = "incomplete"
	// StatusFailed indicates that the request has failed.
	StatusFailed Status = "failed"
)

var (
	reasoningPrefix = regexp.MustCompile("^(o[0-9]|gpt-5)")
)

type Request struct {
	Input              Input              `json:"input,omitempty"`
	Model              string             `json:"model,omitempty"`
	Include            []string           `json:"include,omitempty,omitzero"`
	Instructions       *string            `json:"instructions,omitempty"`
	MaxOutputTokens    *int               `json:"max_output_tokens,omitempty"`
	Metadata           map[string]string  `json:"metadata,omitempty"`
	ParallelToolCalls  *bool              `json:"parallel_tool_calls,omitempty"`
	PreviousResponseID *string            `json:"previous_response_id,omitempty"`
	Reasoning          *ResponseReasoning `json:"reasoning,omitempty"`
	ServiceTier        *string            `json:"service_tier,omitempty"`
	Store              *bool              `json:"store,omitempty"`
	Stream             *bool              `json:"stream,omitempty"`
	Temperature        *json.Number       `json:"temperature,omitempty"`
	Text               *TextFormatting    `json:"text,omitempty"`
	ToolChoice         *ToolChoice        `json:"tool_choice,omitempty"`
	Tools              []Tool             `json:"tools,omitempty,omitzero"`
	TopP               *json.Number       `json:"top_p,omitempty"`
	Truncation         *string            `json:"truncation,omitempty"`
	User               string             `json:"user,omitempty"`
}

type Input struct {
	Text  *string     `json:"-"`
	Items []InputItem `json:",inline"`
}

func (i *Input) GetItems() []InputItem {
	if i.Text != nil {
		return []InputItem{
			{
				Item: &Item{
					InputMessage: &InputMessage{
						Content: InputContent{
							Text: i.Text,
						},
						Role: "user",
					},
				},
			},
		}
	}
	return i.Items
}

func (i Input) MarshalJSON() ([]byte, error) {
	if i.Text != nil {
		return json.Marshal(*i.Text)
	}
	if i.Items != nil {
		return json.Marshal(i.Items)
	}
	return []byte("null"), nil
}

func (i *Input) UnmarshalJSON(data []byte) error {
	if bytes.HasPrefix(data, []byte("\"")) {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		i.Text = &s
		return nil
	}
	i.Items = make([]InputItem, 0)
	return json.Unmarshal(data, &i.Items)
}

type InputItem struct {
	*Item
	*ItemReference
}

func (i InputItem) MarshalJSON() ([]byte, error) {
	if i.ItemReference != nil {
		return json.Marshal(i.ItemReference)
	}
	if i.Item != nil {
		return json.Marshal(i.Item)
	}
	return []byte("null"), nil
}

func (i *InputItem) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "item_reference":
		i.ItemReference = &ItemReference{}
		return json.Unmarshal(data, i.ItemReference)
	}
	i.Item = &Item{}
	return json.Unmarshal(data, i.Item)
}

type ItemReference struct {
	ID   string `json:"id,omitempty"`
	Type string `json:"type,omitempty"`
}

func (i ItemReference) MarshalJSON() ([]byte, error) {
	i.Type = "item_reference"
	type Alias ItemReference
	return json.Marshal((Alias)(i))
}

type Item struct {
	*InputMessage
	*Message
	*FileSearchCall
	*ComputerCall
	*ComputerCallOutput
	*WebSearchCall
	*FunctionCall
	*FunctionCallOutput
	*Reasoning
}

func (i Item) MarshalJSON() ([]byte, error) {
	if i.InputMessage != nil {
		return json.Marshal(i.InputMessage)
	}
	if i.Message != nil {
		return json.Marshal(i.Message)
	}
	if i.FileSearchCall != nil {
		return json.Marshal(i.FileSearchCall)
	}
	if i.ComputerCall != nil {
		return json.Marshal(i.ComputerCall)
	}
	if i.ComputerCallOutput != nil {
		return json.Marshal(i.ComputerCallOutput)
	}
	if i.WebSearchCall != nil {
		return json.Marshal(i.WebSearchCall)
	}
	if i.FunctionCall != nil {
		return json.Marshal(i.FunctionCall)
	}
	if i.FunctionCallOutput != nil {
		return json.Marshal(i.FunctionCallOutput)
	}
	if i.Reasoning != nil {
		return json.Marshal(i.Reasoning)
	}
	return []byte("{}"), nil
}

func (i *Item) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "message":
		var test struct {
			ID      string `json:"id,omitempty"`
			Role    string `json:"role,omitempty"`
			Content any    `json:"content,omitempty"`
		}
		if err := json.Unmarshal(data, &test); err != nil {
			return err
		}
		if _, isString := test.Content.(string); isString || test.ID == "" || test.Role != "assistant" {
			// If the message is not an assistant message, treat it as an input message
			i.InputMessage = &InputMessage{}
			return json.Unmarshal(data, i.InputMessage)
		}
		i.Message = &Message{}
		return json.Unmarshal(data, i.Message)
	case "file_search_call":
		i.FileSearchCall = &FileSearchCall{}
		return json.Unmarshal(data, i.FileSearchCall)
	case "computer_call":
		i.ComputerCall = &ComputerCall{}
		return json.Unmarshal(data, i.ComputerCall)
	case "web_search_call":
		i.WebSearchCall = &WebSearchCall{}
		return json.Unmarshal(data, i.WebSearchCall)
	case "function_call":
		i.FunctionCall = &FunctionCall{}
		return json.Unmarshal(data, i.FunctionCall)
	case "reasoning":
		i.Reasoning = &Reasoning{}
		return json.Unmarshal(data, i.Reasoning)
	}
	i.FunctionCallOutput = &FunctionCallOutput{}
	return json.Unmarshal(data, i.FunctionCallOutput)
}

type FunctionCallOutput struct {
	CallID string  `json:"call_id,omitempty"`
	Output string  `json:"output"`
	Type   string  `json:"type,omitempty"`
	ID     *string `json:"id,omitempty"`
	Status *Status `json:"status,omitempty"`
}

func (f FunctionCallOutput) MarshalJSON() ([]byte, error) {
	f.Type = "function_call_output"
	type Alias FunctionCallOutput
	return json.Marshal((Alias)(f))
}

type ComputerCallOutput struct {
	CallID                   string                    `json:"call_id,omitempty"`
	Type                     string                    `json:"type,omitempty"`
	Output                   ComputerScreenshot        `json:"output,omitempty"`
	AcknowledgedSafetyChecks []AcknowledgedSafetyCheck `json:"acknowledged_safety_checks,omitempty,omitzero"`
	Status                   *Status                   `json:"status,omitempty"`
}

type AcknowledgedSafetyCheck struct {
	ID      string  `json:"id,omitempty"`
	Code    *string `json:"code,omitempty"`
	Message *string `json:"message,omitempty"`
}

type ComputerScreenshot struct {
	Type     string `json:"type,omitempty"`
	FileID   string `json:"file_id,omitempty"`
	ImageURL string `json:"image_url,omitempty"`
}

func (c ComputerScreenshot) MarshalJSON() ([]byte, error) {
	c.Type = "computer_screenshot"
	type Alias ComputerScreenshot
	return json.Marshal((Alias)(c))
}

func (c ComputerCallOutput) MarshalJSON() ([]byte, error) {
	c.Type = "computer_call_output"
	type Alias ComputerCallOutput
	return json.Marshal((Alias)(c))
}

type InputMessage struct {
	Content InputContent `json:"content,omitempty"`
	Role    string       `json:"role,omitempty"`
	Type    string       `json:"type,omitempty"`
	Status  Status       `json:"status,omitempty"`
}

type InputContent struct {
	Text             *string            `json:"-"`
	InputItemContent []InputItemContent `json:",inline"`
}

func (i InputContent) MarshalJSON() ([]byte, error) {
	if i.Text != nil {
		return json.Marshal(*i.Text)
	}
	if i.InputItemContent != nil {
		return json.Marshal(i.InputItemContent)
	}
	return []byte("null"), nil
}

func (i *InputContent) UnmarshalJSON(data []byte) error {
	if bytes.HasPrefix(data, []byte("\"")) {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		i.Text = &s
		return nil
	}
	i.InputItemContent = make([]InputItemContent, 0)
	return json.Unmarshal(data, &i.InputItemContent)
}

type InputItemContent struct {
	*InputText
	*InputImage
	*InputFile
}

func (i *InputItemContent) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "input_text":
		i.InputText = &InputText{}
		return json.Unmarshal(data, i.InputText)
	case "input_image":
		i.InputImage = &InputImage{}
		return json.Unmarshal(data, i.InputImage)
	case "input_file":
		i.InputFile = &InputFile{}
		return json.Unmarshal(data, i.InputFile)
	}
	return nil
}

func (i InputItemContent) MarshalJSON() ([]byte, error) {
	if i.InputText != nil {
		return json.Marshal(i.InputText)
	}
	if i.InputImage != nil {
		return json.Marshal(i.InputImage)
	}
	if i.InputFile != nil {
		return json.Marshal(i.InputFile)
	}
	return []byte("{}"), nil
}

type InputFile struct {
	Type     string  `json:"type,omitempty"`
	FileData *string `json:"file_data,omitempty"`
	FileURL  *string `json:"file_url,omitempty"`
	FileID   *string `json:"file_id,omitempty"`
	Filename string  `json:"filename,omitempty"`
}

func (i InputFile) MarshalJSON() ([]byte, error) {
	i.Type = "input_file"
	type Alias InputFile
	return json.Marshal((Alias)(i))
}

type InputImage struct {
	Type     string  `json:"type,omitempty"`
	Detail   string  `json:"detail,omitempty"`
	FileID   *string `json:"file_id,omitempty"`
	ImageURL *string `json:"image_url,omitempty"`
}

func (i InputImage) MarshalJSON() ([]byte, error) {
	i.Type = "input_image"
	type Alias InputImage
	return json.Marshal((Alias)(i))
}

type InputText struct {
	Type string `json:"type,omitempty"`
	Text string `json:"text,omitempty"`
}

func (i InputText) MarshalJSON() ([]byte, error) {
	i.Type = "input_text"
	type Alias InputText
	return json.Marshal((Alias)(i))
}

func (i InputMessage) MarshalJSON() ([]byte, error) {
	i.Type = "message"
	type Alias InputMessage
	return json.Marshal((Alias)(i))
}

type Response struct {
	CreatedAt          json.Number        `json:"created_at,omitempty"`
	Error              *ResponseError     `json:"error,omitempty"`
	ID                 string             `json:"id,omitempty"`
	IncompleteDetails  *IncompleteDetails `json:"incomplete_details,omitempty"`
	Instructions       string             `json:"instructions,omitempty"`
	MaxOutputTokens    *int               `json:"max_output_tokens,omitempty"`
	Metadata           map[string]string  `json:"metadata,omitempty"`
	Model              string             `json:"model,omitempty"`
	Object             string             `json:"object,omitempty"`
	Output             []ResponseOutput   `json:"output,omitempty"`
	ParallelToolCalls  bool               `json:"parallel_tool_calls,omitempty"`
	PreviousResponseID string             `json:"previous_response_id,omitempty"`
	Reasoning          *ResponseReasoning `json:"reasoning,omitempty"`
	ServiceTier        *string            `json:"service_tier,omitempty"`
	Status             Status             `json:"status,omitempty"`
	Temperature        *json.Number       `json:"temperature,omitempty"`
	Text               TextFormatting     `json:"text,omitempty"`
	ToolChoice         *ToolChoice        `json:"tool_choice,omitempty"`
	Tools              []Tool             `json:"tools,omitempty"`
	TopP               *json.Number       `json:"top_p,omitempty"`
	Truncation         *string            `json:"truncation,omitempty"`
	Usage              Usage              `json:"usage,omitempty"`
	User               string             `json:"user,omitempty"`
}

type Usage struct {
	InputTokens         int                `json:"input_tokens,omitempty"`
	InputTokensDetails  InputTokenDetails  `json:"input_tokens_details,omitempty"`
	OutputTokens        int                `json:"output_tokens,omitempty"`
	OutputTokensDetails OutputTokenDetails `json:"output_tokens_details,omitempty"`
	TotalTokens         int                `json:"total_tokens,omitempty"`
}

type OutputTokenDetails struct {
	ReasoningTokens int `json:"reasoning_tokens,omitempty"`
}

type InputTokenDetails struct {
	CachedTokens int `json:"cached_tokens,omitempty"`
}

type Tool struct {
	*FileSearch  `json:",inline"`
	*Function    `json:",inline"`
	*WebSearch   `json:",inline"`
	*ComputerUse `json:",inline"`
	*CustomTool  `json:",inline"`
}

type CustomTool struct {
	Type        string          `json:"type,omitempty"`
	Name        string          `json:"name,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitzero"`
	Strict      *bool           `json:"strict,omitempty"`
	Description string          `json:"description,omitempty"`
	Attributes  map[string]any  `json:"-"`
}

func (c *CustomTool) UnmarshalJSON(data []byte) error {
	type Alias CustomTool
	if err := json.Unmarshal(data, (*Alias)(c)); err != nil {
		return err
	}

	c.Attributes = make(map[string]any)
	if err := json.Unmarshal(data, &c.Attributes); err != nil {
		return err
	}

	delete(c.Attributes, "name")
	delete(c.Attributes, "parameters")
	delete(c.Attributes, "strict")
	delete(c.Attributes, "description")
	c.Type = ""

	return nil
}

func (c CustomTool) MarshalJSON() ([]byte, error) {
	if c.Type == "" {
		c.Type = "function"
	}

	type Alias CustomTool
	data, err := json.Marshal((Alias)(c))
	if err != nil {
		return nil, err
	}

	if len(c.Attributes) > 0 {
		base := map[string]any{}
		if err := json.Unmarshal(data, &base); err != nil {
			return nil, err
		}
		var toRemove []string
		if c.Attributes["type"] == "computer_use_preview" {
			toRemove = append(toRemove, "name", "description", "parameters", "strict")
		} else if strings.HasPrefix(fmt.Sprint(c.Attributes["type"]), "computer_") {
			toRemove = append(toRemove, "description", "strict")
		}
		for k, v := range c.Attributes {
			if l, ok := v.([]any); k == "remove" && ok {
				for _, v := range l {
					if s, ok := v.(string); ok {
						toRemove = append(toRemove, s)
					}
				}
				continue
			}
			if v != "" {
				base[k] = v
			}
		}
		for _, k := range toRemove {
			delete(base, k)
		}
		return json.Marshal(base)
	}

	return data, nil
}

func (t Tool) MarshalJSON() ([]byte, error) {
	if t.FileSearch != nil {
		return json.Marshal(t.FileSearch)
	} else if t.Function != nil {
		return json.Marshal(t.Function)
	} else if t.WebSearch != nil {
		return json.Marshal(t.WebSearch)
	} else if t.ComputerUse != nil {
		return json.Marshal(t.ComputerUse)
	} else if t.CustomTool != nil {
		return json.Marshal(t.CustomTool)
	}
	return []byte("{}"), nil
}

func (t *Tool) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "file_search":
		t.FileSearch = &FileSearch{}
		return json.Unmarshal(data, t.FileSearch)
	case "function":
		t.Function = &Function{}
		return json.Unmarshal(data, t.Function)
	case "web_search_preview", "web_search_preview_2025_03_11":
		t.WebSearch = &WebSearch{}
		return json.Unmarshal(data, t.WebSearch)
	case "computer_use_preview":
		t.ComputerUse = &ComputerUse{}
		return json.Unmarshal(data, t.ComputerUse)
	default:
		t.CustomTool = &CustomTool{}
		return json.Unmarshal(data, t.CustomTool)
	}
}

type ComputerUse struct {
	Type          string `json:"type,omitempty"`
	DisplayHeight int    `json:"display_height,omitempty"`
	DisplayWidth  int    `json:"display_width,omitempty"`
	Environment   string `json:"environment,omitempty"`
}

func (c ComputerUse) MarshalJSON() ([]byte, error) {
	c.Type = "computer_use_preview"
	type Alias ComputerUse
	return json.Marshal((Alias)(c))
}

type WebSearch struct {
	Type              string       `json:"type,omitempty"`
	SearchContextSize string       `json:"search_context_size,omitempty"`
	UserLocation      *Approximate `json:"user_location,omitempty"`
}

type Approximate struct {
	Type     string  `json:"type,omitempty"`
	City     *string `json:"city,omitempty"`
	Country  *string `json:"country,omitempty"`
	Region   *string `json:"region,omitempty"`
	Timezone *string `json:"timezone,omitempty"`
}

func (a Approximate) MarshalJSON() ([]byte, error) {
	a.Type = "approximate"
	type Alias Approximate
	return json.Marshal((Alias)(a))
}

type Function struct {
	Type        string          `json:"type,omitempty"`
	Name        string          `json:"name,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
	Strict      *bool           `json:"strict,omitempty"`
	Description string          `json:"description,omitempty"`
}

func (f Function) MarshalJSON() ([]byte, error) {
	f.Type = "function"
	type Alias Function
	return json.Marshal((Alias)(f))
}

type FileSearch struct {
	Type           string         `json:"type,omitempty"`
	VectorStoreIDs []string       `json:"vector_store_ids,omitempty"`
	Filters        []Filter       `json:"filters,omitempty,omitzero"`
	MaxNumResults  int            `json:"max_num_results,omitempty"`
	RankingOptions RankingOptions `json:"ranking_options,omitempty,omitzero"`
}

type RankingOptions struct {
	Ranker         string      `json:"ranker,omitempty"`
	ScoreThreshold json.Number `json:"score_threshold,omitempty"`
}

type Filter struct {
	*ComparisonFilter `json:",inline"`
	*CompositeFilter  `json:",inline"`
}

func (f Filter) MarshalJSON() ([]byte, error) {
	if f.CompositeFilter != nil {
		return json.Marshal(f.CompositeFilter)
	}
	if f.ComparisonFilter != nil {
		return json.Marshal(f.ComparisonFilter)
	}
	return []byte("{}"), nil
}

func (f *Filter) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "and", "or":
		f.CompositeFilter = &CompositeFilter{}
		return json.Unmarshal(data, f.CompositeFilter)
	case "":
		// nothing
	default:
		f.ComparisonFilter = &ComparisonFilter{}
		return json.Unmarshal(data, f.ComparisonFilter)
	}
	return nil
}

type CompositeFilter struct {
	Type    string   `json:"type,omitempty"`
	Filters []Filter `json:"filters,omitempty,omitzero"`
}

type ComparisonFilter struct {
	Type  string     `json:"type,omitempty"`
	Key   string     `json:"key,omitempty"`
	Value NativeType `json:"value,omitempty"`
}

type NativeType struct {
	String  *string      `json:"string,omitempty"`
	Number  *json.Number `json:"number,omitempty"`
	Boolean *bool        `json:"boolean,omitempty"`
}

func (n NativeType) MarshalJSON() ([]byte, error) {
	if n.String != nil {
		return json.Marshal(n.String)
	} else if n.Number != nil {
		return json.Marshal(n.Number)
	} else if n.Boolean != nil {
		return json.Marshal(n.Boolean)
	}
	return []byte("null"), nil
}

func (n *NativeType) UnmarshalJSON(data []byte) error {
	if bytes.Equal(data, []byte("true")) || bytes.Equal(data, []byte("false")) {
		var b bool
		if err := json.Unmarshal(data, &b); err != nil {
			return err
		}
		n.Boolean = &b
	} else if bytes.HasPrefix(data, []byte("\"")) {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		n.String = &s
	} else {
		var num json.Number
		if err := json.Unmarshal(data, &num); err != nil {
			return err
		}
		n.Number = &num
	}
	return nil
}

func (f FileSearch) MarshalJSON() ([]byte, error) {
	f.Type = "file_search"
	type Alias FileSearch
	return json.Marshal((Alias)(f))
}

type ToolChoice struct {
	Mode          string
	*HostedTool   `json:",inline"`
	*FunctionTool `json:",inline"`
}

func (f ToolChoice) MarshalJSON() ([]byte, error) {
	if f.Mode != "" {
		return json.Marshal(f.Mode)
	}
	if f.HostedTool != nil {
		return json.Marshal(f.HostedTool)
	}
	return []byte("{}"), nil
}

func (f *ToolChoice) UnmarshalJSON(data []byte) error {
	if bytes.HasPrefix(data, []byte("\"")) {
		if err := json.Unmarshal(data, &f.Mode); err != nil {
			return err
		}
		return nil
	}

	switch getType(data) {
	case "function":
		f.FunctionTool = &FunctionTool{}
		return json.Unmarshal(data, f.FunctionTool)
	case "file_search", "web_search_preview", "computer_use_preview":
		f.HostedTool = &HostedTool{}
		return json.Unmarshal(data, f.HostedTool)
	}

	return nil
}

type HostedTool struct {
	Type string `json:"type,omitempty"`
}

type FunctionTool struct {
	Name string `json:"name,omitempty"`
	Type string `json:"type,omitempty"`
}

func (f FunctionTool) MarshalJSON() ([]byte, error) {
	f.Type = "function"
	type Alias FunctionTool
	return json.Marshal((Alias)(f))
}

type TextFormatting struct {
	Format Format `json:"format,omitempty"`
}

type Format struct {
	*TextFormat `json:",inline"`
	*JSONSchema `json:",inline"`
	*JSONObject `json:",inline"`
}

func (f Format) MarshalJSON() ([]byte, error) {
	if f.TextFormat != nil {
		return json.Marshal(f.TextFormat)
	}
	if f.JSONSchema != nil {
		return json.Marshal(f.JSONSchema)
	}
	if f.JSONObject != nil {
		return json.Marshal(f.JSONObject)
	}
	return []byte("{}"), nil
}

func (f *Format) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "text":
		f.TextFormat = &TextFormat{}
		return json.Unmarshal(data, f.TextFormat)
	case "json_schema":
		f.JSONSchema = &JSONSchema{}
		return json.Unmarshal(data, f.JSONSchema)
	case "json_object":
		f.JSONObject = &JSONObject{}
		return json.Unmarshal(data, f.JSONObject)
	}
	return nil
}

type JSONSchema struct {
	Name        string          `json:"name,omitempty"`
	Schema      json.RawMessage `json:"schema,omitempty"`
	Description string          `json:"description,omitempty"`
	Type        string          `json:"type,omitempty"`
	Strict      bool            `json:"strict,omitempty"`
}

func (f JSONSchema) MarshalJSON() ([]byte, error) {
	f.Type = "json_schema"
	type Alias JSONSchema
	return json.Marshal((Alias)(f))
}

type JSONObject struct {
	Type string `json:"type,omitempty"`
}

func (f JSONObject) MarshalJSON() ([]byte, error) {
	f.Type = "json_object"
	type Alias JSONObject
	return json.Marshal((Alias)(f))
}

type TextFormat struct {
	Type string `json:"type,omitempty"`
}

func (f TextFormat) MarshalJSON() ([]byte, error) {
	f.Type = "text"
	type Alias TextFormat
	return json.Marshal((Alias)(f))
}

type ResponseReasoning struct {
	Effort  *string `json:"effort,omitempty"`
	Summary *string `json:"summary,omitempty"`
}

type IncompleteDetails struct {
	Reason string `json:"reason,omitempty"`
}

type ResponseError struct {
	Code    string `json:"code,omitempty"`
	Message string `json:"message,omitempty"`
}

type ResponseOutput struct {
	*Message        `json:",inline"`
	*FileSearchCall `json:",inline"`
	*FunctionCall   `json:",inline"`
	*WebSearchCall  `json:",inline"`
	*ComputerCall   `json:",inline"`
	*Reasoning      `json:",inline"`
}

func (r *ResponseOutput) ToInput() InputItem {
	return InputItem{
		Item: &Item{
			Message:        r.Message,
			FileSearchCall: r.FileSearchCall,
			FunctionCall:   r.FunctionCall,
			WebSearchCall:  r.WebSearchCall,
			ComputerCall:   r.ComputerCall,
			Reasoning:      r.Reasoning,
		},
	}
}

func (r ResponseOutput) MarshalJSON() ([]byte, error) {
	if r.Message != nil {
		return json.Marshal(r.Message)
	}
	if r.FileSearchCall != nil {
		return json.Marshal(r.FileSearchCall)
	}
	if r.FunctionCall != nil {
		return json.Marshal(r.FunctionCall)
	}
	if r.WebSearchCall != nil {
		return json.Marshal(r.WebSearchCall)
	}
	if r.ComputerCall != nil {
		return json.Marshal(r.ComputerCall)
	}
	if r.Reasoning != nil {
		return json.Marshal(r.Reasoning)
	}
	return []byte("{}"), nil
}

func (r *ResponseOutput) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "message":
		r.Message = &Message{}
		return json.Unmarshal(data, r.Message)
	case "file_search_call":
		r.FileSearchCall = &FileSearchCall{}
		return json.Unmarshal(data, r.FileSearchCall)
	case "function_call":
		r.FunctionCall = &FunctionCall{}
		return json.Unmarshal(data, r.FunctionCall)
	case "web_search_call":
		r.WebSearchCall = &WebSearchCall{}
		return json.Unmarshal(data, r.WebSearchCall)
	case "computer_call":
		r.ComputerCall = &ComputerCall{}
		return json.Unmarshal(data, r.ComputerCall)
	case "reasoning":
		r.Reasoning = &Reasoning{}
		return json.Unmarshal(data, r.Reasoning)
	}
	return nil
}

type FileSearchCall struct {
	ID      string             `json:"id,omitempty"`
	Type    string             `json:"type,omitempty"`
	Queries []string           `json:"queries,omitempty"`
	Status  Status             `json:"status,omitempty"`
	Results []FileSearchResult `json:"results,omitempty"`
}

type FileSearchResult struct {
	Attributes map[string]string `json:"attributes,omitempty"`
	FileID     string            `json:"file_id,omitempty"`
	Filename   string            `json:"filename,omitempty"`
	Score      json.Number       `json:"score,omitempty"`
	Text       string            `json:"text,omitempty"`
}

type Reasoning struct {
	Type             string        `json:"type,omitempty"`
	ID               string        `json:"id,omitempty"`
	Summary          []SummaryText `json:"summary"`
	Status           Status        `json:"status,omitempty"`
	EncryptedContent *string       `json:"encrypted_content,omitempty"`
}

func (r Reasoning) GetSummary() (result []types.SummaryText) {
	for _, s := range r.Summary {
		result = append(result, types.SummaryText{
			Text: s.Text,
		})
	}
	return result
}

func (r Reasoning) MarshalJSON() ([]byte, error) {
	r.Type = "reasoning"
	type Alias Reasoning
	return json.Marshal((Alias)(r))
}

type SummaryText struct {
	Type string `json:"type,omitempty"`
	Text string `json:"text,omitempty"`
}

func (r SummaryText) MarshalJSON() ([]byte, error) {
	r.Type = "summary_text"
	type Alias SummaryText
	return json.Marshal((Alias)(r))
}

type ComputerCall struct {
	ID                  string                `json:"id,omitempty"`
	Type                string                `json:"type,omitempty"`
	CallID              string                `json:"call_id,omitempty"`
	Status              Status                `json:"status,omitempty"`
	PendingSafetyChecks []PendingSafetyChecks `json:"pending_safety_checks,omitempty,omitzero"`
	Action              ComputerCallAction    `json:"action,omitempty"`
}

type ComputerCallAction struct {
	*Click       `json:",inline"`
	*DoubleClick `json:",inline"`
	*Drag        `json:",inline"`
	*KeyPress    `json:",inline"`
	*Move        `json:",inline"`
	*ScreenShot  `json:",inline"`
	*Scroll      `json:",inline"`
	*Type        `json:",inline"`
	*Wait        `json:",inline"`
}

func (c ComputerCallAction) MarshalJSON() ([]byte, error) {
	if c.Click != nil {
		return json.Marshal(c.Click)
	}
	if c.DoubleClick != nil {
		return json.Marshal(c.DoubleClick)
	}
	if c.Drag != nil {
		return json.Marshal(c.Drag)
	}
	if c.KeyPress != nil {
		return json.Marshal(c.KeyPress)
	}
	if c.Move != nil {
		return json.Marshal(c.Move)
	}
	if c.ScreenShot != nil {
		return json.Marshal(c.ScreenShot)
	}
	if c.Scroll != nil {
		return json.Marshal(c.Scroll)
	}
	if c.Type != nil {
		return json.Marshal(c.Type)
	}
	if c.Wait != nil {
		return json.Marshal(c.Wait)
	}
	return []byte("{}"), nil
}

func (c *ComputerCallAction) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "click":
		c.Click = &Click{}
		return json.Unmarshal(data, c.Click)
	case "double_click":
		c.DoubleClick = &DoubleClick{}
		return json.Unmarshal(data, c.DoubleClick)
	case "drag":
		c.Drag = &Drag{}
		return json.Unmarshal(data, c.Drag)
	case "keypress":
		c.KeyPress = &KeyPress{}
		return json.Unmarshal(data, c.KeyPress)
	case "move":
		c.Move = &Move{}
		return json.Unmarshal(data, c.Move)
	case "screenshot":
		c.ScreenShot = &ScreenShot{}
		return json.Unmarshal(data, c.ScreenShot)
	case "scroll":
		c.Scroll = &Scroll{}
		return json.Unmarshal(data, c.Scroll)
	case "type":
		c.Type = &Type{}
		return json.Unmarshal(data, c.Type)
	case "wait":
		c.Wait = &Wait{}
		return json.Unmarshal(data, c.Wait)
	}
	return nil
}

type Wait struct {
	Type string `json:"type"`
}

func (w Wait) MarshalJSON() ([]byte, error) {
	w.Type = "wait"
	type Alias Wait
	return json.Marshal((Alias)(w))
}

type Type struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

func (t Type) MarshalJSON() ([]byte, error) {
	t.Type = "type"
	type Alias Type
	return json.Marshal((Alias)(t))
}

type Scroll struct {
	Type    string `json:"type"`
	ScrollX int    `json:"scroll_x"`
	ScrollY int    `json:"scroll_y"`
	X       int    `json:"x"`
	Y       int    `json:"y"`
}

func (s Scroll) MarshalJSON() ([]byte, error) {
	s.Type = "scroll"
	type Alias Scroll
	return json.Marshal((Alias)(s))
}

type ScreenShot struct {
	Type string `json:"type"`
}

func (s ScreenShot) MarshalJSON() ([]byte, error) {
	s.Type = "screenshot"
	type Alias ScreenShot
	return json.Marshal((Alias)(s))
}

type Move struct {
	X    int    `json:"x"`
	Y    int    `json:"y"`
	Type string `json:"type"`
}

func (m Move) MarshalJSON() ([]byte, error) {
	m.Type = "move"
	type Alias Move
	return json.Marshal((Alias)(m))
}

type KeyPress struct {
	Type string   `json:"type"`
	Keys []string `json:"keys"`
}

func (k KeyPress) MarshalJSON() ([]byte, error) {
	k.Type = "keypress"
	type Alias KeyPress
	return json.Marshal((Alias)(k))
}

type Drag struct {
	Type string     `json:"type"`
	Path []DragPath `json:"path"`
}

func (d Drag) MarshalJSON() ([]byte, error) {
	d.Type = "drag"
	type Alias Drag
	return json.Marshal((Alias)(d))
}

type DragPath struct {
	X int `json:"x"`
	Y int `json:"y"`
}

type DoubleClick struct {
	X    int    `json:"x"`
	Y    int    `json:"y"`
	Type string `json:"type"`
}

func (d DoubleClick) MarshalJSON() ([]byte, error) {
	d.Type = "double_click"
	type Alias DoubleClick
	return json.Marshal((Alias)(d))
}

type Click struct {
	X      int    `json:"x"`
	Y      int    `json:"y"`
	Type   string `json:"type"`
	Button string `json:"button"`
}

func (c Click) MarshalJSON() ([]byte, error) {
	c.Type = "click"
	type Alias Click
	return json.Marshal((Alias)(c))
}

type PendingSafetyChecks struct {
	Code    string `json:"code,omitempty"`
	ID      string `json:"id,omitempty"`
	Message string `json:"message,omitempty"`
}

func (c ComputerCall) MarshalJSON() ([]byte, error) {
	c.Type = "computer_call"
	type Alias ComputerCall
	return json.Marshal((Alias)(c))
}

type WebSearchCall struct {
	Type   string `json:"type,omitempty"`
	ID     string `json:"id,omitempty"`
	Status Status `json:"status,omitempty"`
}

func (w WebSearchCall) MarshalJSON() ([]byte, error) {
	w.Type = "web_search_call"
	type Alias WebSearchCall
	return json.Marshal((Alias)(w))
}

type FunctionCall struct {
	Type      string `json:"type,omitempty"`
	Arguments string `json:"arguments,omitempty"`
	CallID    string `json:"call_id,omitempty"`
	Name      string `json:"name,omitempty"`
	ID        string `json:"id,omitempty"`
	Status    Status `json:"status,omitempty"`
}

func (f FunctionCall) MarshalJSON() ([]byte, error) {
	f.Type = "function_call"
	type Alias FunctionCall
	return json.Marshal((Alias)(f))
}

type Message struct {
	ID      string           `json:"id,omitempty"`
	Content []MessageContent `json:"content,omitempty"`
	Role    string           `json:"role,omitempty"`
	Type    string           `json:"type,omitempty"`
	Status  Status           `json:"status,omitempty"`
}

func (m Message) MarshalJSON() ([]byte, error) {
	m.Role = "assistant"
	m.Type = "message"
	type Alias Message
	return json.Marshal((Alias)(m))
}

type MessageContent struct {
	*OutputText `json:",inline"`
	*Refusal    `json:",inline"`
}

func (m MessageContent) MarshalJSON() ([]byte, error) {
	if m.OutputText != nil {
		return json.Marshal(m.OutputText)
	}
	if m.Refusal != nil {
		return json.Marshal(m.Refusal)
	}
	return []byte("{}"), nil
}

func (m *MessageContent) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "output_text":
		m.OutputText = &OutputText{}
		return json.Unmarshal(data, m.OutputText)
	case "refusal":
		m.Refusal = &Refusal{}
		return json.Unmarshal(data, m.Refusal)
	}
	return nil
}

type Refusal struct {
	Refusal string `json:"refusal,omitempty"`
	Type    string `json:"type,omitempty"`
}

func (m Refusal) MarshalJSON() ([]byte, error) {
	m.Type = "refusal"
	type Alias Refusal
	return json.Marshal((Alias)(m))
}

type OutputText struct {
	Annotations []string `json:"annotations,omitempty"`
	Text        string   `json:"text,omitempty"`
	Type        string   `json:"type,omitempty"`
}

func (m OutputText) MarshalJSON() ([]byte, error) {
	m.Type = "output_text"
	type Alias OutputText
	return json.Marshal((Alias)(m))
}

type MessageAnnotation struct {
	*FileCitation `json:",inline"`
	*URLCitation  `json:",inline"`
	*FilePath     `json:",inline"`
}

func getType(data []byte) string {
	var t struct {
		Type string `json:"type,omitempty"`
	}
	_ = json.Unmarshal(data, &t)
	return t.Type
}

func (m MessageAnnotation) MarshalJSON() ([]byte, error) {
	if m.FileCitation != nil {
		return json.Marshal(m.FileCitation)
	}
	if m.URLCitation != nil {
		return json.Marshal(m.URLCitation)
	}
	if m.FilePath != nil {
		return json.Marshal(m.FilePath)
	}
	return []byte("{}"), nil
}

func (m *MessageAnnotation) UnmarshalJSON(data []byte) error {
	switch getType(data) {
	case "file_citation":
		m.FileCitation = &FileCitation{}
		return json.Unmarshal(data, m.FileCitation)
	case "url_citation":
		m.URLCitation = &URLCitation{}
		return json.Unmarshal(data, m.URLCitation)
	case "file_path":
		m.FilePath = &FilePath{}
		return json.Unmarshal(data, m.FilePath)
	}

	return nil
}

type FilePath struct {
	FileID string `json:"file_id,omitempty"`
	Index  int    `json:"index,omitempty"`
	Type   string `json:"type,omitempty"`
}

func (f FilePath) MarshalJSON() ([]byte, error) {
	f.Type = "file_path"
	type Alias FilePath
	return json.Marshal((Alias)(f))
}

type URLCitation struct {
	URL        string `json:"url,omitempty"`
	Title      string `json:"title,omitempty"`
	StartIndex int    `json:"start_index,omitempty"`
	EndIndex   int    `json:"end_index,omitempty"`
	Type       string `json:"type,omitempty"`
}

func (m URLCitation) MarshalJSON() ([]byte, error) {
	m.Type = "url_citation"
	type Alias URLCitation
	return json.Marshal((Alias)(m))
}

type FileCitation struct {
	FileID string `json:"file_id,omitempty"`
	Index  int    `json:"index,omitempty"`
	Type   string `json:"type,omitempty"`
}

func (f FileCitation) MarshalJSON() ([]byte, error) {
	f.Type = "file_citation"
	type Alias FileCitation
	return json.Marshal((Alias)(f))
}

func (r Response) MarshalJSON() ([]byte, error) {
	r.Object = "response"
	type Alias Response
	return json.Marshal((Alias)(r))
}

type Progress struct {
	Type     string       `json:"type,omitempty"`
	Delta    string       `json:"delta,omitempty"`
	Item     ProgressItem `json:"item,omitempty"`
	Response Response     `json:"response"`
}

type ProgressItem struct {
	ID        string `json:"id,omitempty"`
	CallID    string `json:"call_id,omitempty"`
	Type      string `json:"type,omitempty"`
	Name      string `json:"name,omitempty"`
	Arguments string `json:"arguments,omitempty"`
	Role      string `json:"role,omitempty"`
}
