// keys.go defines the key bindings for the TUI using bubbles/key.
package tui

import "github.com/charmbracelet/bubbles/key"

// KeyMap holds all named key bindings for the agent manager TUI.
type KeyMap struct {
	Up       key.Binding
	Down     key.Binding
	Enter    key.Binding
	Filter   key.Binding
	Escape   key.Binding
	Quit     key.Binding
	Help     key.Binding
	Stop     key.Binding
	Restart  key.Binding
	Kill     key.Binding
	New      key.Binding
	Tab      key.Binding
	Export   key.Binding
}

// DefaultKeyMap is the key map used when no other map is configured.
var DefaultKeyMap = KeyMap{
	Up:      key.NewBinding(key.WithKeys("k", "up"), key.WithHelp("k/↑", "up")),
	Down:    key.NewBinding(key.WithKeys("j", "down"), key.WithHelp("j/↓", "down")),
	Enter:   key.NewBinding(key.WithKeys("enter"), key.WithHelp("enter", "select")),
	Filter:  key.NewBinding(key.WithKeys("/"), key.WithHelp("/", "filter")),
	Escape:  key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "back")),
	Quit:    key.NewBinding(key.WithKeys("q", "ctrl+c"), key.WithHelp("q", "quit")),
	Help:    key.NewBinding(key.WithKeys("?"), key.WithHelp("?", "help")),
	Stop:    key.NewBinding(key.WithKeys("s"), key.WithHelp("s", "stop")),
	Restart: key.NewBinding(key.WithKeys("r"), key.WithHelp("r", "restart")),
	Kill:    key.NewBinding(key.WithKeys("x"), key.WithHelp("x", "kill")),
	New:     key.NewBinding(key.WithKeys("n"), key.WithHelp("n", "new")),
	Tab:     key.NewBinding(key.WithKeys("tab"), key.WithHelp("tab", "switch panel")),
	Export:  key.NewBinding(key.WithKeys("e"), key.WithHelp("e", "export logs")),
}
