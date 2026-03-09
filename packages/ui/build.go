//go:build package

package main

import (
	"log"
	"os"
	"os/exec"
)

func run(name string, args ...string) {
	cmd := exec.Command(name, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Fatal(err)
	}
}

func main() {
	if err := os.Chdir("packages/ui"); err != nil {
		log.Fatal(err)
	}
	if err := os.RemoveAll("dist"); err != nil {
		log.Fatal(err)
	}
	if err := os.RemoveAll("build"); err != nil {
		log.Fatal(err)
	}
	run("pnpm", "i")
	run("pnpm", "run", "build")
	if err := os.Rename("build", "dist"); err != nil {
		log.Fatal(err)
	}
}
