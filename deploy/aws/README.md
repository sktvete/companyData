# AWS deploy — Moonstocks + equity-os

Region: **eu-north-1** · Account: **550822830987**

## 1. RDS Postgres

Deploy (replace VPC/subnet/SG IDs from your ECS cluster):

```bash
aws cloudformation deploy \
  --region eu-north-1 \
  --stack-name moonstocks-rds \
  --template-file deploy/aws/rds-moonstocks.yaml \
  --parameter-overrides \
    VpcId=vpc-XXXX \
    PrivateSubnetIds=subnet-a,subnet-b \
    EcsSecurityGroupId=sg-XXXX \
  --capabilities CAPABILITY_IAM
```

Note the output `DatabaseUrlSecretArn` — equity-os reads `MOONSTOCKS_DATABASE_URL` from Secrets Manager.

## 2. Build & push images

From Windows (after `aws configure` or SSO):

```powershell
.\scripts\deploy_moonstocks_ecr.ps1
```

Or manually:

```bash
# equity-os
aws ecr get-login-password --region eu-north-1 | docker login --username AWS --password-stdin 550822830987.dkr.ecr.eu-north-1.amazonaws.com
docker build -t 550822830987.dkr.ecr.eu-north-1.amazonaws.com/equity-os-prod:latest .
docker push 550822830987.dkr.ecr.eu-north-1.amazonaws.com/equity-os-prod:latest

# analyzer (from moonstocks-ai-analyzer/)
docker build -t 550822830987.dkr.ecr.eu-north-1.amazonaws.com/moonstocks-ai-analyzer-prod:latest ./moonstocks-ai-analyzer
docker push 550822830987.dkr.ecr.eu-north-1.amazonaws.com/moonstocks-ai-analyzer-prod:latest
```

## 3. ECS task definitions

Update image tags in:

- `deploy/aws/equity-os-task-definition.json`
- `moonstocks-ai-analyzer/.aws/task-definition.json`

Register:

```bash
aws ecs register-task-definition --cli-input-json file://deploy/aws/equity-os-task-definition.json --region eu-north-1
aws ecs register-task-definition --cli-input-json file://moonstocks-ai-analyzer/.aws/task-definition.json --region eu-north-1
```

Create/update ECS services on the same cluster as moonstocks (service connect: `equity-os-prod:3000`, `moonstocks-ai-analyzer-prod:8000`).

## 4. Cutover

1. Deploy **equity-os** service (new ALB or reuse moonstocks-api target group on port 3000).
2. Set analyzer `ANALYSIS_API_BASE_URL=http://equity-os-prod:3000`.
3. Point **moonstocks-app** API base URL to equity-os LB.
4. Set equity-os `MOONSTOCKS_API_URL` to the public Moonstocks app URL.
5. Smoke: `POST /api/moonstocks/DECK.US/trigger`, wait ~3 min, `GET /api/moonstocks/DECK.US`.
6. Scale **moonstocks-api** (C#) to 0.

## GitHub Actions (optional)

Set repository **variables** (same pattern as `moonstocks-ai-analyzer`):

- `AWS_REGION`, `ECR_REPOSITORY` (e.g. `equity-os-prod`), `CONTAINER_NAME`, `ECS_SERVICE`, `ECS_CLUSTER`

Set **secret** `AWS_ROLE_ARN` (OIDC). Pushes to `main`/`master` that touch `web/`, `Dockerfile`, etc. run `.github/workflows/deploy-equity-os.yml`.

## Secrets checklist

| Secret | Used by |
|--------|---------|
| `moonstocks/rds/database_url` | equity-os `MOONSTOCKS_DATABASE_URL` |
| `moonstocks-analyzer-ai-secrets-prod` | EODHD, OPENAI, optional ANTHROPIC |
| App ingest | `ANALYZER_API_KEY` on analyzer + equity-os |
