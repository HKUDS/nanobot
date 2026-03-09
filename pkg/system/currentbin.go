package system

import (
	"os"
	"os/exec"
	"path/filepath"
)

func Bin() string {
	if bin := os.Getenv("NANOBOT_BIN"); bin != "" {
		return bin
	}
	return currentBin()
}

// currentBin returns the executable of yourself to allow forking a new version of yourself
// Copied from github.com/moby/moby/pkg/reexec d25b0bd7ea6ce17ca085c54d5965eeeb66417e52
func currentBin() string {
	name := os.Args[0]
	if filepath.Base(name) == name {
		if lp, err := exec.LookPath(name); err == nil {
			return lp
		}
	}
	// handle conversion of relative paths to absolute
	if absName, err := filepath.Abs(name); err == nil {
		return absName
	}
	// if we couldn't get absolute name, return original
	// (NOTE: Go only errors on Abs() if os.Getwd fails)
	return name
}
