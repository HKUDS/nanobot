default: build

GIT_TAG := $(shell git describe --tags --exact-match 2>/dev/null | xargs -I {} echo -X 'github.com/nanobot-ai/nanobot/pkg/version.Tag={}')
GO_LD_FLAGS := "-s -w $(GIT_TAG)"

build:
	go generate ./...
	go build -ldflags=$(GO_LD_FLAGS) -o bin/nanobot .

sandbox-test:
	cd packages/sandbox/src/lib && docker build -t sandbox-test .

sandbox-test-no-cache:
	cd packages/sandbox/src/lib && docker build --no-cache -t sandbox-test .

validate:
	@echo "Running Go validation checks..."
	@echo "==> Running go fmt..."
	@if [ -n "$$(gofmt -l .)" ]; then \
		echo "Error: The following files are not formatted:"; \
		gofmt -l .; \
		echo "Please run 'gofmt -w .' to format them."; \
		exit 1; \
	fi
	@echo "==> Running go vet..."
	@go vet ./...
	@echo "==> Running go test..."
	@go test ./...
	@echo "==> Checking go mod tidy..."
	@go mod tidy
	@if [ -n "$$(git status --porcelain go.mod go.sum)" ]; then \
		echo "Error: go.mod or go.sum is not tidy. Please run 'go mod tidy'."; \
		git diff go.mod go.sum; \
		exit 1; \
	fi
	@echo ""
	@echo "Running UI validation checks..."
	@echo "==> Installing UI dependencies..."
	@pnpm install --frozen-lockfile
	@echo "==> Running UI type check..."
	@pnpm run ci
	@echo "✓ All validation checks passed!"

.PHONY: build sandbox-test sandbox-test-no-cache validate
