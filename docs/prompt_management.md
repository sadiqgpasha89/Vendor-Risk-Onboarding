# Prompt Management System

## Overview

The Prompt Management System provides centralized, versioned management of LLM prompts with support for templates, versioning, and usage tracking.

## Directory Structure

```
prompts/
├── kyc/
│   ├── kyc_assessment.json
│   ├── kyc_verification.json
│   └── kyc_risk_check.json
├── risk/
│   ├── risk_assessment.json
│   ├── risk_scoring.json
│   └── risk_mitigation.json
├── compliance/
│   ├── compliance_check.json
│   ├── regulatory_review.json
│   └── audit_preparation.json
└── document/
    ├── document_analysis.json
    └── document_extraction.json
```

## Quick Start

### Initialize Prompt Registry

```python
from src.config.prompt_manager import PromptRegistry

# Load prompts from disk
registry = PromptRegistry(base_path="prompts")

# Get prompt
prompt = registry.get_prompt("kyc_assessment")
```

### Create and Register Prompts

```python
from src.config.prompt_manager import Prompt, PromptVersion

# Create new prompt
prompt = Prompt(
    name="risk_scoring",
    category="risk",
    description="Score vendor risk based on assessment data"
)

# Add version
version = PromptVersion(
    version="v1.0",
    name="risk_scoring",
    description="Initial risk scoring prompt",
    category="risk",
    template="""Analyze the following vendor information and provide a risk score:

Vendor: {{vendor_name}}
Country: {{country}}
Financial Status: {{financial_status}}
Compliance History: {{compliance_history}}

Provide:
1. Risk Score (0-100)
2. Risk Level (Low/Medium/High/Critical)
3. Key Risk Factors
4. Recommendations

Format as JSON.""",
    variables=["vendor_name", "country", "financial_status", "compliance_history"],
    model="gpt-4",
    temperature=0.3,
    max_tokens=2048,
    tags=["risk", "scoring", "vendor"],
)

prompt.add_version(version)
registry.register_prompt(prompt)
```

### Render Prompts with Variables

```python
# Render with variables
rendered = registry.render_prompt(
    prompt_name="kyc_assessment",
    variables={
        "vendor_name": "Acme Corp",
        "country": "USA",
        "registration_number": "REG123456"
    },
    version_id="v1.0"  # Optional: specify version
)

print(rendered)
```

## Prompt Structure

### Template Format

Prompts use `{{variable}}` syntax for template variables:

```
Analyze {{document_type}} for {{vendor_name}}:

Key questions:
- {{question_1}}
- {{question_2}}
- {{question_3}}
```

### PromptVersion Fields

| Field | Type | Description |
|-------|------|-------------|
| version | str | Version identifier (e.g., v1.0, v2.1) |
| name | str | Prompt name |
| category | str | Category (kyc, risk, compliance, etc.) |
| template | str | Prompt template with {{variable}} placeholders |
| variables | List[str] | List of required variables |
| model | str | Target model (gpt-4, claude-3, etc.) |
| temperature | float | Model temperature (0.0-2.0) |
| max_tokens | int | Maximum tokens for response |
| tags | List[str] | Tags for searching/filtering |
| description | str | Version description |
| created_by | str | Creator of this version |
| notes | str | Additional notes |
| is_active | bool | Whether this version is active |

## Version Management

### Add New Versions

```python
# Add improved version
registry.add_version(
    prompt_name="kyc_assessment",
    version_id="v1.1",
    template="Improved template...",
    variables=["vendor_name", "country", "registration_number"],
    model="gpt-4",
    temperature=0.2,  # More deterministic
    description="Improved KYC assessment with better structure",
    tags=["kyc", "v1.1", "improved"]
)
```

### Switch Default Version

```python
prompt = registry.get_prompt("kyc_assessment")
prompt.default_version = "v1.1"
registry._save_prompt(prompt)  # Save changes
```

### View Version History

```python
prompt = registry.get_prompt("kyc_assessment")

for version in prompt.versions:
    print(f"Version: {version.version}")
    print(f"  Created: {version.created_at}")
    print(f"  Active: {version.is_active}")
    print(f"  Model: {version.model}")
```

## Searching and Filtering

### By Category

```python
# Get all KYC prompts
kyc_prompts = registry.get_prompts_by_category("kyc")
```

### By Tags

```python
# Get prompts tagged with "compliance"
compliance_prompts = registry.get_prompts_by_tags(["compliance"])

# Get prompts with multiple tags
filtered = registry.get_prompts_by_tags(["production", "v1.0"])
```

### Statistics

```python
stats = registry.get_statistics()
print(f"Total prompts: {stats['total_prompts']}")
print(f"Total versions: {stats['total_versions']}")
print(f"Total usage: {stats['total_usage']}")
print(f"Categories: {stats['categories']}")
```

