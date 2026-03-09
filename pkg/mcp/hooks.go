package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"net/url"
	"slices"
	"strings"
)

type HookRunner interface {
	RunHook(ctx context.Context, in, out any, target string) (bool, error)
}

type Hooks []HookMapping

func (h *Hooks) UnmarshalJSON(data []byte) error {
	var m map[string]stringList
	if err := json.Unmarshal(data, &m); err != nil {
		return err
	}

	mappings := make([]HookMapping, 0, len(m))
	for _, key := range slices.Sorted(maps.Keys(m)) {
		def, err := parseHookDefinition(key)
		if err != nil {
			return fmt.Errorf("failed to parse hook definition %s: %w", key, err)
		}

		mappings = append(mappings, HookMapping{
			Name:    def.Name,
			Params:  def.Params,
			Targets: m[key],
		})
	}

	*h = mappings
	return nil
}

func (h Hooks) MarshalJSON() ([]byte, error) {
	if h == nil {
		return nil, nil
	}

	m := make(map[string][]string, len(h))
	for _, mapping := range h {
		m[mapping.String()] = mapping.Targets
	}

	return json.Marshal(m)
}

type stringList []string

func (s *stringList) UnmarshalJSON(data []byte) error {
	if data[0] == '[' && data[len(data)-1] == ']' {
		var raw []string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		*s = raw
	} else {
		var raw string
		if err := json.Unmarshal(data, &raw); err != nil {
			return err
		}
		var list []string
		for item := range strings.SplitSeq(raw, ",") {
			list = append(list, strings.TrimSpace(item))
		}
		*s = list
	}
	return nil
}

type HookResponseCallback[T any] = func(hook HookMapping, resp T, err error) T

func InvokeHooks[T any](ctx context.Context, r HookRunner, hooks Hooks, in *T, name string, params map[string]string, callbacks ...HookResponseCallback[T]) (T, error) {
	var (
		out     T
		current = in
		matched bool
		errs    []error
	)
	for _, mapping := range hooks {
		if mapping.Matches(name, params) {
			for _, target := range mapping.Targets {
				matched = true
				hasOutput, err := r.RunHook(ctx, current, &out, target)
				if hasOutput || err != nil {
					for _, cb := range callbacks {
						out = cb(mapping, out, err)
					}
				}
				if err != nil {
					errs = append(errs, fmt.Errorf("failed to run hook %s: %w", mapping.String(), err))
					continue
				}
				if hasOutput {
					current = &out
				}
			}
		}
	}
	if !matched {
		return *in, errors.Join(errs...)
	}
	return *current, errors.Join(errs...)
}

type HookMapping struct {
	Name    string
	Params  map[string]string
	Targets []string
}

func parseHookDefinition(data string) (result HookMapping, _ error) {
	name, queryRaw, ok := strings.Cut(data, "?")
	if ok {
		query, err := url.ParseQuery(queryRaw)
		if err != nil {
			return result, fmt.Errorf("failed to parse hook parameters: %w", err)
		}
		result.Params = make(map[string]string, len(query))
		for k, v := range query {
			if len(v) == 0 {
				continue
			} else if len(v) > 1 {
				result.Params[k] = strings.Join(v, ",")
			} else {
				result.Params[k] = v[0]
			}
		}
	}

	result.Name = name
	return
}

// Matches will indicate if the hook definition applies to the given hook definition.
// It is assumed that the `other` hook definition is fully defined.
func (h HookMapping) Matches(name string, params map[string]string) bool {
	if h.Name != name && h.Name != "*" {
		return false
	}
	for k, v := range h.Params {
		if params[k] != v {
			return false
		}
	}
	return true
}

func (h HookMapping) String() string {
	s := strings.Builder{}
	s.WriteString(h.Name)
	if len(h.Params) > 0 {
		q := make(url.Values, len(h.Params))
		for k, v := range h.Params {
			q.Add(k, v)
		}
		s.WriteString("?")
		s.WriteString(q.Encode())
	}

	return s.String()
}
