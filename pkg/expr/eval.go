package expr

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/dop251/goja"
)

func EvalString(ctx context.Context, env map[string]string, data map[string]any, expr string) (string, error) {
	ret, err := evalString(ctx, env, data, expr)
	if err != nil {
		return "", fmt.Errorf("failed to evaluate string expression %s: %w", expr, err)
	}
	if ret == nil {
		return "", nil
	}
	if str, ok := ret.(string); ok {
		return str, nil
	}
	return "", fmt.Errorf("expected a string expression, got %T when evaluating %s", ret, expr)
}

func EvalBool(ctx context.Context, env map[string]string, data map[string]any, expr any) (bool, error) {
	ret, err := translate(ctx, env, data, expr)
	if err != nil {
		return false, err
	}
	if ret == nil {
		return false, nil
	}
	switch v := ret.(type) {
	case string:
		return strings.Contains(strings.ToLower(v), "t"), nil
	case bool:
		return v, nil
	default:
		return false, fmt.Errorf("expected a boolean expression, got %T when evaluating %v", ret, expr)
	}
}

func EvalAny(ctx context.Context, env map[string]string, data map[string]any, expr any) (any, error) {
	return translate(ctx, env, data, expr)
}

func EvalObject(ctx context.Context, env map[string]string, data map[string]any, expr any) (any, error) {
	ret, err := translate(ctx, env, data, expr)
	if err != nil {
		return nil, err
	}
	if ret == nil {
		return map[string]any{}, nil
	}
	return ret, nil
}

func translate(ctx context.Context, env map[string]string, data map[string]any, expr any) (any, error) {
	switch expr := (expr).(type) {
	case nil:
		return nil, nil
	case []any:
		result := make([]any, len(expr))
		for i, item := range expr {
			res, err := translate(ctx, env, data, item)
			if err != nil {
				return nil, err
			}
			result[i] = res
		}
		return result, nil
	case map[string]any:
		result := make(map[string]any)
		for key, value := range expr {
			res, err := translate(ctx, env, data, value)
			if err != nil {
				return nil, err
			}
			result[key] = res
		}
	case string:
		return evalString(ctx, env, data, expr)
	}
	return expr, nil
}

func newRuntime(data map[string]any) (*goja.Runtime, error) {
	runtime := goja.New()
	for key, value := range data {
		if err := runtime.Set(key, value); err != nil {
			return nil, fmt.Errorf("failed to set variable %s: %w", key, err)
		}
	}
	return runtime, nil
}

func evalString(_ context.Context, env map[string]string, data map[string]any, expr string) (any, error) {
	if strings.TrimSpace(expr) == "" {
		return "", nil
	}

	if strings.HasPrefix(expr, "${") && strings.HasSuffix(expr, "}") {
		envVal, ok := Lookup(env, expr[2:len(expr)-1])
		if ok {
			return envVal, nil
		}
		runtime, err := newRuntime(data)
		if err != nil {
			return nil, err
		}
		val, err := runtime.RunString(expr[2 : len(expr)-1])
		if err != nil {
			return nil, fmt.Errorf("failed to evaluate expression %s: %w", expr, err)
		}
		if val.String() == "undefined" {
			return nil, fmt.Errorf("expression resulted in a javascript undefined, check for a missing reference in expression %q", expr)
		}
		return val.Export(), nil
	}

	runtime, err := newRuntime(data)
	if err != nil {
		return nil, err
	}

	var lastErr error
	return Expand(expr, func(name string) string {
		if lastErr != nil {
			return name
		}
		envVal, ok := Lookup(env, name)
		if ok {
			return envVal
		}
		val, err := runtime.RunString(name)
		if err != nil {
			lastErr = err
			return ""
		}
		nativeVal := val.Export()
		switch nativeVal := nativeVal.(type) {
		case string:
			return nativeVal
		default:
			result, err := json.Marshal(nativeVal)
			if err != nil {
				lastErr = err
				return ""
			}
			return string(result)
		}
	}), lastErr
}

func EvalList(ctx context.Context, env map[string]string, data map[string]any, expr any) ([]any, error) {
	val, err := translate(ctx, env, data, expr)
	if err != nil {
		return nil, fmt.Errorf("failed to evaluate list: %w", err)
	}
	switch val := val.(type) {
	case []any:
		return val, nil
	case nil:
		return nil, nil
	default:
		return nil, fmt.Errorf("expected a list, got %T", val)
	}
}
