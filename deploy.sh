#!/bin/bash
# =============================================================================
# Micro Mentor Backend — Deploy to AWS ECS Fargate
# Run this from the project root: bash deploy.sh
# Requires: Docker (running), AWS CLI configured as micro-mentor-deploy user
# =============================================================================
set -e

AWS_REGION="us-east-1"
AWS_ACCOUNT="886009424627"
ECR_REPO="$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/micro-mentor-backend"
ECS_CLUSTER="micro-mentor-cluster"
ECS_SERVICE="micro-mentor-service"
TASK_FAMILY="micro-mentor-task"

echo "=== Step 1: Login to ECR ==="
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_REPO

echo ""
echo "=== Step 2: Build Docker image ==="
docker build --platform linux/amd64 -t micro-mentor-backend:latest .

echo ""
echo "=== Step 3: Tag and push to ECR ==="
docker tag micro-mentor-backend:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

echo ""
echo "=== Step 4: Register new task definition revision ==="
NEW_TASK_DEF=$(aws ecs register-task-definition \
  --region $AWS_REGION \
  --cli-input-json file://task-definition.json \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)
echo "New task definition: $NEW_TASK_DEF"

echo ""
echo "=== Step 5: Update ECS service to use new task definition ==="
aws ecs update-service \
  --region $AWS_REGION \
  --cluster $ECS_CLUSTER \
  --service $ECS_SERVICE \
  --task-definition "$NEW_TASK_DEF" \
  --force-new-deployment \
  --query 'service.{status:status,desired:desiredCount}' \
  --output table

echo ""
echo "=== Step 6: Wait for service to stabilise ==="
echo "Waiting for deployment to complete (this takes ~2 minutes)..."
aws ecs wait services-stable \
  --region $AWS_REGION \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE
echo "Service is stable."

echo ""
echo "=== Step 7: Verify ==="
aws ecs describe-services \
  --region $AWS_REGION \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount,taskDef:taskDefinition}' \
  --output table

echo ""
echo "=== Deploy complete ==="
