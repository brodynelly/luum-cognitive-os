package project

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Config holds the subset of cognitive-os.yaml fields that CLI status
// surfaces need. Shared so commands read project.name / project.phase one
// way instead of re-parsing the file ad hoc.
type Config struct {
	Name  string
	Phase string
}

// LoadConfig parses cognitive-os.yaml under root and returns the project
// name and phase. The Name falls back to the root directory's base name
// when the file or the project.name field is missing. A missing file or
// unparseable YAML is not an error: status surfaces degrade gracefully.
func LoadConfig(root string) Config {
	cfg := Config{Name: filepath.Base(filepath.Clean(root))}

	data, err := os.ReadFile(filepath.Join(root, "cognitive-os.yaml"))
	if err != nil {
		return cfg
	}

	var doc struct {
		Project struct {
			Name  string `yaml:"name"`
			Phase string `yaml:"phase"`
		} `yaml:"project"`
	}
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return cfg
	}

	if doc.Project.Name != "" {
		cfg.Name = doc.Project.Name
	}
	cfg.Phase = doc.Project.Phase
	return cfg
}
