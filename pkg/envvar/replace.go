package envvar

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"slices"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/expr"
)

func ReplaceString(envs map[string]string, str string) string {
	r, err := expr.EvalString(context.TODO(), envs, nil, str)
	if err != nil {
		slog.Error("failed to evaluate expression", "expression", str, "error", err)
		return str
	}
	return r
}

func ReplaceObject(envs map[string]string, obj any) error {
	text, err := json.Marshal(obj)
	if err != nil {
		return err
	}
	return json.Unmarshal(
		[]byte(ReplaceString(envs, string(text))),
		obj,
	)
}

func ReplaceMap(envs map[string]string, m map[string]string) map[string]string {
	newMap := make(map[string]string, len(m))
	for k, v := range m {
		newMap[ReplaceString(envs, k)] = ReplaceString(envs, v)
	}
	return newMap
}

func ReplaceEnv(envs map[string]string, command string, args []string, env map[string]string) (string, []string, []string) {
	newEnvMap := make(map[string]string, len(env))
	maps.Copy(newEnvMap, ReplaceMap(envs, env))

	newEnv := make([]string, 0, len(env))
	for _, k := range slices.Sorted(maps.Keys(newEnvMap)) {
		newEnv = append(newEnv, fmt.Sprintf("%s=%s", k, newEnvMap[k]))
	}

	newArgs := make([]string, len(args))
	for i, arg := range args {
		newArgs[i] = ReplaceString(envs, arg)
	}
	return ReplaceString(envs, command), newArgs, newEnv
}
