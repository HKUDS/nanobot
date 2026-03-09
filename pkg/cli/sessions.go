package cli

import (
	"os"
	"text/tabwriter"
	"time"

	"github.com/nanobot-ai/nanobot/pkg/session"
	"github.com/spf13/cobra"
)

type Sessions struct {
	Nanobot *Nanobot
	Output  string `usage:"Output format (json, yaml, table)" short:"o" default:"table"`
}

func NewSessions(n *Nanobot) *Sessions {
	return &Sessions{
		Nanobot: n,
	}
}

func (t *Sessions) Customize(cmd *cobra.Command) {
	cmd.Use = "sessions [flags]"
	cmd.Short = "List all existing sessions"
	cmd.Aliases = []string{"session", "s"}
	cmd.Args = cobra.NoArgs
	cmd.Hidden = true
}

func (t *Sessions) Run(cmd *cobra.Command, args []string) error {
	store, err := session.NewStoreFromDSN(t.Nanobot.DSN())
	if err != nil {
		return err
	}

	sessions, err := store.List(cmd.Context())
	if err != nil {
		return err
	}

	tw := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	_, err = tw.Write([]byte("ID\tDATE\tACCT\tDESCRIPTION\n"))
	if err != nil {
		return err
	}

	for _, session := range sessions {
		_, _ = tw.Write([]byte(session.SessionID + "\t" + session.UpdatedAt.Format(time.RFC3339) +
			"\t" + trim(session.AccountID) +
			"\t" + trim(session.Description) + "\n"))
	}

	return tw.Flush()
}
