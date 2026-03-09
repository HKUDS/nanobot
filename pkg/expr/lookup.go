package expr

import (
	"strings"
	"time"
)

func builtinEnv(envMap map[string]string, key string) (string, bool) {
	switch key {
	case "nanobot:time":
		now := time.Now()
		if tz, ok := envMap["TZ"]; ok {
			loc, err := time.LoadLocation(tz)
			if err != nil {
				return "", false
			}
			now = now.In(loc)
		}
		if format, ok := envMap["TIME_FORMAT"]; ok {
			return now.Format(format), true
		}
		return now.Format(time.RFC3339), true
	default:
		return "", false
	}
}

func Lookup(envMap map[string]string, envKey string) (string, bool) {
	v, ok := builtinEnv(envMap, envKey)
	if ok {
		return v, true
	}

	val, ok := envMap[envKey]
	if ok {
		return val, true
	}
	for envMapKey, envMapVal := range envMap {
		if strings.EqualFold(envKey, strings.ReplaceAll(envMapKey, "-", "_")) {
			val = envMapVal
			ok = true
			break
		}
	}
	if ok {
		return val, true
	}

	return "", false
}
