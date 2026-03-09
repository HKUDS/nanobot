package agents

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"math"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/types"
	tiktoken "github.com/pkoukk/tiktoken-go"
	"golang.org/x/image/webp"
)

func init() {
	// Register the WebP format so image.DecodeConfig can handle it alongside
	// JPEG, PNG, and GIF (which are registered via their blank imports above).
	// The golang.org/x/image/webp package does not auto-register like the
	// standard library image format packages do.
	image.RegisterFormat("webp", "RIFF????WEBP", webp.Decode, webp.DecodeConfig)
}

// estimateTokens estimates the total token count for a set of messages, a system prompt, and tool definitions.
// It uses the cl100k_base encoding (reasonable for both OpenAI and Anthropic models).
// Falls back to len(text)/4 heuristic if tiktoken encoding fails.
//
// For image content in tool call results, vision tokens are estimated from the
// image dimensions rather than the base64 data length. See estimateImageTokens
// for details on the estimation approach.
func estimateTokens(messages []types.Message, systemPrompt string, tools []types.ToolUseDefinition) int {
	var (
		sb          strings.Builder
		imageTokens int
	)

	if systemPrompt != "" {
		sb.WriteString(systemPrompt)
		sb.WriteString("\n")
	}

	for _, msg := range messages {
		sb.WriteString(msg.Role)
		sb.WriteString(": ")
		for _, item := range msg.Items {
			if item.Content != nil {
				sb.WriteString(item.Content.Text)
				sb.WriteString(" ")
			}
			if item.ToolCall != nil {
				sb.WriteString(item.ToolCall.Name)
				sb.WriteString(" ")
				sb.WriteString(item.ToolCall.Arguments)
				sb.WriteString(" ")
			}
			if item.ToolCallResult != nil {
				for _, c := range item.ToolCallResult.Output.Content {
					switch c.Type {
					case "text", "":
						sb.WriteString(c.Text)
					case "image":
						// Estimate vision tokens from image dimensions rather than
						// counting the base64 data as text tokens. See estimateImageTokens
						// for details on the estimation approach.
						imageTokens += estimateImageTokens(c.Data)
					case "audio":
						sb.WriteString(c.Data)
					case "resource":
						if c.Resource != nil {
							sb.WriteString(c.Resource.Text)
							sb.WriteString(c.Resource.Blob)
						}
					default:
						if data, err := json.Marshal(c); err == nil {
							sb.Write(data)
						}
					}
					sb.WriteString(" ")
				}
			}
			if item.Reasoning != nil {
				for _, s := range item.Reasoning.Summary {
					sb.WriteString(s.Text)
					sb.WriteString(" ")
				}
			}
		}
		sb.WriteString("\n")
	}

	for _, tool := range tools {
		sb.WriteString(tool.Name)
		sb.WriteString(" ")
		sb.WriteString(tool.Description)
		sb.WriteString(" ")
		if len(tool.Parameters) > 0 {
			sb.Write(tool.Parameters)
			sb.WriteString(" ")
		}
		sb.WriteString("\n")
	}

	return countTokens(sb.String()) + imageTokens
}

// estimateImageTokens estimates the number of tokens an image will consume when
// sent to an LLM with vision capabilities, based on its pixel dimensions.
//
// The estimate uses the formula from Anthropic's vision documentation:
//
//	tokens = (width × height) / 750
//
// See: https://platform.claude.com/docs/en/build-with-claude/vision#calculate-image-costs
//
// Before applying the formula, the image dimensions are scaled down (preserving
// aspect ratio) so that neither edge exceeds 1568 pixels, matching the resize
// behavior described in the Anthropic docs.
//
// This produces an upper-bound estimate. In practice, Anthropic's actual token
// counts tend to be lower than the formula suggests, and OpenAI's vision token
// costs are typically lower still (in testing, OpenAI reported roughly half the
// tokens that Anthropic did for the same image). The overestimate is intentional
// — it is safer to overcount tokens when managing context window budgets, as
// undercounting risks exceeding the context limit.
//
// JPEG, PNG, GIF, and WebP formats are supported. JPEG, PNG, and GIF use Go's
// standard library decoders; WebP uses golang.org/x/image/webp, registered via
// init(). For unrecognized formats or when the image data cannot be decoded, a
// conservative fallback of 1600 tokens is returned. This corresponds roughly to
// the token cost of a max-sized image after Anthropic's server-side resizing
// (~1568×1568 pixels).
//
// The data parameter is expected to be a base64-encoded image, as returned by
// MCP tool results (mcp.Content with Type "image").
func estimateImageTokens(data string) int {
	raw, err := base64.StdEncoding.DecodeString(data)
	if err != nil {
		return 1600
	}

	// DecodeConfig reads only the image header to extract dimensions — it does
	// not decode the full pixel data, so this is cheap even for large images.
	cfg, _, err := image.DecodeConfig(bytes.NewReader(raw))
	if err != nil {
		return 1600
	}

	w, h := cfg.Width, cfg.Height

	// Anthropic scales images down so that neither dimension exceeds 1568px,
	// preserving the original aspect ratio.
	const maxEdge = 1568
	if w > maxEdge || h > maxEdge {
		scale := float64(maxEdge) / float64(max(w, h))
		w = int(float64(w) * scale)
		h = int(float64(h) * scale)
	}

	return int(math.Round(float64(w*h) / 750.0))
}

// countTokens counts the tokens in the given text using tiktoken's cl100k_base encoding.
// Falls back to len(text)/4 if encoding fails.
func countTokens(text string) int {
	enc, err := tiktoken.GetEncoding("cl100k_base")
	if err != nil {
		return len(text) / 4
	}
	return len(enc.Encode(text, nil, nil))
}
