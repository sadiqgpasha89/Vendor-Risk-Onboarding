# Stakeholder Dashboard Guide

## Overview

The Stakeholder Dashboard provides business-level metrics and insights for non-technical stakeholders, executives, and management teams. It focuses on:

- **Volume Metrics**: Vendors processed, documents analyzed, workflows completed
- **Quality Metrics**: Quality scores, accuracy, consistency
- **Performance Metrics**: Latency, success rates, throughput
- **Cost Analysis**: Total costs, per-vendor costs, optimization
- **Compliance**: Compliance scores, audit results
- **Business Insights**: Key findings and recommendations

## Quick Start

### Create a Basic Dashboard

```python
from src.dashboards.stakeholder_dashboard import DashboardBuilder

# Create dashboard
dashboard = (
    DashboardBuilder("Acme Corporation")
    .add_volume_metrics(
        vendors_processed=1250,
        documents_analyzed=15000,
        workflows_completed=950
    )
    .add_quality_metrics(
        quality_score=0.87,
        accuracy=0.92,
        consistency=0.88
    )
    .add_performance_metrics(
        avg_latency=1200,  # ms
        success_rate=0.96,
        throughput=5.2  # ops/sec
    )
    .add_cost_metrics(
        total_cost=45000,  # $
        cost_per_vendor=36,
        cost_optimization=0.15
    )
    .add_compliance_metrics(
        compliance_score=0.94,
        audit_passed=18,
        audit_total=19
    )
    .build()
)

# Get summary
summary = dashboard.get_summary()
print(summary)
```

### Generate Reports

```python
# Get health score
health = dashboard.get_health_score()
print(f"Overall Health: {health:.1f}%")

# Export JSON
json_data = dashboard.get_json_for_export()

# Generate HTML report
html = dashboard.get_html_report()
with open("dashboard_report.html", "w") as f:
    f.write(html)
```

## Dashboard Structure

### Sections

Each dashboard consists of sections organized by category:

| Section | Category | Metrics |
|---------|----------|---------|
| Processing Volume | VOLUME | Vendors, Documents, Workflows |
| Quality Metrics | QUALITY | Quality Score, Accuracy, Consistency |
| System Performance | PERFORMANCE | Latency, Success Rate, Throughput |
| Cost Analysis | COST | Total Cost, Cost/Vendor, Optimization |
| Compliance | COMPLIANCE | Compliance Score, Audit Pass Rate |

### Metrics

Each metric contains:

```python
@dataclass
class DashboardMetric:
    name: str                  # "quality_score"
    category: MetricCategory   # MetricCategory.QUALITY
    value: float               # 87.5
    unit: str                  # "%"
    status: str                # "green", "yellow", "red"
    trend: float               # +5.2 (percent change)
    description: str           # Human-readable description
    target: Optional[float]    # 90.0 (goal)
    historical_values: List    # [85, 86, 87, 87.5]
```

### Status Colors

- **Green**: On track (value above warning threshold)
- **Yellow**: Warning (value between critical and warning)
- **Red**: Critical (value below critical threshold)

## API Reference

### DashboardBuilder

Fluent API for building dashboards:

```python
builder = DashboardBuilder("Organization Name")

# Add metric groups
builder.add_volume_metrics(...)
builder.add_quality_metrics(...)
builder.add_performance_metrics(...)
builder.add_cost_metrics(...)
builder.add_compliance_metrics(...)

# Add insights and recommendations
builder.add_insights_and_recommendations(
    insights={"Section": ["insight1", "insight2"]},
    recommendations={"Section": ["rec1", "rec2"]}
)

# Build
dashboard = builder.build()
```

### StakeholderDashboard

Main dashboard class:

```python
dashboard = StakeholderDashboard("Organization")

# Add metrics
dashboard.add_metric(
    section_title="Quality Metrics",
    metric_name="accuracy",
    value=92.5,
    unit="%",
    category=MetricCategory.QUALITY,
    target=95,
    description="Assessment accuracy"
)

# Add insights
dashboard.add_insight("Quality Metrics", "Accuracy improved 2% this quarter")

# Add recommendations
dashboard.add_recommendation("Quality Metrics", "Increase training data for edge cases")

# Get results
summary = dashboard.get_summary()
health = dashboard.get_health_score()
json_data = dashboard.get_json_for_export()
html = dashboard.get_html_report()
```

## Thresholds and Status

### Default Thresholds

| Metric | Warning | Critical | Better |
|--------|---------|----------|--------|
| quality_score | 80% | 60% | Higher |
| processing_latency | 2000ms | 5000ms | Lower |
| success_rate | 95% | 80% | Higher |
| compliance_score | 90% | 70% | Higher |
| cost_per_transaction | $1.00 | $5.00 | Lower |

