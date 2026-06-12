package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/spf13/cobra"

	"luum-agent-os/cmd/cos/internal/project"
)

// projectCoverageSchema is the schema_version a project coverage artifact
// must declare for cos status to trust its summary.
const projectCoverageSchema = "cos-project-coverage.v1"

// projectInstallMeta mirrors the fields of .cognitive-os/install-meta.json
// that the project status report uses.
type projectInstallMeta struct {
	Mode            string `json:"mode"`
	Version         string `json:"version"`
	Harness         string `json:"harness"`
	ProjectName     string `json:"project_name"`
	RulesInstalled  int    `json:"rules_installed"`
	HooksInstalled  int    `json:"hooks_installed"`
	SkillsInstalled int    `json:"skills_installed"`
}

// componentCount pairs the count recorded at install time with the count
// currently on disk so drift between the two is visible.
type componentCount struct {
	Installed int `json:"installed"`
	OnDisk    int `json:"on_disk"`
}

// coverageStatus is the summary block of a cos-project-coverage.v1 artifact.
// Present is false when no valid artifact exists.
type coverageStatus struct {
	Present bool `json:"present"`
	Total   int  `json:"total"`
	Wired   int  `json:"wired"`
	Partial int  `json:"partial"`
	Missing int  `json:"missing"`
}

// projectStatus is the full project-mode status payload for cos status.
type projectStatus struct {
	Mode           string         `json:"mode"`
	ProjectDir     string         `json:"project_dir"`
	Name           string         `json:"name"`
	Version        string         `json:"version"`
	Profile        string         `json:"profile"`
	Harness        string         `json:"harness"`
	Phase          string         `json:"phase"`
	Hooks          componentCount `json:"hooks"`
	Rules          componentCount `json:"rules"`
	Skills         componentCount `json:"skills"`
	Cosd           string         `json:"cosd"`
	Coverage       coverageStatus `json:"coverage"`
	ActiveSessions *int           `json:"active_sessions"`
}

// buildProjectStatus assembles the project-mode status for an installed
// Cognitive OS project rooted at root.
func buildProjectStatus(root string) (projectStatus, error) {
	metaPath := filepath.Join(root, ".cognitive-os", "install-meta.json")
	data, err := os.ReadFile(metaPath)
	if err != nil {
		return projectStatus{}, fmt.Errorf("reading %s: %w", metaPath, err)
	}
	var meta projectInstallMeta
	if err := json.Unmarshal(data, &meta); err != nil {
		return projectStatus{}, fmt.Errorf("parsing %s: %w", metaPath, err)
	}

	cfg := project.LoadConfig(root)
	cosDir := filepath.Join(root, ".cognitive-os")

	return projectStatus{
		Mode:       "project",
		ProjectDir: root,
		Name:       cfg.Name,
		Version:    meta.Version,
		Profile:    meta.Mode,
		Harness:    meta.Harness,
		Phase:      cfg.Phase,
		Hooks: componentCount{
			Installed: meta.HooksInstalled,
			OnDisk:    countComponentFiles(filepath.Join(cosDir, "hooks")),
		},
		Rules: componentCount{
			Installed: meta.RulesInstalled,
			OnDisk:    countComponentFiles(filepath.Join(cosDir, "rules")),
		},
		Skills: componentCount{
			Installed: meta.SkillsInstalled,
			// On-disk count covers only the cos/ kernel namespace so it
			// matches install-meta's skills_installed definition (a dir
			// containing SKILL.md, not "_"/"."-prefixed). Other namespaces
			// (extensions, project skills) are deliberately excluded.
			OnDisk: countSkillDirs(filepath.Join(cosDir, "skills", "cos")),
		},
		Cosd:           cosdState(root),
		Coverage:       loadProjectCoverage(root),
		ActiveSessions: activeSessionCount(root),
	}, nil
}

// countComponentFiles counts installed component files under dir. Symlinks
// are resolved and deduplicated by resolved path, so a symlink and its
// target inside the same tree count once. Names starting with "_" or "."
// are skipped: helper libraries (for example hooks/cos/_lib) and OS
// metadata files are not installed primitives.
func countComponentFiles(dir string) int {
	seen := map[string]bool{}
	var walk func(string)
	walk = func(current string) {
		entries, err := os.ReadDir(current)
		if err != nil {
			return
		}
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasPrefix(name, "_") || strings.HasPrefix(name, ".") {
				continue
			}
			path := filepath.Join(current, name)
			resolved, err := filepath.EvalSymlinks(path)
			if err != nil {
				continue // broken symlink
			}
			info, err := os.Stat(resolved)
			if err != nil {
				continue
			}
			if info.IsDir() {
				walk(path)
				continue
			}
			seen[resolved] = true
		}
	}
	walk(dir)
	return len(seen)
}

