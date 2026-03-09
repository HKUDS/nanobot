//go:build !package

package ui

import "embed"

//go:embed all:*dist
var FS embed.FS