## Import/Export

### Export Prompts

```python
# Export all prompts
registry.export_prompts("prompts_backup.json")

# Export specific category
registry.export_prompts("prompts_kyc.json", category="kyc")
```

### Import Prompts

```python
# Import from backup
registry.import_prompts("prompts_backup.json")
```

## Integration with LLM Calls

### Using with LangChain

```python
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

registry = PromptRegistry()

# Get rendered prompt
rendered = registry.render_prompt(
    "kyc_assessment",
    {
        "vendor_name": "Example Corp",
        "country": "USA",
        "registration_number": "123456"
    }
)

# Use with LangChain
prompt_template = PromptTemplate.from_template(rendered)
llm = ChatOpenAI(model="gpt-4")
chain = prompt_template | llm

result = chain.invoke({})
```

### Using with OpenAI API

```python
from openai import OpenAI

registry = PromptRegistry()
client = OpenAI()

rendered = registry.render_prompt("risk_assessment", variables)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": rendered}],
    temperature=0.3,
    max_tokens=2048
)
```

## Best Practices

### Naming Conventions

1. **Prompt Names**: Use snake_case (e.g., `kyc_assessment`, `risk_scoring`)
2. **Categories**: Use lowercase, single word when possible
3. **Versions**: Use semantic versioning (v1.0, v1.1, v2.0)
4. **Tags**: Use lowercase, hyphens for phrases (e.g., `high-priority`, `production`)

### Template Guidelines

1. **Clear Variable Names**: Use descriptive names like `{{vendor_name}}`, not `{{x}}`
2. **Formatting**: Include clear sections and examples in prompts
3. **Instructions**: Specify output format (JSON, bullet points, etc.)
4. **Variables**: Keep number of variables minimal (< 10)
5. **Length**: Optimize for token usage while maintaining clarity

### Versioning Strategy

1. **v1.0**: Initial release
2. **v1.x**: Minor improvements (formatting, clarity)
3. **v2.x**: Significant changes (model upgrade, new approach)
4. **Active**: Keep only stable versions as active
5. **Deprecation**: Mark old versions with notes about replacements

## Monitoring Usage

```python
# Track usage per prompt
for prompt in registry.prompts.values():
    print(f"{prompt.name}: {prompt.usage_count} uses")
    print(f"  Last active version: {prompt.get_active_version().version}")
```

## API Reference

### PromptRegistry

```python
# Create/Load
registry = PromptRegistry(base_path="prompts")

# Register
registry.register_prompt(prompt)

# Retrieve
prompt = registry.get_prompt(name)

# Render
rendered = registry.render_prompt(name, variables, version_id)

# Search
prompts = registry.get_prompts_by_category(category)
prompts = registry.get_prompts_by_tags(tags)

# Manage versions
registry.add_version(name, version_id, template, ...)

# Statistics
stats = registry.get_statistics()

# Import/Export
registry.export_prompts(path, category)
registry.import_prompts(path)
```

### Prompt

```python
# Create
prompt = Prompt(name, category, description)

# Manage versions
prompt.add_version(version)
version = prompt.get_version(version_id)
version = prompt.get_active_version()

# Render
rendered = prompt.render(variables, version_id)

# Serialize
data = prompt.to_dict()
```

### PromptVersion

```python
# Create
version = PromptVersion(
    version, name, description, category,
    template, variables, model,
    temperature, max_tokens
)

# Properties
hash = version.get_hash()  # Content hash for tracking
data = version.to_dict()
```

## Examples

### Example 1: KYC Assessment

See `prompts/kyc/kyc_assessment.json`

### Example 2: Risk Scoring

```json
{
  "name": "risk_scoring",
  "category": "risk",
  "description": "Score vendor risk",
  "versions": [{
    "version": "v1.0",
    "template": "Score risk based on: {{factors}}",
    "variables": ["factors"],
    "model": "gpt-4",
    "temperature": 0.3
  }]
}
```

## Troubleshooting

### Prompt Not Found

```python
# List available prompts
all_prompts = registry.prompts.keys()
print(all_prompts)

# Check category
prompts = registry.get_prompts_by_category("kyc")
```

### Variable Substitution Failed

```python
# Check required variables
prompt = registry.get_prompt("kyc_assessment")
version = prompt.get_active_version()
print(f"Required: {version.variables}")

# Ensure all are provided
variables = {var: "value" for var in version.variables}
```

### Version Not Active

```python
prompt = registry.get_prompt("name")
prompt.default_version = "v1.0"
registry._save_prompt(prompt)
```

## Next Steps

1. Create category folders in `prompts/`
2. Add prompt definitions as JSON files
3. Load prompts with `PromptRegistry()`
4. Use `render_prompt()` in your application
5. Track usage with built-in counters
6. Version control your prompts like code
