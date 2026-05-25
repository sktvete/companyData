# AWS Deployment Guide — equity-os

## Architecture

```
Internet
  │
  ▼
ALB (HTTPS 443 / HTTP 80→redirect)
  │
  ▼
ECS Fargate  ─── equity-os task (Flask/Gunicorn, port 3000)
  │                  │
  │                  ├── EFS /app/outputs  (fundamentals_cache, price DB)
  │                  └── RDS Postgres      (moonstocks analyses)
  │
  └─── analyzer task (FastAPI/uvicorn, port 8000) ← internal, Cloud Map DNS
         └── RDS Postgres (same DB)

ECR  ──── equity-os image  (built + pushed by GitHub Actions on push to master)
     ──── analyzer image
```

**Region**: `eu-north-1` (Stockholm)
**Account**: `550822830987`

---

## Stack order

Deploy in this order (each stack references outputs from the previous):

```
1. efs.yaml              ← EFS filesystem (created once, survives updates)
2. rds-moonstocks.yaml   ← RDS PostgreSQL (created once)
3. ecs-analyzer.yaml     ← analyzer service (internal, Cloud Map)
4. ecs-equity-os.yaml    ← equity-os service + ALB (references outputs from 1-3)
```

---

## Pre-requisites

- AWS CLI configured: `aws configure` or an IAM role with the required permissions
- An existing ECS cluster (or create one: `aws ecs create-cluster --cluster-name moonstocks-prod`)
- A VPC with at least 2 public subnets (ALB) and 2 private subnets (ECS tasks, RDS)
- A NAT Gateway so private tasks can reach the internet (EODHD, OpenAI)
- ECR repositories for `equity-os` and `moonstocks-analyzer`
- (Optional) ACM certificate for HTTPS

---

## Step 1 — Create ECR repositories

```bash
REGION=eu-north-1
ACCOUNT=550822830987

aws ecr create-repository --repository-name equity-os           --region $REGION
aws ecr create-repository --repository-name moonstocks-analyzer --region $REGION
```

---

## Step 2 — Store secrets in Secrets Manager

```bash
REGION=eu-north-1

# EODHD API key
aws secretsmanager create-secret \
  --name equity-os/eodhd-api-key \
  --secret-string '{"EODHD_API_KEY":"<your-key>"}' \
  --region $REGION

# OpenAI API key
aws secretsmanager create-secret \
  --name equity-os/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"<your-key>"}' \
  --region $REGION

# Shared analyzer API key (random string, used for equity-os ↔ analyzer auth)
ANALYZER_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
aws secretsmanager create-secret \
  --name equity-os/analyzer-api-key \
  --secret-string "{\"ANALYZER_API_KEY\":\"$ANALYZER_KEY\"}" \
  --region $REGION
```

Note the ARNs returned — you'll need them in Steps 4 and 5.

---

## Step 3 — Deploy EFS

```bash
aws cloudformation deploy \
  --stack-name equity-os-efs \
  --template-file deploy/aws/efs.yaml \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    PrivateSubnetIds="subnet-aaaa,subnet-bbbb" \
    EcsSecurityGroupId=sg-xxxxxxxx \
  --capabilities CAPABILITY_IAM \
  --region $REGION
```

---

## Step 4 — Deploy RDS

```bash
aws cloudformation deploy \
  --stack-name moonstocks-rds \
  --template-file deploy/aws/rds-moonstocks.yaml \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    PrivateSubnetIds="subnet-aaaa,subnet-bbbb" \
    EcsSecurityGroupId=sg-xxxxxxxx \
  --capabilities CAPABILITY_IAM \
  --region $REGION

# Get the database URL secret ARN:
aws cloudformation describe-stacks \
  --stack-name moonstocks-rds \
  --query "Stacks[0].Outputs[?OutputKey=='DatabaseUrlSecretArn'].OutputValue" \
  --output text \
  --region $REGION
```

---

## Step 5 — Build & push images (first time)

The GitHub Actions workflow (`deploy-equity-os.yml`) handles this automatically on push.
For the initial deploy, push manually:

```bash
# equity-os
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

docker build -t equity-os .
docker tag  equity-os $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/equity-os:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/equity-os:latest

# moonstocks-analyzer (OpenAI-only slim build)
docker build -t moonstocks-analyzer ./moonstocks-ai-analyzer
docker tag  moonstocks-analyzer $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/moonstocks-analyzer:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/moonstocks-analyzer:latest

# moonstocks-analyzer WITH Claude support (add --build-arg WITH_CLAUDE=true)
# docker build --build-arg WITH_CLAUDE=true -t moonstocks-analyzer ./moonstocks-ai-analyzer
```

---

