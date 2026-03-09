package main

import (
	"os"

	"github.com/nanobot-ai/nanobot/pkg/cli"
	"github.com/nanobot-ai/nanobot/pkg/cmd"
	"github.com/nanobot-ai/nanobot/pkg/supervise"
)

func main() {
	if len(os.Args) > 2 && os.Args[1] == "_exec" {
		if err := supervise.Daemon(); err != nil {
			os.Exit(1)
		}
		return
	}
	cmd.Main(cli.New())
}
