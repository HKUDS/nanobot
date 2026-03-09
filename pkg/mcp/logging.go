package mcp

import (
	"encoding/json"
	"fmt"
	"strconv"
)

func MessageIDString(id any) string {
	switch v := id.(type) {
	case nil:
		return ""
	case json.Number:
		return v.String()
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(v), 'f', -1, 32)
	default:
		return fmt.Sprint(id)
	}
}
