package cli

import (
	"os"

	"github.com/nanobot-ai/nanobot/pkg/chat"
	"github.com/nanobot-ai/nanobot/pkg/runtime"
	"github.com/spf13/cobra"
)

type Call struct {
	File   string `usage:"File to read input from" default:"" short:"f"`
	Output string `usage:"Output format (json, pretty)" default:"pretty" short:"o"`
	n      *Nanobot
}

func NewCall(n *Nanobot) *Call {
	return &Call{
		n: n,
	}
}

func (e *Call) Customize(cmd *cobra.Command) {
	cmd.Hidden = true
	cmd.Use = "call [flags] TARGET_NAME [INPUT...]"
	cmd.Short = "Call a single tool, agent, or flow in the nanobot. Use \"nanobot targets\" to list available targets."
	cmd.Example = `
  # Run a tool, passing in a JSON object as input. Tools expect a JSON object as input.
  nanobot call server1/tool1 '{"arg1": "value1", "arg2": "value2"}'

  # Run a tool, passing in the same input as above, but using a friendly format.
  nanobot call server1/tool1 --arg1=value1 --arg2 value2

  # Run an agent from the current directory, passing in a string as input. If the input is JSON it will be based as is.
  nanobot call -c . agent1 "What is the weather like today?"
`
	cmd.Args = cobra.MinimumNArgs(1)
	cmd.Flags().SetInterspersed(false)
}

func (e *Call) Run(cmd *cobra.Command, args []string) error {
	cfg, err := e.n.ReadConfig(cmd.Context(), e.n.ConfigPath, !e.n.ExcludeBuiltInAgents)
	if err != nil {
		return err
	}
	runtime, err := e.n.GetRuntime(runtime.Options{
		MaxConcurrency: e.n.MaxConcurrency,
		DSN:            e.n.DSN(),
		ConfigDir:      e.n.ConfigPath,
	})
	if err != nil {
		return err
	}

	ctx := runtime.WithTempSession(cmd.Context(), cfg)

	result, err := runtime.CallFromCLI(ctx, args[0], args[1:]...)
	if err != nil {
		return err
	}

	if display(result, e.Output) {
		return nil
	}

	return chat.PrintResult(os.Stdout, result)
}
