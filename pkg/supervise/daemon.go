package supervise

import (
	"context"
	"os"
	"os/exec"
	"time"
)

func Daemon() error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	cmd := exec.CommandContext(ctx, os.Args[2], os.Args[3:]...)
	cmd.Stderr = os.Stderr
	cmd.Stdout = os.Stdout

	// Inherit the process group from parent (don't create new one)
	// The parent already set up the process group in Cmd()
	cmd.Cancel = func() error {
		if cmd.Process != nil {
			return cmd.Process.Kill()
		}
		return nil
	}

	processIn, err := cmd.StdinPipe()
	if err != nil {
		return err
	}

	go func() {
		var buf [4096]byte
		for {
			n, err := os.Stdin.Read(buf[:])
			if err != nil {
				break
			}
			if n > 0 {
				if _, err := processIn.Write(buf[:n]); err != nil {
					break
				}
			}
		}
		time.Sleep(5 * time.Second)
		cancel()
	}()

	return cmd.Run()
}
