package sandbox

import (
	"archive/tar"
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"log/slog"

	"github.com/nanobot-ai/nanobot/pkg/supervise"
	"github.com/nanobot-ai/nanobot/pkg/uuid"
	"github.com/nanobot-ai/nanobot/pkg/version"
)

var (
	validChars = regexp.MustCompile(`^[a-zA-Z0-9@:/._-]+$`)
	// Must start with git@ or https:// or ssh:// or http://
	gitRepoPrefix = regexp.MustCompile(`^(git@|https://|ssh://|http://)`)
)

type Command struct {
	PublishPorts []string
	ReversePorts []int
	Roots        []Root
	Command      string
	Workdir      string
	Args         []string
	Env          []string
	BaseImage    string
	Dockerfile   string
	Source       Source
}

type Root struct {
	Name string
	Path string
}

type Source struct {
	Repo      string
	Tag       string
	Commit    string
	Branch    string
	SubPath   string
	Reference string
}

type Cmd struct {
	*exec.Cmd
	cancel    func()
	postStart func() error
}

func (c *Cmd) Wait() error {
	if c.cancel != nil {
		defer c.cancel()
	}
	return c.Cmd.Wait()
}

func (c *Cmd) Start() error {
	if err := c.Cmd.Start(); err != nil {
		return err
	}
	if c.postStart == nil {
		return nil
	}

	if err := c.postStart(); err != nil {
		c.cancel()
		_ = c.Wait()
		return fmt.Errorf("post-start hook failed: %w", err)
	}

	return nil
}

func getBaseImage(ctx context.Context, config Command) (string, error) {
	baseImage := config.BaseImage
	if baseImage == "" {
		baseImage = version.BaseImage
	}
	if config.Dockerfile != "" {
		var err error
		baseImage, err = buildBaseImage(ctx, config)
		if err != nil {
			return "", fmt.Errorf("failed to build base image: %w", err)
		}
	}
	if config.Source.Repo != "" {
		return buildImage(ctx, baseImage, config)
	}
	if !validChars.MatchString(baseImage) {
		return "", fmt.Errorf("invalid base image: %s", baseImage)
	}
	return baseImage, nil
}

func NewCmd(ctx context.Context, sandbox Command) (*Cmd, error) {
	baseImage, err := getBaseImage(ctx, sandbox)
	if err != nil {
		return nil, err
	}

	cacheDir, err := os.UserCacheDir()
	if err != nil {
		return nil, fmt.Errorf("failed to get user cache directory: %w", err)
	}

	containerName := fmt.Sprintf("nanobot-%s", strings.Split(uuid.String(), "-")[0])
	dockerArgs := []string{"run",
		"-i", "--name", containerName}

	cacheDir = filepath.Join(cacheDir, "nanobot")
	for _, dir := range []string{".cache", ".npm", "go/pkg"} {
		if err := os.MkdirAll(filepath.Join(cacheDir, dir), 0755); err != nil {
			return nil, fmt.Errorf("failed to create cache directory: %w", err)
		}
		dockerArgs = append(dockerArgs, "-v", fmt.Sprintf("%s/%s:/mcp/%s", cacheDir, dir, dir))
	}

	dockerArgs = append(dockerArgs, "-u", fmt.Sprintf("%d:%d", os.Getuid(), os.Getgid()))
	for _, k := range sandbox.Env {
		dockerArgs = append(dockerArgs, "-e", k)
	}

	workdir := sandbox.Workdir
	for _, root := range sandbox.Roots {
		if root.Name == "cwd" && sandbox.Source.Repo == "" && sandbox.Source.SubPath == "" && workdir == "" {
			workdir = root.Path
		}
		dockerArgs = append(dockerArgs, "-v", root.Path+":"+root.Path)
	}
	if workdir != "" {
		dockerArgs = append(dockerArgs, "-w", workdir)
	}
	for _, port := range sandbox.PublishPorts {
		dockerArgs = append(dockerArgs, "-p", "127.0.0.1:"+port+":"+port)
	}
	dockerArgs = append(dockerArgs, "--", baseImage)
	if sandbox.Command != "" {
		dockerArgs = append(dockerArgs, sandbox.Command)
	}
	dockerArgs = append(dockerArgs, sandbox.Args...)

	ctx, cancel := context.WithCancel(ctx)
	cmd := supervise.Cmd(ctx, "docker", dockerArgs...)
	return &Cmd{
		cancel: cancel,
		Cmd:    cmd,
		postStart: func() error {
			for _, port := range sandbox.ReversePorts {
				if err := startReversePort(ctx, containerName, port, cancel); err != nil {
					return err
				}
			}
			return err
		},
	}, nil
}

