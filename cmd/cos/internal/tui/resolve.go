package tui

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// installationsRegistryPath returns the path of the global COS installation
// registry. It is a package variable so tests can inject a temporary registry.
var installationsRegistryPath = func() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".cognitive-os", "installations.json")
}

type installationRecord struct {
	Path   string `json:"path"`
	Source string `json:"source"`
}

type installationsRegistry struct {
	Installations []installationRecord `json:"installations"`
}

// resolveScript locates an allowlisted action script for the given project
// root. Installed projects do not carry the COS source scripts, so resolution
// falls back from the project tree to the recorded source checkout:
//
//  1. <root>/scripts/<name>            (COS source repo layout)
//  2. <root>/.cognitive-os/bin/<name>  (installed project-local bin)
//  3. $COS_SOURCE_DIR/scripts/<name>   (explicit source override)
//  4. <source>/scripts/<name> where <source> comes from the installation
//     registry entry whose path matches the project root
//
// The first existing executable candidate wins. When nothing resolves, the
// error lists every candidate path tried so the action is rejected with a
// diagnosable reason instead of exec'ing a missing path.
func resolveScript(root, name string) (string, error) {
	candidates := []string{
		filepath.Join(root, "scripts", name),
		filepath.Join(root, ".cognitive-os", "bin", name),
	}
	if sourceDir := strings.TrimSpace(os.Getenv("COS_SOURCE_DIR")); sourceDir != "" {
		candidates = append(candidates, filepath.Join(sourceDir, "scripts", name))
	}
	if source := registrySourceForRoot(root); source != "" {
		candidates = append(candidates, filepath.Join(source, "scripts", name))
	}
	for _, candidate := range candidates {
		if isExecutableFile(candidate) {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("script %q not found for project %s; tried: %s", name, root, strings.Join(candidates, ", "))
}

// registrySourceForRoot returns the source checkout recorded for the project
// root in the global installation registry, or "" when no entry matches.
func registrySourceForRoot(root string) string {
	path := installationsRegistryPath()
	if path == "" {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	var registry installationsRegistry
	if err := json.Unmarshal(data, &registry); err != nil {
		return ""
	}
	normalizedRoot := normalizePath(root)
	for _, install := range registry.Installations {
		if install.Path == "" || install.Source == "" {
			continue
		}
		if normalizePath(install.Path) == normalizedRoot {
			return install.Source
		}
	}
	return ""
}

// normalizePath returns the absolute, symlink-resolved form of path so
// registry entries match relative roots (e.g. --project-dir .) and symlinked
// roots (e.g. /tmp -> /private/tmp on macOS). When symlink resolution fails
// (path missing, permission), it falls back to the absolute cleaned form.
func normalizePath(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = filepath.Clean(path)
	}
	if resolved, err := filepath.EvalSymlinks(abs); err == nil {
		return resolved
	}
	return abs
}

func isExecutableFile(path string) bool {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return false
	}
	return info.Mode().Perm()&0o111 != 0
}
