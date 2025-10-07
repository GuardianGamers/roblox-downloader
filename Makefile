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
	@echo "  make deploy [STAGE=dev|test|prod]      - Deploy full stack to AWS (build+push+deploy)"
	@echo "  make deploy-only [STAGE=dev|test|prod] - Deploy CloudFormation only (no Docker rebuild)"
	@echo "  make delete [STAGE=dev|test|prod]      - Delete stack from AWS"
	@echo "  make logs [STAGE=dev|test|prod]        - Tail ECS task logs"
	@echo "  make run-task [STAGE=dev|test|prod]    - Manually run ECS task"
	@echo "  make status [STAGE=dev|test|prod]      - Show stack status"
	@echo ""
	@echo "Docker image management:"
	@echo "  make docker-build [STAGE=dev]           - Build Docker image"
	@echo "  make docker-run [STAGE=dev]             - Run container locally (for testing)"
	@echo "  make docker-check [STAGE=dev]           - Run version check only (local test)"
	@echo "  make docker-info [STAGE=dev]            - Show image information"
	@echo "  make docker-clean [STAGE=dev]           - Remove Docker images"
	@echo ""
	@echo "  make help                               - Show this help message"
	@echo ""
	@echo "Current settings:"
	@echo "  STAGE: $(STAGE) (default: dev, options: dev, test, prod)"
	@echo "  VERSION: $(VERSION) (default: latest)"
	@echo "  LOCAL_IMAGE: $(LOCAL_IMAGE):$(VERSION)"
	@echo "  STACK_NAME: $(STACK_NAME)"

# Docker image management
.PHONY: docker-build
docker-build:
	@BUILD_TIMESTAMP=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	echo "Building roblox-downloader locally with timestamp: $$BUILD_TIMESTAMP"; \
	docker build \
		--build-arg BUILD_TIMESTAMP="$$BUILD_TIMESTAMP" \
		--build-arg BUILD_VERSION="$(VERSION)" \
		-t $(LOCAL_IMAGE):$(VERSION) \
		-f $(DOCKERFILE) .
	@echo "Image built locally: $(LOCAL_IMAGE):$(VERSION)"

# Docker run targets (for local testing - use existing image)
.PHONY: docker-run
docker-run:
	@echo "Running Docker container locally (for testing)..."
	@mkdir -p ./downloads
	docker run --rm \
		-e PYTHONUNBUFFERED=1 \
		-e AWS_REGION=$(AWS_REGION) \
		-e AWS_ACCESS_KEY_ID \
		-e AWS_SECRET_ACCESS_KEY \
		-e AWS_SESSION_TOKEN \
		-e BUCKET_NAME=test-bucket-local \
		-v $(PWD)/downloads:/downloads \
		-v ~/.aws:/root/.aws:ro \
		$(LOCAL_IMAGE):$(VERSION)

.PHONY: docker-check
docker-check:
	@echo "Checking Roblox version (local test)..."
	docker run --rm \
		-e PYTHONUNBUFFERED=1 \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads --check-only

.PHONY: docker-custom
docker-custom:
	@echo "Running with custom arguments: $(ARGS)"
	@mkdir -p ./downloads
	docker run --rm \
		-v $(PWD)/downloads:/downloads \
		$(LOCAL_IMAGE):$(VERSION) \
		python download_roblox.py --output-dir /downloads $(ARGS)

# Standalone ECR push (not typically needed, use 'make push' instead)
.PHONY: docker-push-ecr
docker-push-ecr: docker-build
	@echo "Pushing local image to ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	aws ecr describe-repositories --repository-names $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null 2>&1 || aws ecr create-repository --repository-name $(LOCAL_IMAGE) --region $(AWS_REGION) --output text > /dev/null
	docker tag $(LOCAL_IMAGE):$(VERSION) $(ECR_IMAGE):$(VERSION)
	docker push $(ECR_IMAGE):$(VERSION)
	@echo "Image deployed: $(ECR_IMAGE):$(VERSION)"

.PHONY: docker-info
docker-info:
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
		echo "  ❌ Image not found. Run 'make docker-build' first."; \
	fi
	@echo ""
	@echo "💡 To view build info at runtime, check /app/build_info.txt inside container"

.PHONY: docker-clean
docker-clean:
	@echo "Removing Docker images..."
	@docker rmi $(LOCAL_IMAGE):$(VERSION) 2>/dev/null || echo "Image $(LOCAL_IMAGE):$(VERSION) not found"
	@echo "Cleanup complete"

# AWS deployment targets
.PHONY: validate
validate:
	@echo "Validating CloudFormation template..."
	aws cloudformation validate-template --template-body file://template.yaml > /dev/null
	@echo "Template is valid!"

.PHONY: build
build: docker-build
	@echo "Tagging image for ECR..."
	docker tag $(LOCAL_IMAGE):$(VERSION) $(ECR_IMAGE):latest

.PHONY: push
push: build
	@echo "Pushing Docker image to ECR..."
	@echo "Creating ECR repository if it doesn't exist..."
	@aws ecr describe-repositories --repository-names roblox-downloader-$(STAGE) --region $(AWS_REGION) > /dev/null 2>&1 || \
		aws ecr create-repository \
			--repository-name roblox-downloader-$(STAGE) \
			--region $(AWS_REGION) \
			--image-scanning-configuration scanOnPush=true \
			--tags Key=Environment,Value=$(STAGE) Key=Project,Value=roblox-downloader
	@echo "Logging into ECR..."
	@aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	@echo "Pushing image..."
	docker push $(ECR_IMAGE):latest
	@echo "Image pushed: $(ECR_IMAGE):latest"

.PHONY: deploy
deploy: push
	@echo "Deploying CloudFormation stack (STAGE=$(STAGE))..."
	@echo "Docker image already pushed to: $(ECR_IMAGE):latest"
	aws cloudformation deploy \
		--template-file template.yaml \
		--stack-name $(STACK_NAME) \
		--parameter-overrides Stage=$(STAGE) \
		--capabilities CAPABILITY_NAMED_IAM \
		--tags Stage=$(STAGE) Project=roblox-downloader
	@echo "Deployment complete!"

.PHONY: deploy-only
deploy-only:
	@echo "Deploying CloudFormation stack WITHOUT rebuilding Docker image (STAGE=$(STAGE))..."
	@echo "Using existing ECR image: $(ECR_IMAGE):latest"
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