### Customize Thresholds

```python
from src.dashboards.stakeholder_dashboard import MetricThreshold

dashboard.thresholds["custom_metric"] = MetricThreshold(
    metric_name="custom_metric",
    warning_threshold=80,
    critical_threshold=50,
    direction="higher_is_better"
)
```

## Export Formats

### JSON Export

```python
json_data = dashboard.get_json_for_export()
# Returns structured JSON with all metrics, insights, recommendations
```

### HTML Report

```python
html = dashboard.get_html_report()
# Returns complete HTML file with:
# - Health score display
# - Metrics table per section
# - Insights and recommendations
# - Professional styling
```

### API Response Format

```python
summary = dashboard.get_summary()
# Returns:
# {
#   "organization": "Name",
#   "generated_at": "2024-01-15T10:30:00",
#   "sections": [
#     {
#       "title": "Section Name",
#       "category": "quality",
#       "metrics": [...],
#       "insights": [...],
#       "recommendations": [...]
#     }
#   ],
#   "key_metrics": {...},  # Non-green metrics
#   "alerts": [...]         # Red/yellow metrics
# }
```

## Integration with FastAPI

### Add Endpoints

```python
from fastapi import FastAPI
from src.dashboards.stakeholder_dashboard import DashboardBuilder

app = FastAPI()

@app.get("/api/v1/dashboards/stakeholder")
async def get_stakeholder_dashboard():
    """Get real-time stakeholder dashboard."""
    
    # In production, fetch metrics from database
    dashboard = (
        DashboardBuilder("Organization")
        .add_volume_metrics(...)
        .add_quality_metrics(...)
        .add_performance_metrics(...)
        .add_cost_metrics(...)
        .add_compliance_metrics(...)
        .build()
    )
    
    return dashboard.get_summary()

@app.get("/api/v1/dashboards/export/json")
async def export_dashboard_json():
    """Export dashboard as JSON."""
    dashboard = create_dashboard()
    return dashboard.get_json_for_export()

@app.get("/api/v1/dashboards/export/html")
async def export_dashboard_html():
    """Export dashboard as HTML report."""
    dashboard = create_dashboard()
    return {
        "html": dashboard.get_html_report(),
        "content_type": "text/html"
    }

@app.get("/api/v1/dashboards/health")
async def get_health_score():
    """Get overall health score."""
    dashboard = create_dashboard()
    return {
        "health_score": dashboard.get_health_score(),
        "status": "healthy" if dashboard.get_health_score() >= 80 else "at_risk"
    }
```

### Database Integration

```python
from src.db.models import DashboardMetric
from sqlalchemy.orm import Session

async def get_stakeholder_dashboard(db: Session):
    """Build dashboard from database metrics."""
    
    # Fetch metrics
    volume_metrics = db.query(DashboardMetric).filter_by(
        category="volume"
    ).all()
    
    quality_metrics = db.query(DashboardMetric).filter_by(
        category="quality"
    ).all()
    
    dashboard = DashboardBuilder("Organization")
    
    # Add metrics from database
    for metric in volume_metrics:
        dashboard.dashboard.add_metric(
            section_title="Processing Volume",
            metric_name=metric.name,
            value=metric.value,
            unit=metric.unit,
            category=metric.category,
            target=metric.target,
            description=metric.description
        )
    
    # ... similar for other categories
    
    return dashboard.build()
```

## Example: Complete Dashboard Setup

