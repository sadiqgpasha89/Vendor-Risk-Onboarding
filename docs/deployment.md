# Deployment Guide

## Overview

This guide covers deploying the Vendor Risk Onboarding system to various environments.

## Prerequisites

- Docker and Docker Compose
- Kubernetes cluster (for K8s deployment)
- Cloud account (AWS/Azure/GCP)
- SSL certificates for production

## Local Development

### Quick Start with Docker Compose

```bash
# Clone repository
git clone <repo-url>
cd vendor-risk-onboarding

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Start all services
docker-compose up -d

# Initialize database
docker-compose exec api python -c "from src.db.connection import init_db; init_db()"

# Access application
curl http://localhost:8000/health
```

### Accessing Services

- **API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **Jaeger Tracing**: http://localhost:16686
- **Flower (Celery)**: http://localhost:5555
- **MLFlow**: http://localhost:5000

## Production Deployment

### Environment Setup

```bash
# Create production environment file
cp .env.example .env.production

# Configure for production
export APP_ENV=production
export DEBUG=false
export LOG_LEVEL=WARNING
export DATABASE_URL=postgresql://user:pass@prod-db:5432/vendor_risk
export REDIS_URL=redis://prod-redis:6379/0
export OPENAI_API_KEY=<your-api-key>
```

### Database Migration

```bash
# Create database
createdb vendor_risk

# Run migrations
docker-compose exec api alembic upgrade head

# Backup database
pg_dump vendor_risk > backup.sql
```

### Security Configuration

```bash
# Generate secure secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Set in environment
export SECRET_KEY=<generated-key>

# Ensure SSL/TLS
# Configure nginx reverse proxy with SSL
# Update CORS_ORIGINS for production domain
```

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (1.24+)
- kubectl configured
- Helm 3.x
- PostgreSQL operator or managed database

### Deployment Steps

```bash
# Create namespace
kubectl create namespace vendor-risk

# Create secrets
kubectl create secret generic app-secrets \
  -n vendor-risk \
  --from-literal=secret-key=<your-secret> \
  --from-literal=openai-api-key=<your-key> \
  --from-literal=database-url=postgresql://...

# Install using Helm (if helm chart available)
helm install vendor-risk ./helm \
  -n vendor-risk \
  -f values.yaml

# Or deploy manually
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/ingress.yaml

# Check deployment
kubectl get pods -n vendor-risk
kubectl logs -n vendor-risk deployment/api
```

### Example Kubernetes Manifest

```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: vendor-risk
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
      - name: api
        image: vendor-risk:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: database-url
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: openai-api-key
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: vendor-risk
spec:
  type: LoadBalancer
  selector:
    app: api
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
```

## Cloud Deployment

### AWS Deployment

```bash
# Using ECR for container registry
aws ecr create-repository --repository-name vendor-risk

# Push image
docker build -t vendor-risk:latest .
docker tag vendor-risk:latest <account>.dkr.ecr.<region>.amazonaws.com/vendor-risk:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/vendor-risk:latest

# Create RDS PostgreSQL database
aws rds create-db-instance \
  --db-instance-identifier vendor-risk-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username admin \
  --master-user-password <password>

# Create ElastiCache Redis
aws elasticache create-cache-cluster \
  --cache-cluster-id vendor-risk-redis \
  --engine redis \
  --cache-node-type cache.t3.micro

# Deploy to ECS Fargate
aws ecs create-service \
  --cluster vendor-risk \
  --service-name api \
  --task-definition vendor-risk:1 \
  --desired-count 3 \
  --launch-type FARGATE
```

### Azure Deployment

```bash
# Create resource group
az group create --name vendor-risk-rg --location eastus

# Create App Service
az appservice plan create \
  --name vendor-risk-plan \
  --resource-group vendor-risk-rg \
  --sku B3 --is-linux

# Create web app
az webapp create \
  --resource-group vendor-risk-rg \
  --plan vendor-risk-plan \
  --name vendor-risk-app \
  --deployment-container-image-name <image>

# Create PostgreSQL
az postgres server create \
  --resource-group vendor-risk-rg \
  --name vendor-risk-db \
  --admin-user dbadmin \
  --admin-password <password>

# Create Cache for Redis
az redis create \
  --resource-group vendor-risk-rg \
  --name vendor-risk-redis
```

### GCP Deployment

```bash
# Create GKE cluster
gcloud container clusters create vendor-risk \
  --zone us-central1-a \
  --num-nodes 3

# Create Cloud SQL instance
gcloud sql instances create vendor-risk-db \
  --database-version POSTGRES_15 \
  --tier db-f1-micro

# Create Memorystore Redis
gcloud redis instances create vendor-risk-redis \
  --size=1 \
  --region=us-central1

# Deploy to GKE
kubectl apply -f k8s/
```

## Monitoring & Logging

### Prometheus Setup

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'vendor-risk-api'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### ELK Stack Setup

```bash
# Start ELK
docker-compose -f docker-compose.elk.yml up

# Configure Logstash to ingest logs
# View logs in Kibana at http://localhost:5601
```

## Backup & Disaster Recovery

### Database Backup

```bash
# Automated daily backup
0 2 * * * pg_dump vendor_risk | gzip > /backups/vendor_risk_$(date +\%Y\%m\%d).sql.gz

# Restore from backup
gunzip -c backup.sql.gz | psql vendor_risk
```

### S3 Backup

```bash
# Backup database to S3
aws s3 cp backup.sql.gz s3://vendor-risk-backups/$(date +%Y%m%d)/

# Lifecycle policy for retention
aws s3api put-bucket-lifecycle-configuration \
  --bucket vendor-risk-backups \
  --lifecycle-configuration file://lifecycle.json
```

## Performance Tuning

### Database Optimization

```sql
-- Create indexes
CREATE INDEX idx_vendor_status ON vendors(status);
CREATE INDEX idx_workflow_vendor_time ON workflows(vendor_id, created_at);

-- Analyze query performance
EXPLAIN ANALYZE SELECT * FROM vendors WHERE status = 'pending';

-- Vacuum and analyze
VACUUM ANALYZE;
```

### Application Tuning

```python
# Increase connection pool
DATABASE_POOL_SIZE=50
DATABASE_MAX_OVERFLOW=100

# Increase worker concurrency
CELERY_WORKER_CONCURRENCY=8

# Enable response caching
REDIS_CACHE_TTL=7200
```

## Troubleshooting

### Common Issues

**Issue**: High database connection errors
```bash
# Check connection pool
SELECT count(*) FROM pg_stat_activity;

# Increase pool size in .env
DATABASE_POOL_SIZE=100
```

**Issue**: Slow API responses
```bash
# Check metrics
curl http://localhost:8000/api/v1/monitoring/metrics

# Enable query logging
DATABASE_ECHO=true
```

**Issue**: Celery task queue backlog
```bash
# Scale workers
docker-compose up -d --scale celery_worker=5

# Monitor queue
flower --port=5555
```

## Maintenance

### Regular Tasks

- **Daily**: Monitor error rates, check logs
- **Weekly**: Review performance metrics, database size
- **Monthly**: Clean old logs, update dependencies
- **Quarterly**: Security audit, disaster recovery drill

### Updating Application

```bash
# Pull latest code
git pull

# Update dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Restart services
docker-compose restart
```

## Support & Troubleshooting

See [README.md](../README.md) for support information.
