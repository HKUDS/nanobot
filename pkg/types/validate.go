package types

import (
	"fmt"
)

func checkDup(seen map[string]string, category string, keys ...string) error {
	for _, k := range keys {
		if oldCategory, ok := seen[k]; ok {
			return fmt.Errorf("duplicate name [%s] used for both [%s] and [%s]", k, oldCategory, category)
		}
		seen[k] = category
	}
	return nil
}
