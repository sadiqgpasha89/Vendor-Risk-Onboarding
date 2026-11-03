# Secrets Configuration Guide

## Overview

The secrets management system provides secure storage and retrieval of sensitive data like API keys, passwords, and tokens.

## Directory Structure

```
secrets/
├── .key                              # Encryption key (auto-generated)
├── openai_api_key.json              # OpenAI API key
├── langsmith_api_key.json           # LangSmith API key
├── langfuse_keys.json               # LangFuse credentials
├── database_password.json           # Database credentials
└── ...
```

## Usage Examples

### Initialize Secrets Manager

```python
from src.config.secrets_manager import get_secrets_manager

# Auto-selects backend based on environment
secrets = get_secrets_manager()

# Or explicitly use file backend with encryption
from src.config.secrets_manager import FileSecretsBackend, SecretsManager

backend = FileSecretsBackend(base_path="secrets", encrypt=True)
secrets = SecretsManager(backend)
```

### Store Secrets

```python
# Store API key
secrets.store_secret(
    name="openai_api_key",
    value="sk-...",
    secret_type="api_key",
    description="OpenAI API key for production",
    tags=["production", "external"],
    metadata={"service": "openai", "version": "v1"}
)

# Store database connection string
secrets.store_secret(
    name="postgres_conn",
    value="postgresql://user:pass@host:5432/db",
    secret_type="connection_string",
    tags=["database", "production"]
)
```

### Retrieve Secrets

```python
# Get secret value
api_key = secrets.get_secret("openai_api_key")

# Get full secret object
secret_obj = secrets.get_secret_object("openai_api_key")
print(f"Created: {secret_obj.created_at}")
print(f"Tags: {secret_obj.tags}")
```

### Manage Secrets

```python
# List all secrets
all_secrets = secrets.list_secrets()

# List secrets by type
api_keys = secrets.list_secrets(secret_type="api_key")

# List secrets by tag
prod_secrets = secrets.get_secrets_by_tag("production")

# Update secret
secrets.update_secret("openai_api_key", "sk-new-key")

# Delete secret
secrets.delete_secret("openai_api_key")

# Export metadata (without values)
secrets.export_secrets_metadata("secrets_audit.json")

# Clear cache
secrets.clear_cache()
```

## Production Setup

In production, use environment-based secrets:

```python
from src.config.secrets_manager import EnvironmentSecretsBackend, SecretsManager

backend = EnvironmentSecretsBackend(prefix="VENDOR_RISK_")
secrets = SecretsManager(backend)
```

Set environment variables:
```bash
export VENDOR_RISK_OPENAI_API_KEY="sk-..."
export VENDOR_RISK_LANGSMITH_KEY="..."
export VENDOR_RISK_POSTGRES_CONN="postgresql://..."
```

## Development Setup

For development, use encrypted file storage:

```bash
# Secrets are stored in secrets/ directory
# First run generates .key file (add to .gitignore)
python -c "from src.config.secrets_manager import get_secrets_manager; sm = get_secrets_manager()"
```

Add to .gitignore:
```
secrets/.key
secrets/*.json
```

## Secret Types

| Type | Example | Use Case |
|------|---------|----------|
| api_key | sk-... | External APIs (OpenAI, LangSmith) |
| token | Bearer xxx | Authentication tokens |
| password | db_pass | Passwords for services |
| connection_string | postgresql://... | Database connections |
| credential | username:password | Combined credentials |

## Security Best Practices

1. **Encryption**: Always enable encryption for file-based secrets
2. **Access Control**: Restrict permissions on secrets directory (600 on secrets files)
3. **Rotation**: Regularly rotate API keys and passwords
4. **Audit**: Export and review secrets metadata periodically
5. **Environment**: Use environment variables in production
6. **Tagging**: Use tags to organize and categorize secrets
7. **Cache**: Clear cache when secrets might have changed
8. **.gitignore**: Never commit secret files to version control

## Integration with Configuration

```python
# In settings.py
from src.config.secrets_manager import get_secrets_manager

secrets = get_secrets_manager()

class Settings:
    # Retrieve from secrets
    openai_api_key = secrets.get_secret("openai_api_key")
    langsmith_key = secrets.get_secret("langsmith_key")
    database_url = secrets.get_secret("postgres_conn")
```

## Monitoring and Audit

```python
# Check secret metadata
secret_obj = secrets.get_secret_object("openai_api_key")
print(f"Last updated: {secret_obj.updated_at}")
print(f"Created by: {secret_obj.created_by}")
print(f"Metadata: {secret_obj.metadata}")

# Export audit trail
secrets.export_secrets_metadata("audit_trail.json")
```

## Troubleshooting

### Encryption Key Not Found

```python
# The key is auto-generated on first use
# Location: secrets/.key
# Add to .gitignore
```

### Permission Denied

```bash
# Fix permissions on secrets directory
chmod 600 secrets/*.json
chmod 700 secrets/
```

### Secrets Not Loading

```python
# Clear cache and try again
secrets.clear_cache()
value = secrets.get_secret("key_name")

# Or check backend configuration
for secret_name in secrets.list_secrets():
    print(f"Found secret: {secret_name}")
```