```python
from src.dashboards.stakeholder_dashboard import DashboardBuilder, MetricCategory
from datetime import datetime

# Create dashboard for Q1 2024
dashboard = DashboardBuilder("Acme Corporation Q1 2024")

# Volume metrics
dashboard.add_volume_metrics(
    vendors_processed=1250,
    documents_analyzed=15000,
    workflows_completed=950
)

# Quality metrics
dashboard.add_quality_metrics(
    quality_score=0.87,
    accuracy=0.92,
    consistency=0.88
)

# Performance metrics
dashboard.add_performance_metrics(
    avg_latency=1200,      # ms
    success_rate=0.96,     # 96%
    throughput=5.2         # ops/sec
)

# Cost metrics
dashboard.add_cost_metrics(
    total_cost=45000,              # $45,000
    cost_per_vendor=36,            # $36/vendor
    cost_optimization=0.15         # 15% savings
)

# Compliance metrics
dashboard.add_compliance_metrics(
    compliance_score=0.94,         # 94%
    audit_passed=18,
    audit_total=19
)

# Add insights and recommendations
dashboard.add_insights_and_recommendations(
    insights={
        "Quality Metrics": [
            "Accuracy improved 2% from previous quarter",
            "Consistency issues identified in ML model predictions",
            "Vendor verification turnaround reduced by 15%"
        ],
        "Cost Analysis": [
            "Achieved 15% cost optimization through workflow improvements",
            "Operational efficiency gains from automation",
            "Infrastructure cost increased due to data volume"
        ],
        "Compliance": [
            "Successfully passed 18 of 19 compliance audits",
            "One audit failure due to documentation gap",
            "No critical findings reported"
        ]
    },
    recommendations={
        "Quality Metrics": [
            "Retrain ML models on consistency edge cases",
            "Implement additional validation checks",
            "Consider manual review for high-risk vendors"
        ],
        "Cost Analysis": [
            "Explore caching strategies to reduce API calls",
            "Negotiate better rates with cloud providers",
            "Implement auto-scaling for off-peak hours"
        ],
        "Compliance": [
            "Address documentation gap before next audit",
            "Implement quarterly compliance reviews",
            "Schedule refresh training for compliance team"
        ]
    }
)

# Build dashboard
dashboard_obj = dashboard.build()

# Get results
print(f"Health Score: {dashboard_obj.get_health_score():.1f}%")
print(f"Summary: {dashboard_obj.get_summary()}")

# Export
with open("q1_2024_dashboard.html", "w") as f:
    f.write(dashboard_obj.get_html_report())

with open("q1_2024_dashboard.json", "w") as f:
    import json
    json.dump(dashboard_obj.get_json_for_export(), f, indent=2)
```

## Grafana Integration

### Export to Grafana JSON

```python
def export_to_grafana(dashboard):
    """Convert dashboard to Grafana format."""
    
    grafana_dashboard = {
        "dashboard": {
            "title": dashboard.organization_name,
            "description": "Stakeholder Dashboard",
            "tags": ["stakeholder", "business-metrics"],
            "timezone": "browser",
            "panels": [],
            "refresh": "30s",
            "time": {
                "from": "now-30d",
                "to": "now"
            }
        }
    }
    
    panel_id = 1
    for section in dashboard.sections.values():
        for metric in section.metrics:
            panel = {
                "id": panel_id,
                "title": metric.name,
                "type": "gauge" if metric.unit == "%" else "stat",
                "targets": [
                    {
                        "expr": f"metric_{metric.name}",
                        "legendFormat": metric.unit
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "thresholds": {
                            "mode": "absolute",
                            "steps": [
                                {"color": "red", "value": None},
                                {"color": "yellow", "value": metric.target * 0.7},
                                {"color": "green", "value": metric.target * 0.9}
                            ]
                        }
                    }
                }
            }
            grafana_dashboard["dashboard"]["panels"].append(panel)
            panel_id += 1
    
    return grafana_dashboard
```

## Best Practices

### 1. Regular Updates

```python
# Update metrics daily or on schedule
async def update_dashboard_metrics():
    """Update dashboard metrics from database."""
    dashboard = await get_stakeholder_dashboard()
    # Store in cache or database for fast retrieval
```

### 2. Trend Analysis

```python
# Track historical values
metric.historical_values = [85.0, 86.5, 87.0, 87.5]
metric.trend = 2.5  # 2.5% improvement
```

### 3. Alerting

```python
if dashboard.get_health_score() < 70:
    # Send alert to stakeholders
    send_alert("Dashboard health critical")
```

### 4. Customization

```python
# Allow stakeholders to customize thresholds
dashboard.thresholds["quality_score"].warning_threshold = 0.75
```

## Performance Considerations

1. **Caching**: Cache dashboard data for 15-30 minutes
2. **Database Queries**: Use aggregations for metrics
3. **Export**: Generate exports asynchronously
4. **Historical Data**: Archive old metrics separately

## Troubleshooting

### Status Not Updating

```python
# Check threshold configuration
threshold = dashboard.thresholds.get("metric_name")
if threshold:
    print(f"Warning: {threshold.warning_threshold}")
    print(f"Critical: {threshold.critical_threshold}")

# Recalculate status
metric.status = threshold.get_status(metric.value)
```

### Missing Sections

```python
# Ensure all sections are created
if "Quality Metrics" not in dashboard.sections:
    dashboard.sections["Quality Metrics"] = DashboardSection(
        title="Quality Metrics",
        category=MetricCategory.QUALITY
    )
```

### Export Issues

```python
# HTML export requires all metrics
if not dashboard.get_summary()["sections"]:
    print("No sections added to dashboard")

# JSON export requires proper serialization
import json
json_str = json.dumps(dashboard.get_json_for_export(), indent=2)
```

## Next Steps

1. Create dashboard in your FastAPI application
2. Connect to your database for real metrics
3. Set up regular update schedule
4. Export and share with stakeholders
5. Gather feedback and refine metrics
6. Integrate with Grafana for advanced visualizations