## Step 6 — Deploy analyzer service

```bash
aws cloudformation deploy \
  --stack-name moonstocks-analyzer \
  --template-file deploy/aws/ecs-analyzer.yaml \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    PrivateSubnetIds="subnet-aaaa,subnet-bbbb" \
    EcrImageUri=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/moonstocks-analyzer:latest \
    EcsClusterArn=arn:aws:ecs:$REGION:$ACCOUNT:cluster/moonstocks-prod \
    EquityOsTaskSgId=sg-xxxxxxxx \
    OpenAiApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/openai-api-key \
    EohdApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/eodhd-api-key \
    AnalyzerApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/analyzer-api-key \
    DatabaseUrlSecretArn=arn:aws:secretsmanager:...:moonstocks/rds/database_url \
    EquityOsBaseUrl=http://equity-os.internal:3000 \
  --capabilities CAPABILITY_IAM \
  --region $REGION
```

---

## Step 7 — Deploy equity-os service + ALB

```bash
aws cloudformation deploy \
  --stack-name equity-os \
  --template-file deploy/aws/ecs-equity-os.yaml \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    PublicSubnetIds="subnet-pub1,subnet-pub2" \
    PrivateSubnetIds="subnet-aaaa,subnet-bbbb" \
    EcrImageUri=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/equity-os:latest \
    EcsClusterArn=arn:aws:ecs:$REGION:$ACCOUNT:cluster/moonstocks-prod \
    EfsStackName=equity-os-efs \
    EohdApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/eodhd-api-key \
    OpenAiApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/openai-api-key \
    DatabaseUrlSecretArn=arn:aws:secretsmanager:...:moonstocks/rds/database_url \
    AnalyzerApiKeySecretArn=arn:aws:secretsmanager:...:equity-os/analyzer-api-key \
    AnalyzerServiceUrl=http://analyzer.equity-os.local:8000 \
    CertificateArn=arn:aws:acm:$REGION:$ACCOUNT:certificate/xxxx \
  --capabilities CAPABILITY_IAM \
  --region $REGION
```

Get the ALB DNS name and point your domain CNAME to it:
```bash
aws cloudformation describe-stacks \
  --stack-name equity-os \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" \
  --output text
```

---

## Step 8 — Seed EFS with initial data

On first deploy the EFS is empty so the screener will start with no data.
Populate it before (or immediately after) the first deploy:

```bash
# Upload outputs from local machine to S3, then sync to EFS at next restart
aws s3 sync outputs/ s3://my-equity-os-bucket/equity-os/outputs/ \
  --exclude "*.db-shm" --exclude "*.db-wal" --exclude ".chatgpt_session.json"

# Then set OUTPUTS_S3_URI in the equity-os stack and restart the task.
# On startup, the entrypoint syncs from S3 → EFS.
```

---

## GitHub Actions CI/CD

After the infrastructure is in place, set these in your GitHub repo
(Settings → Secrets and variables → Actions):

| Type | Name | Value |
|------|------|-------|
| Variable | `AWS_REGION` | `eu-north-1` |
| Variable | `ECR_REPOSITORY` | `equity-os` |
| Variable | `CONTAINER_NAME` | `equity-os` |
| Variable | `ECS_SERVICE` | `equity-os` |
| Variable | `ECS_CLUSTER` | `moonstocks-prod` |
| Secret | `AWS_ROLE_ARN` | `arn:aws:iam::550822830987:role/github-actions-deploy` |

Every push to `master` then automatically: builds the image → pushes to ECR → updates the ECS service → waits for health check.

---

## Updating screener data

When you run a new screener analysis locally, sync it to EFS via S3:

```bash
# Upload new outputs to S3
aws s3 sync outputs/ s3://my-equity-os-bucket/equity-os/outputs/ \
  --exclude "*.db-shm" --exclude "*.db-wal" --exclude ".chatgpt_session.json"

# Restart the ECS task so it picks up the new data on next startup S3 sync
aws ecs update-service --cluster moonstocks-prod --service equity-os --force-new-deployment
```

---

## Cost estimate (eu-north-1, 1 replica each)

| Service | Size | Est. monthly |
|---------|------|-------------|
| ECS equity-os | 2 vCPU / 4 GB | ~$50 |
| ECS analyzer | 1 vCPU / 2 GB | ~$25 |
| RDS db.t4g.micro | PostgreSQL 16 | ~$15 |
| ALB | ~1 LCU | ~$20 |
| EFS | 21 MB → grows | ~$1 |
| ECR | 2 repos, ~1 GB | ~$2 |
| **Total** | | **~$113/month** |

Scale down analyzer to 0 tasks when not in use to save ~$25/month.