// countSkillDirs counts skill directories (those containing a SKILL.md)
// under dir, deduplicating symlinked directories by resolved path. Loose
// files such as CATALOG.md are not skills and are not counted.
func countSkillDirs(dir string) int {
	seen := map[string]bool{}
	var walk func(string)
	walk = func(current string) {
		entries, err := os.ReadDir(current)
		if err != nil {
			return
		}
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasPrefix(name, "_") || strings.HasPrefix(name, ".") {
				continue
			}
			path := filepath.Join(current, name)
			resolved, err := filepath.EvalSymlinks(path)
			if err != nil {
				continue
			}
			info, err := os.Stat(resolved)
			if err != nil || !info.IsDir() {
				continue
			}
			if _, err := os.Stat(filepath.Join(resolved, "SKILL.md")); err == nil {
				seen[resolved] = true
				continue
			}
			walk(path)
		}
	}
	walk(dir)
	return len(seen)
}

// cosdState reports the daemon state for the project:
//   - "absent":  no .cognitive-os/cosd directory at all
//   - "stopped": cosd directory exists but no live pid
//   - "running": pid file exists and the process answers signal 0
func cosdState(root string) string {
	cosdDir := filepath.Join(root, ".cognitive-os", "cosd")
	info, err := os.Stat(cosdDir)
	if err != nil || !info.IsDir() {
		return "absent"
	}
	data, err := os.ReadFile(filepath.Join(cosdDir, "runtime", "cosd.pid"))
	if err != nil {
		return "stopped"
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || pid <= 0 {
		return "stopped"
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return "stopped"
	}
	if err := proc.Signal(syscall.Signal(0)); err != nil {
		return "stopped"
	}
	return "running"
}

// loadProjectCoverage reads .cognitive-os/reports/coverage-latest.json and
// returns its summary when the artifact declares the expected schema.
func loadProjectCoverage(root string) coverageStatus {
	path := filepath.Join(root, ".cognitive-os", "reports", "coverage-latest.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return coverageStatus{}
	}
	var payload struct {
		SchemaVersion string `json:"schema_version"`
		Summary       struct {
			Total   int `json:"total"`
			Wired   int `json:"wired"`
			Partial int `json:"partial"`
			Missing int `json:"missing"`
		} `json:"summary"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return coverageStatus{}
	}
	if payload.SchemaVersion != projectCoverageSchema {
		return coverageStatus{}
	}
	return coverageStatus{
		Present: true,
		Total:   payload.Summary.Total,
		Wired:   payload.Summary.Wired,
		Partial: payload.Summary.Partial,
		Missing: payload.Summary.Missing,
	}
}

// activeSessionCount returns the number of entries in
// .cognitive-os/sessions/active-sessions.json, or nil when the ledger is
// absent or unreadable.
func activeSessionCount(root string) *int {
	data, err := os.ReadFile(filepath.Join(root, ".cognitive-os", "sessions", "active-sessions.json"))
	if err != nil {
		return nil
	}
	var payload struct {
		Sessions []json.RawMessage `json:"sessions"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil
	}
	count := len(payload.Sessions)
	return &count
}

// runProjectStatus prints the project-mode status report.
func runProjectStatus(cmd *cobra.Command, root string) error {
	status, err := buildProjectStatus(root)
	if err != nil {
		return err
	}

	out := cmd.OutOrStdout()
	if statusJSON {
		enc := json.NewEncoder(out)
		enc.SetIndent("", "  ")
		return enc.Encode(status)
	}

	phase := status.Phase
	if phase == "" {
		phase = "(not set)"
	}

	fmt.Fprintf(out, "\nCognitive OS project status — %s\n\n", status.ProjectDir)
	fmt.Fprintf(out, "  Project:  %s\n", status.Name)
	fmt.Fprintf(out, "  Version:  %s\n", status.Version)
	fmt.Fprintf(out, "  Profile:  %s\n", status.Profile)
	fmt.Fprintf(out, "  Harness:  %s\n", status.Harness)
	fmt.Fprintf(out, "  Phase:    %s\n\n", phase)
	fmt.Fprintf(out, "  Hooks:    %s\n", formatComponentCount(status.Hooks))
	fmt.Fprintf(out, "  Rules:    %s\n", formatComponentCount(status.Rules))
	fmt.Fprintf(out, "  Skills:   %s\n\n", formatComponentCount(status.Skills))
	fmt.Fprintf(out, "  cosd:     %s\n", status.Cosd)
	if status.Coverage.Present {
		fmt.Fprintf(out, "  Coverage: %d total — %d wired, %d partial, %d missing\n",
			status.Coverage.Total, status.Coverage.Wired, status.Coverage.Partial, status.Coverage.Missing)
	} else {
		fmt.Fprintf(out, "  Coverage: no coverage artifact — run: cos tui --operate refresh-coverage --confirm\n")
	}
	if status.ActiveSessions != nil {
		fmt.Fprintf(out, "  Sessions: %d active\n", *status.ActiveSessions)
	} else {
		fmt.Fprintf(out, "  Sessions: no session ledger\n")
	}
	fmt.Fprintln(out)
	return nil
}

// formatComponentCount renders "42 (42 on disk)" so install-time vs on-disk
// drift is visible at a glance.
func formatComponentCount(c componentCount) string {
	return fmt.Sprintf("%d (%d on disk)", c.Installed, c.OnDisk)
}
