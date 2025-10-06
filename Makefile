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
	@echo "AWS ECS Fargate deployment (recommended):"
	@echo "  make validate                           - Validate CloudFormation template"
	@echo "  make build [STAGE=dev|test|prod]       - Build Docker image"
	@echo "  make push [STAGE=dev|test|prod]        - Push image to ECR"
	@echo "  make deploy [STAGE=dev|test|prod]      - Deploy full stack to AWS"
	@echo "  make delete [STAGE=dev|test|prod]      - Delete stack from AWS"
	@echo "  make logs [STAGE=dev|test|prod]        - Tail ECS task logs"
	@echo "  make run-task [STAGE=dev|test|prod]    - Manually run ECS task"
	@echo "  make status [STAGE=dev|test|prod]      - Show stack status"
	@echo ""
	@echo "Local Docker testing:"
	@echo "  make local-build [STAGE=dev]            - Build Docker image locally"
	@echo "  make local-run [STAGE=dev]              - Run container locally"
	@echo "  make local-check [STAGE=dev]            - Run version check only"
	@echo "  make local-info [STAGE=dev]             - Show local build information"
	@echo "  make local-clean                        - Remove local Docker images"
	@echo ""
	@echo "  make help                               - Show this help message"
	@echo ""
	@echo "Current settings:"
	@echo "  STAGE: $(STAGE) (default: dev, options: dev, test, prod)"
	@echo "  VERSION: $(VERSION) (default: latest)"
	@echo "  LOCAL_IMAGE: $(LOCAL_IMAGE):$(VERSION)"
	@echo "  STACK_NAME: $(STACK_NAME)"

# Local build target
.PHONY: local-build
local-build:
	@BUILD_TIMESTAMP=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	echo "Building roblox-downloader locally with timestamp: $$BUILD_TIMESTAMP"; \
	docker build \
		--build-arg BUILD_TIMESTAMP="$$BUILD_TIMESTAMP" \
		--build-arg BUILD_VERSION="$(VERSION)" \
		-t $(LOCAL_IMAGE):$(VERSION) \
		-f $(DOCKERFILE) .
	@echo "Image built locally: $(LOCAL_IMAGE):$(VERSION)"

# Local run target - downloads and extracts to local directory
.PHONY: local-run
local-run: local-build
	@echo "Running roblox-downloader locally..."
	@mkdir -p ./downloads
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION)

# Local version check only
.PHONY: local-check
local-check: local-build
	@echo "Checking Roblox version locally..."
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads --check-only

# Local run with custom arguments
.PHONY: local-custom
local-custom: local-build
	@echo "Running locally with custom arguments: $(ARGS)"
	@mkdir -p ./downloads
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads $(ARGS)

# Local ECR push target (standalone, without SAM)
.PHONY: local-push-ecr
local-push-ecr: local-build
	@echo "Pushing local image to ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	aws ecr describe-repositories --repository-names $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null 2>&1 || aws ecr create-repository --repository-name $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null
	docker tag $(LOCAL_IMAGE):$(VERSION) $(ECR_IMAGE):$(VERSION)
	docker push $(ECR_IMAGE):$(VERSION)
	@echo "Image deployed: $(ECR_IMAGE):$(VERSION)"

# Local build info target
.PHONY: local-info
local-info:
	@echo "Local Docker Image Information (STAGE=$(STAGE)):"
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
		echo "  ❌ Image not found locally. Run 'make local-build' first."; \
	fi
	@echo ""
	@echo "💡 To view build info at runtime, check /app/build_info.txt inside container"

# Local clean target
.PHONY: local-clean
local-clean:
	@echo "Removing local Docker images..."
	@docker rmi $(LOCAL_IMAGE):$(VERSION) 2>/dev/null || echo "Image $(LOCAL_IMAGE):$(VERSION) not found"
	@echo "Cleanup complete"

# AWS deployment targets
.PHONY: validate
validate:
	@echo "Validating CloudFormation template..."
	aws cloudformation validate-template --template-body file://template.yaml > /dev/null
	@echo "Template is valid!"

.PHONY: build
build: local-build
	@echo "Tagging image for ECR..."
	docker tag $(LOCAL_IMAGE):$(VERSION) $(ECR_IMAGE):latest

.PHONY: push
push: build
	@echo "Pushing Docker image to ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	aws ecr describe-repositories --repository-names roblox-downloader-$(STAGE) --region $(AWS_REGION) > /dev/null 2>&1 || \
		aws ecr create-repository --repository-name roblox-downloader-$(STAGE) --region $(AWS_REGION)
	docker push $(ECR_IMAGE):latest
	@echo "Image pushed: $(ECR_IMAGE):latest"

.PHONY: deploy
deploy: push
	@echo "Deploying CloudFormation stack (STAGE=$(STAGE))..."
	aws cloudformation deploy \
		--template-file template.yaml \
		--stack-name $(STACK_NAME) \
		--parameter-overrides Stage=$(STAGE) \
		--capabilities CAPABILITY_NAMED_IAM \
		--tags Stage=$(STAGE) Project=roblox-downloader
	@echo "Deployment complete!"

.PHONY: delete
delete:
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

.PHONY: logs
logs:
	@echo "Fetching ECS task logs for $(STACK_NAME)..."
	@CLUSTER=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text); \
	aws logs tail /ecs/roblox-downloader-$(STAGE) --follow

.PHONY: run-task
run-task:
	@echo "Manually running ECS task..."
	@CLUSTER=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text); \
	TASK_DEF=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query 'Stacks[0].Outputs[?OutputKey==`ECSTaskDefinitionArn`].OutputValue' --output text); \
	SUBNETS=$$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=roblox-downloader-public-*-$(STAGE)" --query 'Subnets[*].SubnetId' --output text | tr '\t' ','); \
	SG=$$(aws ec2 describe-security-groups --filters "Name=tag:Name,Values=roblox-downloader-sg-$(STAGE)" --query 'SecurityGroups[0].GroupId' --output text); \
	aws ecs run-task \
		--cluster $$CLUSTER \
		--task-definition $$TASK_DEF \
		--launch-type FARGATE \
		--network-configuration "awsvpcConfiguration={subnets=[$$SUBNETS],securityGroups=[$$SG],assignPublicIp=ENABLED}" \
		--count 1
	@echo "Task started!"

.PHONY: status
status:
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

