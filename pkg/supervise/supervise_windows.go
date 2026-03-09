package supervise

import (
	"context"
	"os/exec"

	"github.com/nanobot-ai/nanobot/pkg/system"
)

func Cmd(ctx context.Context, command string, args ...string) *exec.Cmd {
	args = append([]string{"_exec", command}, args...)
	cmd := exec.CommandContext(ctx, system.Bin(), args...)

	cmd.Cancel = func() error {
		if cmd.Process != nil {
			return cmd.Process.Kill()
		}
		return nil
	}

	return cmd
}
