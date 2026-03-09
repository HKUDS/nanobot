package cli

import (
	"os"
	"text/tabwriter"

	"github.com/nanobot-ai/nanobot/pkg/log"
	"github.com/nanobot-ai/nanobot/pkg/tools"
	"github.com/spf13/cobra"
)

type Targets struct {
	n         *Nanobot
	MCPServer []string `usage:"Specific MCP server name to query (default: all)" short:"s" name:"mcp-server"`
	Output    string   `usage:"Output format (json, yaml, table)" short:"o" default:"table"`
}

func NewTargets(n *Nanobot) *Targets {
	return &Targets{
		n: n,
	}
}

func (t *Targets) Customize(cmd *cobra.Command) {
	cmd.Hidden = true
	cmd.Use = "targets [flags]"
	cmd.Short = "List the available tools, agents, flows that can be called using \"nanobot call\"."
	cmd.Aliases = []string{"target", "t"}
	cmd.Args = cobra.NoArgs
	cmd.Example = `
  # List the tools from nanobot.yaml in the current directory
  nanobot targets -c ./nanobot.yaml
`
}

func (t *Targets) Run(cmd *cobra.Command, args []string) error {
	log.EnableMessages = false
	r, err := t.n.GetRuntime()
	if err != nil {
		return err
	}

	c, err := t.n.ReadConfig(cmd.Context(), t.n.ConfigPath, !t.n.ExcludeBuiltInAgents)
	if err != nil {
		return err
	}

	tools, err := r.ListTools(r.WithTempSession(cmd.Context(), c), tools.ListToolsOptions{
		Servers: t.MCPServer,
	})
	if err != nil {
		return err
	}

	if display(tools, t.Output) {
		return nil
	}

	tw := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	_, err = tw.Write([]byte("TARGET\tTYPE\tDESCRIPTION\n"))
	if err != nil {
		return err
	}

	for _, tool := range tools {
		for _, t := range tool.Tools {
			target := tool.Server
			targetType := "agent"
			if _, ok := c.MCPServers[target]; ok {
				targetType = "tool"
				target = target + "/" + t.Name
			}

			_, _ = tw.Write([]byte(target + "\t" + targetType + "\t" + trim(t.Description) + "\n"))
		}
	}

	return tw.Flush()
}

func trim(s string) string {
	if len(s) > 70 {
		return s[:70] + "..."
	}
	return s
}
