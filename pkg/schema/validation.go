package schema

import (
	"encoding/json"

	"github.com/nanobot-ai/nanobot/pkg/types"
)

// ValidateAndFixToolSchema validates and fixes tool input schemas to ensure they meet
// LLM provider requirements, specifically ensuring object schemas have properties defined.
func ValidateAndFixToolSchema(schema json.RawMessage) json.RawMessage {
	if len(schema) == 0 {
		// Return a valid empty object schema for tools with no parameters
		return json.RawMessage(`{"type": "object", "properties": {}}`)
	}

	var schemaObj map[string]any
	if err := json.Unmarshal(schema, &schemaObj); err != nil {
		// If we can't parse it, return a safe default
		return json.RawMessage(`{"type": "object", "properties": {}}`)
	}

	// Check if this is an object type schema
	if schemaType, ok := schemaObj["type"].(string); ok && schemaType == "object" {
		// If it's an object type but missing properties, add an empty properties object
		if _, hasProperties := schemaObj["properties"]; !hasProperties {
			schemaObj["properties"] = map[string]any{}
		}

		// Re-marshal the fixed schema
		if fixedSchema, err := json.Marshal(schemaObj); err == nil {
			return json.RawMessage(fixedSchema)
		}
	}

	// Return the original schema if no fixes were needed or if we couldn't fix it
	return schema
}

// ValidateToolMappings validates and fixes tool schemas in tool mappings to ensure compatibility with LLM providers
func ValidateToolMappings(toolMappings types.ToolMappings) types.ToolMappings {
	validated := make(types.ToolMappings)
	for k, mapping := range toolMappings {
		mapping.Target.InputSchema = ValidateAndFixToolSchema(mapping.Target.InputSchema)
		validated[k] = mapping
	}
	return validated
}
