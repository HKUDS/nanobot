package mcp

import (
	"context"
	"fmt"
	"io"
	"maps"
	"net"
	"os"
	"os/exec"
	"slices"
	"strings"
	"sync"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/envvar"
	"github.com/nanobot-ai/nanobot/pkg/mcp/sandbox"
	"github.com/nanobot-ai/nanobot/pkg/supervise"
	"github.com/nanobot-ai/nanobot/pkg/system"
)

type Runner struct {
	lock    sync.Mutex
	running map[string]Server
}

type streamResult struct {
	cmd    *exec.Cmd
	Stdout io.Reader
	Stdin  io.Writer
	Close  func()
}

func (r *Runner) newCommand(ctx context.Context, currentEnv map[string]string, root func(context.Context) ([]Root, error), config Server) (Server, *sandbox.Cmd, error) {
	var publishPorts []string
	ports := config.Ports
	if len(ports) == 0 {
		// If no ports are specified, use the default port
		ports = []string{"mcp"}
	}
	if currentEnv == nil {
		currentEnv = make(map[string]string)
	} else {
		currentEnv = maps.Clone(currentEnv)
	}
	for _, port := range ports {
		l, err := net.Listen("tcp4", "localhost:0")
		if err != nil {
			return config, nil, fmt.Errorf("failed to allocate port for %s: %w", port, err)
		}
		addrString := l.Addr().String()
		_, portStr, err := net.SplitHostPort(addrString)
		if err != nil {
			_ = l.Close()
			return config, nil, fmt.Errorf("failed to get port for %s, addr %s: %w", port, addrString, err)
		}
		if err := l.Close(); err != nil {
			return config, nil, fmt.Errorf("failed to close listener for %s, addr %s: %w", port, addrString, err)
		}
		publishPorts = append(publishPorts, portStr)
		currentEnv["port:"+port] = portStr
		currentEnv["nanobot:port:"+port] = portStr
	}

	config.BaseURL = envvar.ReplaceString(currentEnv, config.BaseURL)

	command, args, env := envvar.ReplaceEnv(currentEnv, config.Command, config.Args, config.Env)
	if !config.Sandboxed || command == "nanobot" {
		if command == "nanobot" {
			command = system.Bin()
		}
		cmd := supervise.Cmd(ctx, command, args...)
		cmd.Dir = envvar.ReplaceString(currentEnv, config.Cwd)
		cmd.Env = append(cleanOSEnv(), env...)
		return config, &sandbox.Cmd{
			Cmd: cmd,
		}, nil
	}

	var (
		rootPaths []sandbox.Root
		roots     []Root
		err       error
	)

	if root != nil {
		roots, err = root(ctx)
		if err != nil {
			return config, nil, fmt.Errorf("failed to get roots: %w", err)
		}
	}

	for _, root := range roots {
		if strings.HasPrefix(root.URI, "file://") {
			rootPaths = append(rootPaths, sandbox.Root{
				Name: root.Name,
				Path: root.URI[7:],
			})
		}
	}

	cmd, err := sandbox.NewCmd(ctx, sandbox.Command{
		PublishPorts: publishPorts,
		ReversePorts: config.ReversePorts,
		Roots:        rootPaths,
		Command:      command,
		Workdir:      envvar.ReplaceString(config.Env, config.Workdir),
		Args:         args,
		Env:          slices.Collect(maps.Keys(config.Env)),
		BaseImage:    config.Image,
		Dockerfile:   config.Dockerfile,
		Source:       sandbox.Source(config.Source),
	})
	if err != nil {
		return config, nil, fmt.Errorf("failed to create sandbox command: %w", err)
	}

	cmd.Env = append(cleanOSEnv(), env...)
	return config, cmd, nil
}

var allowedEnv = map[string]bool{
	"PATH": true,
	"HOME": true,
	"USER": true,
}

func cleanOSEnv() []string {
	// Clean up the environment variables to avoid issues with sandboxing
	env := os.Environ()
	cleanedEnv := make([]string, 0, len(allowedEnv))
	for _, e := range env {
		k, _, found := strings.Cut(e, "=")
		if found && allowedEnv[k] {
			// Only allow specific environment variables
			cleanedEnv = append(cleanedEnv, e)
		}
	}
	return cleanedEnv
}

func (r *Runner) doRun(ctx context.Context, serverName string, config Server, cmd *sandbox.Cmd) (Server, error) {
	// hold open stdin for the supervisor
	_, err := cmd.StdinPipe()
	if err != nil {
		return config, fmt.Errorf("failed to get stdin pipe: %w", err)
	}
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		return config, fmt.Errorf("failed to get stdout pipe: %w", err)
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		return config, fmt.Errorf("failed to get stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return config, fmt.Errorf("failed to start command: %w", err)
	}

	if r.running == nil {
		r.running = make(map[string]Server)
	}
	r.running[serverName] = config

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		sandbox.PipeOut(ctx, stdoutPipe, serverName)
	}()

	go func() {
		defer wg.Done()
		sandbox.PipeOut(ctx, stderrPipe, serverName)
	}()

	go func() {
		wg.Wait()
		err := cmd.Wait()
		if err != nil {
			slog.Error("command exited with error", "server", serverName, "error", err)
		}
		r.lock.Lock()
		delete(r.running, serverName)
		r.lock.Unlock()
	}()

	return config, nil
}

func (r *Runner) doStream(ctx context.Context, serverName string, cmd *sandbox.Cmd) (*streamResult, error) {
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to get stdout pipe: %w", err)
	}
	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to get stdin pipe: %w", err)
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("failed to get stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("failed to start command: %w", err)
	}

	go func() {
		sandbox.PipeOut(ctx, stderrPipe, serverName)
		if err := cmd.Wait(); err != nil {
			slog.Error("command exited with error", "server", serverName, "error", err)
		}
	}()

	return &streamResult{
		cmd:    cmd.Cmd,
		Stdout: stdoutPipe,
		Stdin:  stdinPipe,
	}, nil
}

func (r *Runner) Run(ctx context.Context, roots func(ctx context.Context) ([]Root, error), env map[string]string, serverName string, config Server) (Server, error) {
	r.lock.Lock()
	defer r.lock.Unlock()

	if c, ok := r.running[serverName]; ok {
		return c, nil
	}

	newConfig, cmd, err := r.newCommand(ctx, env, roots, config)
	if err != nil {
		return config, err
	}

	return r.doRun(ctx, serverName, newConfig, cmd)
}

func (r *Runner) Stream(ctx context.Context, roots func(context.Context) ([]Root, error), env map[string]string, serverName string, config Server) (*streamResult, error) {
	ctx, cancel := context.WithCancel(ctx)
	_, cmd, err := r.newCommand(ctx, env, roots, config)
	if err != nil {
		cancel()
		return nil, err
	}
	result, err := r.doStream(ctx, serverName, cmd)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to run stdio command: %w", err)
	}
	result.Close = cancel
	return result, nil
}
