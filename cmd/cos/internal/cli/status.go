package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"luum-agent-os/cmd/cos/internal/manifest"
	"luum-agent-os/cmd/cos/internal/project"
	"luum-agent-os/cmd/cos/internal/ui"
)

var (
	statusJSON        bool
	statusChangedOnly bool
	statusProjectDir  string
)

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show project install status or package release status",
	Long: `Show Cognitive OS status. The command is mode-aware:

Project mode (installed consumer projects):
  When the root has .cognitive-os/install-meta.json and no
  packages/*/cos-package.yaml manifests, shows this project's Cognitive
  OS install state: version, profile, harness, phase, hook/rule/skill
  counts (recorded at install time vs on disk), cosd state, coverage
  summary, and active sessions. A bare packages/ directory (for example
  a JS monorepo) does not switch modes.

Release mode (the Cognitive OS source repository):
  When at least one packages/*/cos-package.yaml manifest exists, shows
  the release status of all packages: the version from cos-package.yaml,
  the latest scoped git tag, and the number of commits since that tag.

Examples:
  cos status                    Auto-detect mode and show status
  cos status --json             Output as JSON
  cos status --project-dir DIR  Inspect a specific project root
  cos status --changed-only     Release mode: only packages with unreleased changes`,
	RunE: runStatus,
}

func init() {
	statusCmd.Flags().BoolVar(&statusJSON, "json", false, "Output as JSON")
	statusCmd.Flags().BoolVar(&statusChangedOnly, "changed-only", false, "Show only packages with unreleased changes (release mode)")
	statusCmd.Flags().StringVar(&statusProjectDir, "project-dir", os.Getenv("COGNITIVE_OS_PROJECT_DIR"), "Project root to inspect (defaults to $COGNITIVE_OS_PROJECT_DIR when set, else auto-detect from cwd)")
	rootCmd.AddCommand(statusCmd)
}

// PackageStatus holds the release status of a single package.
type PackageStatus struct {
	Name       string `json:"name"`
	Version    string `json:"version"`
	LastTag    string `json:"last_tag"`
	Commits    int    `json:"commits_since_tag"`
	HasChanges bool   `json:"has_changes"`
}

// discoverPackages scans the packages/ directory under projectRoot and returns
// a sorted list of PackageStatus entries. This is shared between status and
// release-all commands.
func discoverPackages(projectRoot string) ([]PackageStatus, error) {
	packagesDir := filepath.Join(projectRoot, "packages")
	entries, err := os.ReadDir(packagesDir)
	if err != nil {
		return nil, fmt.Errorf("reading packages/ directory: %w", err)
	}

	var statuses []PackageStatus
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}

		manifestPath := filepath.Join(packagesDir, entry.Name(), "cos-package.yaml")
		m, err := manifest.ParseFile(manifestPath)
		if err != nil {
			// Skip directories without a valid cos-package.yaml.
			continue
		}

		tagName := scopedTagName(m.Name, m.Version)
		lastTag, commits := getTagStatus(projectRoot, tagName, filepath.Join("packages", entry.Name()))

		statuses = append(statuses, PackageStatus{
			Name:       m.Name,
			Version:    m.Version,
			LastTag:    lastTag,
			Commits:    commits,
			HasChanges: lastTag == "" || commits > 0,
		})
	}

	sort.Slice(statuses, func(i, j int) bool {
		return statuses[i].Name < statuses[j].Name
	})

	return statuses, nil
}

// getTagStatus checks for an exact scoped git tag matching the current version.
// If found, counts commits since that tag affecting the given path.
// Returns the tag name and commit count. If no tag exists, returns ("", 0).
func getTagStatus(projectRoot, expectedTag, pkgPath string) (string, int) {
	// Check if the exact version tag exists.
	if !gitTagExistsInDir(projectRoot, expectedTag) {
		return "", 0
	}

	// Count commits since the tag that touch this package's directory.
	countCmd := exec.Command("git", "rev-list", "--count", expectedTag+"..HEAD", "--", pkgPath)
	countCmd.Dir = projectRoot
	out, err := countCmd.Output()
	if err != nil {
		return expectedTag, 0
	}

	count := 0
	fmt.Sscanf(strings.TrimSpace(string(out)), "%d", &count)
	return expectedTag, count
}

// gitTagExistsInDir checks if a git tag exists, running from the given directory.
func gitTagExistsInDir(dir, tag string) bool {
	cmd := exec.Command("git", "tag", "-l", tag)
	cmd.Dir = dir
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(output)) == tag
}

// hasPackageManifests reports whether projectRoot holds at least one
// packages/*/cos-package.yaml manifest. Mode dispatch requires this evidence:
// a bare packages/ directory (for example a JS monorepo inside a consumer
// project) must not flip cos status into release mode. Manifest evidence
// deliberately wins over install-meta so a self-hosted Cognitive OS source
// repo (which can have both) still reports release status.
func hasPackageManifests(projectRoot string) bool {
	matches, err := filepath.Glob(filepath.Join(projectRoot, "packages", "*", "cos-package.yaml"))
	return err == nil && len(matches) > 0
}

