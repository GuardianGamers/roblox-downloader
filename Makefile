# Variables
DOCKERFILE=Dockerfile

# Default stage is dev
STAGE?=dev
AWS_ACCOUNT=$(shell aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
ECR_REGISTRY=$(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com
LOCAL_IMAGE=roblox-downloader-$(STAGE)

ECR_IMAGE=$(ECR_REGISTRY)/$(LOCAL_IMAGE)

VERSION?=latest

# SAM/CloudFormation stack name
STACK_NAME=roblox-downloader-$(STAGE)

# Default target
.PHONY: help
help:
	@echo "Available commands:"
	@echo ""
	@echo "Docker commands:"
	@echo "  make build [STAGE=dev|test|prod]       - Build the Docker image"
	@echo "  make run [STAGE=dev|test|prod]         - Run the Docker container locally"
	@echo "  make run-check [STAGE=dev|test|prod]   - Run version check only"
	@echo "  make deploy [STAGE=dev|test|prod]      - Deploy the Docker image to ECR"
	@echo "  make build-info [STAGE=dev|test|prod]  - Show build information for Docker image"
	@echo "  make clean                              - Remove local Docker images"
	@echo ""
	@echo "AWS SAM commands:"
	@echo "  make sam-validate                       - Validate SAM template"
	@echo "  make sam-build [STAGE=dev|test|prod]   - Build SAM application"
	@echo "  make sam-deploy [STAGE=dev|test|prod]  - Deploy stack to AWS"
	@echo "  make sam-delete [STAGE=dev|test|prod]  - Delete stack from AWS"
	@echo "  make sam-logs [STAGE=dev|test|prod]    - Tail Lambda logs"
	@echo "  make sam-invoke [STAGE=dev|test|prod]  - Manually invoke Lambda"
	@echo "  make sam-status [STAGE=dev|test|prod]  - Show stack status"
	@echo ""
	@echo "  make help                               - Show this help message"
	@echo ""
	@echo "Current settings:"
	@echo "  STAGE: $(STAGE) (default: dev, options: dev, test, prod)"
	@echo "  VERSION: $(VERSION) (default: latest)"
	@echo "  LOCAL_IMAGE: $(LOCAL_IMAGE):$(VERSION)"
	@echo "  STACK_NAME: $(STACK_NAME)"

# Build target
.PHONY: build
build:
	@BUILD_TIMESTAMP=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	echo "Building roblox-downloader with timestamp: $$BUILD_TIMESTAMP"; \
	docker build \
		--build-arg BUILD_TIMESTAMP="$$BUILD_TIMESTAMP" \
		--build-arg BUILD_VERSION="$(VERSION)" \
		-t $(LOCAL_IMAGE):$(VERSION) \
		-f $(DOCKERFILE) .
	@echo "Image built locally: $(LOCAL_IMAGE):$(VERSION)"

# Run target - downloads and extracts to local directory
.PHONY: run
run: build
	@echo "Running roblox-downloader..."
	@mkdir -p ./downloads
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION)

# Run version check only
.PHONY: run-check
run-check: build
	@echo "Checking Roblox version..."
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads --check-only

# Run with custom arguments
.PHONY: run-custom
run-custom: build
	@echo "Running with custom arguments: $(ARGS)"
	@mkdir -p ./downloads
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads $(ARGS)

# Deploy target
.PHONY: deploy
deploy: build
	@echo "Starting ECR login..."
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	@echo "Checking/creating ECR repository..."
	aws ecr describe-repositories --repository-names $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null 2>&1 || aws ecr create-repository --repository-name $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null
	@echo "Tagging image: $(LOCAL_IMAGE):$(VERSION) as $(ECR_IMAGE):$(VERSION)"
	docker tag $(LOCAL_IMAGE):$(VERSION) $(ECR_IMAGE):$(VERSION)
	@echo "Pushing image to ECR..."
	docker push $(ECR_IMAGE):$(VERSION)
	@echo "Image deployed: $(ECR_IMAGE):$(VERSION)"

# Build info target - shows build information for Docker image
.PHONY: build-info
build-info:
	@echo "Build Information for Docker Image (STAGE=$(STAGE)):"
	@echo "================================================="
	@echo ""
	@echo "🔍 Image: $(LOCAL_IMAGE):$(VERSION)"
	@if docker image inspect $(LOCAL_IMAGE):$(VERSION) >/dev/null 2>&1; then \
		echo "  📅 Build Timestamp: $$(docker image inspect $(LOCAL_IMAGE):$(VERSION) --format '{{index .Config.Labels "build.timestamp"}}')"; \
		echo "  🏷️  Build Version: $$(docker image inspect $(LOCAL_IMAGE):$(VERSION) --format '{{index .Config.Labels "build.version"}}')"; \
		echo "  🔧 Component: $$(docker image inspect $(LOCAL_IMAGE):$(VERSION) --format '{{index .Config.Labels "build.component"}}')"; \
		echo "  📊 Image Size: $$(docker image ls $(LOCAL_IMAGE):$(VERSION) --format 'table {{.Size}}' | tail -n +2)"; \
		echo "  🆔 Image ID: $$(docker image ls $(LOCAL_IMAGE):$(VERSION) --format 'table {{.ID}}' | tail -n +2)"; \
	else \
		echo "  ❌ Image not found locally. Run 'make build' first."; \
	fi
	@echo ""
	@echo "💡 To view build info at runtime, check /app/build_info.txt inside container"

# Clean target - remove local images
.PHONY: clean
clean:
	@echo "Removing local Docker images..."
	@docker rmi $(LOCAL_IMAGE):$(VERSION) 2>/dev/null || echo "Image $(LOCAL_IMAGE):$(VERSION) not found"
	@echo "Cleanup complete"

# SAM targets
.PHONY: sam-validate
sam-validate:
	@echo "Validating SAM template..."
	sam validate --template template.yaml

.PHONY: sam-build
sam-build: build deploy
	@echo "Building SAM application..."
	sam build --template template.yaml

.PHONY: sam-deploy
sam-deploy: sam-build
	@echo "Deploying SAM application to AWS (STAGE=$(STAGE))..."
	sam deploy \
		--template template.yaml \
		--stack-name $(STACK_NAME) \
		--parameter-overrides Stage=$(STAGE) \
		--capabilities CAPABILITY_NAMED_IAM \
		--resolve-s3 \
		--no-fail-on-empty-changeset \
		--tags Stage=$(STAGE) Project=roblox-downloader

.PHONY: sam-delete
sam-delete:
	@echo "Deleting SAM stack $(STACK_NAME)..."
	@read -p "Are you sure you want to delete stack $(STACK_NAME)? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		aws cloudformation delete-stack --stack-name $(STACK_NAME); \
		echo "Waiting for stack deletion..."; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_NAME); \
		echo "Stack deleted successfully"; \
	else \
		echo "Deletion cancelled"; \
	fi

.PHONY: sam-logs
sam-logs:
	@echo "Tailing Lambda logs for $(STACK_NAME)..."
	sam logs --stack-name $(STACK_NAME) --tail

.PHONY: sam-invoke
sam-invoke:
	@echo "Invoking Lambda function..."
	aws lambda invoke \
		--function-name roblox-downloader-$(STAGE) \
		--payload '{"action":"download","extract":true,"force":false}' \
		--cli-binary-format raw-in-base64-out \
		response.json
	@echo "Response:"
	@cat response.json
	@rm response.json

.PHONY: sam-status
sam-status:
	@echo "Stack status for $(STACK_NAME):"
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].[StackStatus,LastUpdatedTime]' \
		--output table 2>/dev/null || echo "Stack not found"
	@echo ""
	@echo "Stack outputs:"
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].Outputs' \
		--output table 2>/dev/null || echo "No outputs available"

