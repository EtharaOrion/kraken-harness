// cobra_extractor — dump kubectl subcommand help as a YAML tree.
//
// Compiled during the bootstrap phase (see kwok backend Dockerfile) and
// invoked once per (repo, ref) to produce a machine-readable spec that
// KubectlCobraYamlSource consumes to build CliSpec + TestIntent objects.
// The YAML files it emits are the standard cobra/doc GenYamlTree layout:
// one <command>.yaml per (sub)command, each with name, synopsis, description,
// example, usage, and a flags list. Skips config/plugin which mutate state
// on construction.
//
// Usage:  cobra_extractor -out /path/to/bundle-dir
package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/spf13/cobra/doc"
	"k8s.io/cli-runtime/pkg/genericiooptions"
	"k8s.io/kubectl/pkg/cmd"
)

func main() {
	root := flag.String("root", "", "path to kubectl source root (unused; kept for consistency)")
	out := flag.String("out", ".", "output directory for YAML bundle")
	flag.Parse()
	_ = root // unused; kubectl imports are static

	iostreams := genericiooptions.IOStreams{In: os.Stdin, Out: os.Stdout, ErrOut: os.Stderr}
	kubectlCmd := cmd.NewDefaultKubectlCommand()
	kubectlCmd.SetIn(iostreams.In)
	kubectlCmd.SetOut(iostreams.Out)
	kubectlCmd.SetErr(iostreams.ErrOut)

	// Skip-list: subcommands that mutate global state on construction or are
	// noisy (config touches kubeconfig; plugin scans PATH).
	skipList := map[string]bool{"config": true, "plugin": true}
	for i := len(kubectlCmd.Commands()) - 1; i >= 0; i-- {
		sub := kubectlCmd.Commands()[i]
		if skipList[sub.Name()] {
			kubectlCmd.RemoveCommand(sub)
		}
	}

	if err := os.MkdirAll(*out, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "mkdir %s: %v\n", *out, err)
		os.Exit(1)
	}
	if err := doc.GenYamlTree(kubectlCmd, *out); err != nil {
		fmt.Fprintf(os.Stderr, "GenYamlTree failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "wrote YAML tree to %s\n", *out)
}
