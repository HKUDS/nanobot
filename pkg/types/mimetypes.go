package types

const (
	MessageMimeType     = "application/vnd.nanobot.chat.message+json"
	HistoryMimeType     = "application/vnd.nanobot.chat.history+json"
	ToolResultMimeType  = "application/vnd.nanobot.tool.result+json"
	ErrorMimeType       = "application/vnd.nanobot.error+json"
	AgentMimeType       = "application/vnd.nanobot.agent+json"
	SessionMimeType     = "application/vnd.nanobot.session+json"
	ElicitationMimeType = "application/vnd.nanobot.elicitation+json"
	MetaNanobot         = "ai.nanobot"

	MessageURI     = "chat://message/%s"
	HistoryURI     = "chat://history"
	ProgressURI    = "chat://progress"
	ElicitationURI = "chat://elicitation"
)

var (
	ImageMimeTypes = map[string]struct{}{
		"image/png":  {},
		"image/jpeg": {},
		"image/webp": {},
	}
	TextMimeTypes = map[string]struct{}{
		"text/plain":       {},
		"text/markdown":    {},
		"text/html":        {},
		"text/csv":         {},
		"application/json": {},
	}
	PDFMimeTypes = map[string]struct{}{
		"application/pdf": {},
	}
)