func buildImage(ctx context.Context, baseImage string, config Command) (string, error) {
	var (
		source   = config.Source.Repo
		fragment string
		isGit    = gitRepoPrefix.MatchString(source)
	)

	if !validChars.MatchString(source) {
		return "", fmt.Errorf("invalid source repo: %s", source)
	}

	if config.Source.Commit != "" {
		fragment = config.Source.Commit
	} else if config.Source.Tag != "" {
		fragment = config.Source.Tag
	} else if config.Source.Branch != "" {
		fragment = config.Source.Branch
	}
	if config.Source.SubPath != "" {
		fragment += ":" + config.Source.SubPath
	}

	if fragment != "" && !validChars.MatchString(fragment) {
		return "", fmt.Errorf("invalid source reference: %s", fragment)
	}

	if fragment != "" {
		source = source + "#" + fragment
	}

	uid := os.Getuid()
	gid := os.Getgid()

	var cmd *exec.Cmd
	if isGit {
		slog.Info("downloading source", "source", source)
		cmd = exec.CommandContext(ctx, "docker", "build", "-q", "-")
		cmd.Stdin = dockerFileToTar(fmt.Sprintf(`FROM %s
USER %d:%d
WORKDIR /mcp
ADD %s /mcp`, baseImage, uid, gid, source))
	} else {
		slog.Info("copying source", "source", filepath.Join(config.Source.Repo, config.Source.SubPath))
		srcPath := config.Source.SubPath
		if srcPath == "" {
			srcPath = "."
		}
		cmd = exec.CommandContext(ctx, "docker", "build", "-q", "-f", "-", config.Source.Repo)
		cmd.Stdin = bytes.NewBufferString(fmt.Sprintf(`FROM %s
USER %d:%d
WORKDIR /mcp
COPY %s /mcp`, baseImage, uid, gid, srcPath))
	}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to get source %s: %w, output: %s", source, err, string(out))
	}

	id := strings.TrimSpace(string(out))
	slog.Info("built image", "image", id)
	return id, nil
}

func dockerFileToTar(dockerfile string) io.Reader {
	dockerfile = strings.ReplaceAll(dockerfile, "${NANOBOT_IMAGE}", version.BaseImage)
	var buf bytes.Buffer
	t := tar.NewWriter(&buf)
	if err := t.WriteHeader(&tar.Header{
		Name: "Dockerfile",
		Size: int64(len([]byte(dockerfile))),
	}); err != nil {
		panic(fmt.Errorf("failed to write tar header: %w", err))
	}
	if _, err := t.Write([]byte(dockerfile)); err != nil {
		panic(fmt.Errorf("failed to write Dockerfile to tar: %w", err))
	}
	if err := t.Close(); err != nil {
		panic(fmt.Errorf("failed to close tar writer: %w", err))
	}
	return &buf
}

func buildBaseImage(ctx context.Context, config Command) (string, error) {
	slog.Info("building base image")
	f, err := os.CreateTemp("", "nanobot-dockerfile-*.id")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file for dockerfile: %w", err)
	}
	if err := f.Close(); err != nil {
		return "", fmt.Errorf("failed to close temp file: %w", err)
	}

	defer func() {
		_ = os.Remove(f.Name())
	}()

	outBuf := &bytes.Buffer{}
	cmd := exec.CommandContext(ctx, "docker", "build", "--iidfile", f.Name(), "-")
	cmd.Stdin = dockerFileToTar(config.Dockerfile)
	cmd.Stdout = outBuf
	stdErr, err := cmd.StderrPipe()
	if err != nil {
		return "", fmt.Errorf("failed to get stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("failed to start docker build: %w", err)
	}

	lines := bufio.NewScanner(stdErr)
	for lines.Scan() {
		_, _ = fmt.Fprintln(os.Stderr, lines.Text())
	}

	if err := cmd.Wait(); err != nil {
		return "", fmt.Errorf("failed to build base image: %w, output: %s", err, outBuf.String())
	}

	idBytes, err := os.ReadFile(f.Name())
	return strings.TrimSpace(string(idBytes)), err
}
