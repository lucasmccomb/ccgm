BINARY     := ccgm-agents
VERSION    ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS    := -X main.version=$(VERSION)
BUILD_DIR  := dist
INSTALL_DIR := $(HOME)/.ccgm/bin

.PHONY: build test lint build-all clean install

## build: Compile for the current platform.
build:
	go build -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY) ./cmd/$(BINARY)

## test: Run all tests.
test:
	go test ./...

## lint: Run golangci-lint (must be installed).
lint:
	golangci-lint run ./...

## build-all: Cross-compile for darwin-arm64, darwin-amd64, and linux-amd64.
build-all:
	GOOS=darwin  GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY)-darwin-arm64  ./cmd/$(BINARY)
	GOOS=darwin  GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY)-darwin-amd64  ./cmd/$(BINARY)
	GOOS=linux   GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY)-linux-amd64   ./cmd/$(BINARY)

## clean: Remove build artifacts.
clean:
	rm -rf $(BUILD_DIR)

## install: Install binary to ~/.ccgm/bin/.
install: build
	mkdir -p $(INSTALL_DIR)
	cp $(BUILD_DIR)/$(BINARY) $(INSTALL_DIR)/$(BINARY)
	@echo "Installed to $(INSTALL_DIR)/$(BINARY)"