func runStatus(cmd *cobra.Command, args []string) error {
	projectRoot := statusProjectDir
	if projectRoot == "" {
		projectRoot = project.FindRootOrCwd()
	}

	if hasPackageManifests(projectRoot) {
		return runReleaseStatus(projectRoot)
	}

	metaPath := filepath.Join(projectRoot, ".cognitive-os", "install-meta.json")
	if _, err := os.Stat(metaPath); err == nil {
		return runProjectStatus(cmd, projectRoot)
	}

	manifestGlob := filepath.Join(projectRoot, "packages", "*", "cos-package.yaml")
	return fmt.Errorf(`%s is neither a Cognitive OS release workspace nor an installed Cognitive OS project

cos status has two modes:
  release mode: package release status — requires at least one %s
  project mode: this project's Cognitive OS install state — requires %s

Neither was found. Run cos status from the Cognitive OS source repository or
from an installed project, or point at one with --project-dir`,
		projectRoot, manifestGlob, metaPath)
}

// runReleaseStatus shows the release status of all packages under
// projectRoot/packages (the original cos status behavior). The text output
// starts with a header naming the resolved root so redirection via
// COGNITIVE_OS_PROJECT_DIR (or --project-dir) is always visible.
func runReleaseStatus(projectRoot string) error {
	statuses, err := discoverPackages(projectRoot)
	if err != nil {
		return err
	}

	if len(statuses) == 0 {
		if statusJSON {
			return printStatusJSON(projectRoot, statuses)
		}
		fmt.Printf("\nCognitive OS release status — %s\n", projectRoot)
		fmt.Println("No packages found in packages/")
		return nil
	}

	// Filter if --changed-only.
	if statusChangedOnly {
		var filtered []PackageStatus
		for _, s := range statuses {
			if s.HasChanges {
				filtered = append(filtered, s)
			}
		}
		statuses = filtered
	}

	if statusJSON {
		return printStatusJSON(projectRoot, statuses)
	}

	fmt.Printf("\nCognitive OS release status — %s\n", projectRoot)
	return printStatusTable(statuses)
}

// releaseStatusPayload is the release-mode --json envelope. project_dir
// identifies the resolved root so env-redirected runs are visible in
// machine-readable output too.
type releaseStatusPayload struct {
	ProjectDir string          `json:"project_dir"`
	Packages   []PackageStatus `json:"packages"`
}

func printStatusJSON(projectRoot string, statuses []PackageStatus) error {
	if statuses == nil {
		statuses = []PackageStatus{}
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(releaseStatusPayload{ProjectDir: projectRoot, Packages: statuses})
}

func printStatusTable(statuses []PackageStatus) error {
	if len(statuses) == 0 {
		fmt.Println("No packages with unreleased changes.")
		return nil
	}

	// Calculate column widths.
	maxName := len("PACKAGE")
	maxVersion := len("VERSION")
	maxTag := len("LAST TAG")
	for _, s := range statuses {
		if len(s.Name) > maxName {
			maxName = len(s.Name)
		}
		if len(s.Version) > maxVersion {
			maxVersion = len(s.Version)
		}
		tagDisplay := s.LastTag
		if tagDisplay == "" {
			tagDisplay = "(never released)"
		}
		if len(tagDisplay) > maxTag {
			maxTag = len(tagDisplay)
		}
	}

	fmt.Println()
	// Header.
	header := fmt.Sprintf("  %-*s  %-*s  %-*s  %s",
		maxName, "PACKAGE",
		maxVersion, "VERSION",
		maxTag, "LAST TAG",
		"COMMITS",
	)
	fmt.Println(ui.HeaderStyle.Render(header))
	fmt.Println(strings.Repeat("-", len(header)+4))

	// Rows.
	changed := 0
	for _, s := range statuses {
		tagDisplay := s.LastTag
		if tagDisplay == "" {
			tagDisplay = "(never released)"
		}

		commitDisplay := fmt.Sprintf("%d", s.Commits)
		if s.LastTag == "" {
			commitDisplay = "-"
		}

		var statusIcon string
		if s.HasChanges {
			statusIcon = ui.WarningStyle.Render("*")
			changed++
		} else {
			statusIcon = " "
		}

		fmt.Printf("%s %-*s  %-*s  %-*s  %s\n",
			statusIcon,
			maxName, s.Name,
			maxVersion, s.Version,
			maxTag, tagDisplay,
			commitDisplay,
		)
	}

	fmt.Println()
	if changed > 0 {
		fmt.Printf("  %s %d of %d packages have unreleased changes\n", ui.IconWarning, changed, len(statuses))
	} else {
		fmt.Printf("  %s All %d packages are up to date\n", ui.IconSuccess, len(statuses))
	}

	return nil
}
