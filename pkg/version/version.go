package version

import (
	"fmt"
	"runtime/debug"
)

var (
	Tag       = "v0.0.0-dev"
	BaseImage = "ghcr.io/nanobot-ai/nanobot:main"
	Name      = "nanobot"
)

func Get() Version {
	return NewVersion(Tag)
}

type Version struct {
	Tag    string `json:"tag,omitempty"`
	Commit string `json:"commit,omitempty"`
	Dirty  bool   `json:"dirty,omitempty"`
}

func NewVersion(tag string) Version {
	v := Version{
		Tag: tag,
	}
	v.Commit, v.Dirty = GitCommit()
	return v
}

func (v Version) String() string {
	if len(v.Commit) < 12 {
		return v.Tag
	} else if v.Dirty {
		return fmt.Sprintf("%s-%s-dirty", v.Tag, v.Commit[:8])
	}

	return fmt.Sprintf("%s+%s", v.Tag, v.Commit[:8])
}

func GitCommit() (commit string, dirty bool) {
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return "", false
	}
	for _, setting := range bi.Settings {
		switch setting.Key {
		case "vcs.modified":
			dirty = setting.Value == "true"
		case "vcs.revision":
			commit = setting.Value
		}
	}

	return
}
