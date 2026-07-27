// task-router: identify the agent's Go solution file inside /workspace and
// republish it as /task_module/task_module.go so the Harbor-supplied test
// file (also package task_module) can call its symbols directly.
//
// Standalone program, standard library only (go/parser + go/ast + regexp).
// Generic-parameterized functions (`func F[T any](...)`) parse cleanly via
// go/parser — no special handling required.
//
// Contract:
//   router --expect=Name1,Name2,... --dest=/task_module/task_module.go /workspace
//
// The first .go file under the search root whose top-level declared names
// (funcs, methods, type specs, var/const) form a SUPERSET of the expected
// names wins. Its `package X` header is rewritten to `package task_module`
// and the modified source is written to --dest.
//
// Skipped: *_test.go, files inside vendor/, and --dest itself. Idempotent:
// if --dest already exists we exit 0 without re-scanning.

package main

import (
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var packageLineRe = regexp.MustCompile(`(?m)^package [A-Za-z_][A-Za-z0-9_]*`)

func main() {
	expect := flag.String("expect", "", "comma-separated top-level identifier names required")
	dest := flag.String("dest", "", "output path for the rewritten task_module.go")
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr,
			"Usage: %s --expect=Name1,Name2,... --dest=/task_module/task_module.go /workspace\n",
			os.Args[0])
		flag.PrintDefaults()
	}
	flag.Parse()

	if *expect == "" || *dest == "" || flag.NArg() != 1 {
		flag.Usage()
		os.Exit(2)
	}

	if _, err := os.Stat(*dest); err == nil {
		return
	}

	root := flag.Arg(0)
	expectedNames := splitNames(*expect)
	if len(expectedNames) == 0 {
		fmt.Fprintln(os.Stderr, "no valid identifiers in --expect")
		os.Exit(2)
	}

	absDest, err := filepath.Abs(*dest)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cannot resolve --dest: %v\n", err)
		os.Exit(2)
	}

	var scanned []string
	winner, err := findWinner(root, absDest, expectedNames, &scanned)
	if err != nil {
		fmt.Fprintf(os.Stderr, "scan failed: %v\n", err)
		os.Exit(1)
	}
	if winner == "" {
		fmt.Fprintf(os.Stderr,
			"task-router: no .go file under %s declares all of %v\nscanned %d files:\n",
			root, expectedNames, len(scanned))
		for _, p := range scanned {
			fmt.Fprintf(os.Stderr, "  %s\n", p)
		}
		os.Exit(1)
	}

	src, err := os.ReadFile(winner)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read %s: %v\n", winner, err)
		os.Exit(1)
	}
	rewritten := packageLineRe.ReplaceAllString(string(src), "package task_module")

	if err := os.MkdirAll(filepath.Dir(absDest), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "mkdir %s: %v\n", filepath.Dir(absDest), err)
		os.Exit(1)
	}
	if err := os.WriteFile(absDest, []byte(rewritten), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "write %s: %v\n", absDest, err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "task-router: %s -> %s\n", winner, absDest)
}

func splitNames(s string) []string {
	seen := make(map[string]struct{})
	var out []string
	for _, raw := range strings.Split(s, ",") {
		n := strings.TrimSpace(raw)
		if n == "" || !isIdentifier(n) {
			continue
		}
		if _, dup := seen[n]; dup {
			continue
		}
		seen[n] = struct{}{}
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

func isIdentifier(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		if i == 0 {
			if !(r == '_' || (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z')) {
				return false
			}
			continue
		}
		if !(r == '_' || (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9')) {
			return false
		}
	}
	return true
}

func findWinner(root, absDest string, expected []string, scanned *[]string) (string, error) {
	var candidates []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if d.Name() == "vendor" || d.Name() == ".git" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(d.Name(), ".go") {
			return nil
		}
		if strings.HasSuffix(d.Name(), "_test.go") {
			return nil
		}
		abs, aerr := filepath.Abs(path)
		if aerr == nil && abs == absDest {
			return nil
		}
		candidates = append(candidates, path)
		return nil
	})
	if err != nil {
		return "", err
	}

	sort.Strings(candidates)

	fset := token.NewFileSet()
	for _, p := range candidates {
		*scanned = append(*scanned, p)
		f, perr := parser.ParseFile(fset, p, nil, parser.SkipObjectResolution)
		if perr != nil {
			continue
		}
		declared := collectTopLevelNames(f)
		if hasAll(declared, expected) {
			return p, nil
		}
	}
	return "", nil
}

func collectTopLevelNames(f *ast.File) map[string]struct{} {
	out := make(map[string]struct{})
	for _, decl := range f.Decls {
		switch d := decl.(type) {
		case *ast.FuncDecl:
			// Includes methods on types — Recv is populated for methods.
			if d.Name != nil {
				out[d.Name.Name] = struct{}{}
			}
		case *ast.GenDecl:
			for _, spec := range d.Specs {
				switch s := spec.(type) {
				case *ast.TypeSpec:
					if s.Name != nil {
						out[s.Name.Name] = struct{}{}
					}
				case *ast.ValueSpec:
					for _, n := range s.Names {
						if n != nil {
							out[n.Name] = struct{}{}
						}
					}
				}
			}
		}
	}
	return out
}

func hasAll(declared map[string]struct{}, expected []string) bool {
	for _, n := range expected {
		if _, ok := declared[n]; !ok {
			return false
		}
	}
	return true
}
