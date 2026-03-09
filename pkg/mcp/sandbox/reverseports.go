package sandbox

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"sync"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/reverseproxy"
	"github.com/nanobot-ai/nanobot/pkg/supervise"
	"github.com/nanobot-ai/nanobot/pkg/version"
)

func startReversePort(ctx context.Context, targetContainerName string, port int, cancel func()) error {
	for range 10 {
		if err := exec.Command("docker", "start", targetContainerName).Run(); err == nil {
			break
		}
	}

	server, err := reverseproxy.NewTLSServer(port)
	if err != nil {
		return fmt.Errorf("failed to create reverse proxy server for port %d: %w", port, err)
	}

	targetPort, err := server.Start(ctx)
	if err != nil {
		return fmt.Errorf("failed to start reverse proxy server for port %d: %w", port, err)
	}

	ca, err := server.GetCACertPEM()
	if err != nil {
		return fmt.Errorf("failed to get CA certificate for port %d: %w", port, err)
	}

	cert, key, err := server.GenerateClientCert()
	if err != nil {
		return fmt.Errorf("failed to generate client certificate for port %d: %w", port, err)
	}

	containerName := fmt.Sprintf("%s-%d", targetContainerName, port)
	cmd := supervise.Cmd(ctx, "docker", "run", "--rm",
		"--network", "container:"+targetContainerName,
		"--name", containerName,
		"-e", "LISTEN_PORT",
		"-e", "TARGET_PORT",
		"-e", "CA_CERT",
		"-e", "CLIENT_CERT",
		"-e", "CLIENT_KEY",
		version.BaseImage,
		"proxy",
	)
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("LISTEN_PORT=%d", port),
		fmt.Sprintf("TARGET_PORT=%d", targetPort),
		fmt.Sprintf("CA_CERT=%s", ca),
		fmt.Sprintf("CLIENT_CERT=%s", cert),
		fmt.Sprintf("CLIENT_KEY=%s", key),
	)

	// just hold open stdin for supervisor
	_, err = cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdin pipe for reverse proxy container for port %d: %w", port, err)
	}

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdout pipe for reverse proxy container for port %d: %w", port, err)
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("failed to get stderr pipe for reverse proxy container for port %d: %w", port, err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start reverse proxy container for port %d: %w", port, err)
	}

	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		PipeOut(ctx, stdoutPipe, containerName)
	}()
	go func() {
		defer wg.Done()
		PipeOut(ctx, stderrPipe, containerName)
	}()
	go func() {
		defer func() {
			cancel()
		}()
		wg.Wait()
		if err := cmd.Wait(); err != nil {
			slog.Error("reverse proxy container exited with error", "port", port, "error", err)
		}
	}()
	return nil
}
