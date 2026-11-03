"""Examples demonstrating dashboard and observability integration."""

import asyncio
import json
from datetime import datetime, timedelta

from src.dashboards.stakeholder_dashboard import (
    DashboardBuilder,
    MetricCategory,
    StakeholderDashboard,
)
from src.engineering.llm_observability import (
    LLMCallMetadata,
    UnifiedLLMObservability,
    llm_observable,
)


async def example_1_basic_dashboard():
    """Example 1: Create a basic stakeholder dashboard."""
    print("\n=== Example 1: Basic Stakeholder Dashboard ===\n")

    # Create dashboard using builder pattern
    dashboard = (
        DashboardBuilder("Acme Corporation")
        .add_volume_metrics(
            vendors_processed=1250,
            documents_analyzed=15000,
            workflows_completed=950,
        )
        .add_quality_metrics(
            quality_score=0.87,
            accuracy=0.92,
            consistency=0.88,
        )
        .add_performance_metrics(
            avg_latency=1200,  # ms
            success_rate=0.96,
            throughput=5.2,  # ops/sec
        )
        .add_cost_metrics(
            total_cost=45000,  # $
            cost_per_vendor=36,
            cost_optimization=0.15,
        )
        .add_compliance_metrics(
            compliance_score=0.94,
            audit_passed=18,
            audit_total=19,
        )
        .build()
    )

    # Get health score
    health_score = dashboard.get_health_score()
    print(f"Overall Health Score: {health_score:.1f}%")
    print(f"Status: {'✓ Healthy' if health_score >= 80 else '⚠ At Risk'}")

    # Get summary
    summary = dashboard.get_summary()
    print(f"\nSections: {len(summary['sections'])}")
    for section in summary["sections"]:
        print(f"  - {section['title']}: {len(section['metrics'])} metrics")

    # Show alerts
    if summary["alerts"]:
        print(f"\nAlerts ({len(summary['alerts'])}):")
        for alert in summary["alerts"]:
            print(
                f"  - {alert['metric']}: {alert['value']} {alert['severity'].upper()}"
            )

    return dashboard


async def example_2_add_insights():
    """Example 2: Add insights and recommendations."""
    print("\n=== Example 2: Dashboard with Insights ===\n")

    dashboard_builder = DashboardBuilder("Acme Corporation Q1 2024")

    # Add metrics
    dashboard_builder.add_volume_metrics(
        vendors_processed=1250,
        documents_analyzed=15000,
        workflows_completed=950,
    )

    dashboard_builder.add_quality_metrics(
        quality_score=0.87,
        accuracy=0.92,
        consistency=0.88,
    )

    # Add insights and recommendations
    dashboard_builder.add_insights_and_recommendations(
        insights={
            "Quality Metrics": [
                "Accuracy improved 2% from previous quarter",
                "Consistency issues identified in ML model predictions",
                "Vendor verification turnaround reduced by 15%",
            ],
            "Processing Volume": [
                "Processed 45% more vendors than last quarter",
                "Document analysis volume increased by 60%",
                "Workflow automation rate improved to 76%",
            ],
        },
        recommendations={
            "Quality Metrics": [
                "Retrain ML models on consistency edge cases",
                "Implement additional validation checks",
                "Consider manual review for high-risk vendors",
            ],
            "Processing Volume": [
                "Scale infrastructure for increased document processing",
                "Optimize batch processing pipeline",
                "Explore parallel workflow execution",
            ],
        },
    )

    dashboard = dashboard_builder.build()

    # Export to JSON
    json_data = dashboard.get_json_for_export()
    print(f"Dashboard JSON Export:")
    print(json.dumps(json_data, indent=2)[:500] + "...\n")

    return dashboard


async def example_3_html_export():
    """Example 3: Export dashboard as HTML."""
    print("\n=== Example 3: HTML Export ===\n")

    dashboard = (
        DashboardBuilder("Acme Corporation")
        .add_volume_metrics(1250, 15000, 950)
        .add_quality_metrics(0.87, 0.92, 0.88)
        .add_performance_metrics(1200, 0.96, 5.2)
        .add_cost_metrics(45000, 36, 0.15)
        .add_compliance_metrics(0.94, 18, 19)
        .build()
    )

    # Generate HTML report
    html = dashboard.get_html_report()

    # Save to file
    with open("/tmp/dashboard_report.html", "w") as f:
        f.write(html)

    print(f"HTML report generated: /tmp/dashboard_report.html")
    print(f"Report size: {len(html)} bytes")
    print(f"First 300 chars:\n{html[:300]}...\n")

    return dashboard


async def example_4_llm_observability_tracking():
    """Example 4: Track LLM calls with LangSmith and LangFuse."""
    print("\n=== Example 4: LLM Observability Tracking ===\n")

    # Initialize unified observability
    # In production, set environment variables:
    # LANGSMITH_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
    unified_obs = UnifiedLLMObservability(
        langsmith_project="vendor-risk-assessment",
        langfuse_public_key=None,  # Set from env in production
        langfuse_secret_key=None,
    )

    # Simulate LLM calls
    calls = [
        {
            "name": "vendor_risk_assessment",
            "inputs": {"vendor_id": "V001", "country": "USA"},
            "outputs": {"risk_score": 42, "risk_level": "medium"},
            "metadata": LLMCallMetadata(
                model="gpt-4",
                prompt_tokens=150,
                completion_tokens=100,
                total_tokens=250,
                latency_ms=1200,
                cost=0.015,
            ),
        },
        {
            "name": "kyc_verification",
            "inputs": {"vendor_id": "V002", "documents": "pdf,jpg"},
            "outputs": {"verified": True, "confidence": 0.95},
            "metadata": LLMCallMetadata(
                model="gpt-4",
                prompt_tokens=200,
                completion_tokens=150,
                total_tokens=350,
                latency_ms=1500,
                cost=0.020,
            ),
        },
        {
            "name": "compliance_check",
            "inputs": {"vendor_id": "V003", "jurisdiction": "EU"},
            "outputs": {"compliant": True, "issues": []},
            "metadata": LLMCallMetadata(
                model="gpt-3.5-turbo",
                prompt_tokens=100,
                completion_tokens=80,
                total_tokens=180,
                latency_ms=800,
                cost=0.002,
            ),
        },
    ]

    # Log calls
    for call in calls:
        tracking_ids = unified_obs.log_llm_call(
            name=call["name"],
            inputs=call["inputs"],
            outputs=call["outputs"],
            metadata=call["metadata"],
            tags=["production", "vendor-risk"],
        )
        print(f"Logged '{call['name']}': {tracking_ids}")

    # Get statistics
    stats = unified_obs.get_statistics()
    print(f"\nObservability Statistics:")
    print(f"  Total calls tracked: {stats['total_calls']}")
    print(f"  Total input size: {stats['total_input_size']} bytes")
    print(f"  Total output size: {stats['total_output_size']} bytes")
    print(f"  Backends configured: {stats['backends_configured']}")

    # Get call history
    history = unified_obs.get_call_history(limit=5)
    print(f"\nRecent calls ({len(history)}):")
    for call in history:
        print(f"  - {call['name']}: {call['timestamp']}")

    return unified_obs


async def example_5_llm_observable_decorator():
    """Example 5: Use @llm_observable decorator."""
    print("\n=== Example 5: LLM Observable Decorator ===\n")

    unified_obs = UnifiedLLMObservability(
        langsmith_project="vendor-risk-assessment"
    )

    # Define tracked function
    @llm_observable(unified_obs, name="vendor_assessment", tags=["async"])
    async def assess_vendor(vendor_id: str, data: dict):
        """Assess vendor with automatic tracking."""
        await asyncio.sleep(0.1)  # Simulate processing
        return {"vendor_id": vendor_id, "risk_score": 42, "status": "complete"}

    # Call function (automatically tracked)
    result = await assess_vendor("V001", {"country": "USA"})
    print(f"Assessment result: {result}")

    # Verify tracking
    stats = unified_obs.get_statistics()
    print(f"Calls tracked after decoration: {stats['total_calls']}")

    return unified_obs


async def example_6_dashboard_with_observability():
    """Example 6: Integrate dashboard with observability data."""
    print("\n=== Example 6: Dashboard + Observability Integration ===\n")

    # Initialize observability
    unified_obs = UnifiedLLMObservability(
        langsmith_project="vendor-risk-assessment"
    )

    # Simulate tracking some calls
    for i in range(10):
        unified_obs.log_llm_call(
            name=f"assessment_{i}",
            inputs={"vendor_id": f"V{i:03d}"},
            outputs={"risk_score": 30 + i * 5},
            metadata=LLMCallMetadata(
                model="gpt-4",
                prompt_tokens=150 + i * 10,
                completion_tokens=100 + i * 5,
                latency_ms=1000 + i * 100,
                cost=0.01 + i * 0.001,
            ),
        )

    # Get observability stats
    obs_stats = unified_obs.get_statistics()

    # Calculate metrics for dashboard
    total_calls = obs_stats["total_calls"]
    total_cost = sum(
        (0.01 + i * 0.001) for i in range(total_calls)
    )  # Approximate
    cost_per_vendor = total_cost / total_calls if total_calls > 0 else 0

    # Create dashboard with observability-derived metrics
    dashboard = (
        DashboardBuilder("Vendor Risk Platform")
        .add_volume_metrics(
            vendors_processed=total_calls,
            documents_analyzed=total_calls * 12,
            workflows_completed=int(total_calls * 0.95),
        )
        .add_quality_metrics(
            quality_score=0.88,
            accuracy=0.93,
            consistency=0.87,
        )
        .add_performance_metrics(
            avg_latency=1400,
            success_rate=0.95,
            throughput=total_calls / 60,  # Per minute
        )
        .add_cost_metrics(
            total_cost=total_cost,
            cost_per_vendor=cost_per_vendor,
            cost_optimization=0.12,
        )
        .build()
    )

    print(f"Dashboard created from observability data:")
    print(f"  Health Score: {dashboard.get_health_score():.1f}%")
    summary = dashboard.get_summary()
    print(f"  Sections: {len(summary['sections'])}")

    return dashboard, unified_obs


async def example_7_custom_thresholds():
    """Example 7: Customize metric thresholds."""
    print("\n=== Example 7: Custom Thresholds ===\n")

    from src.dashboards.stakeholder_dashboard import MetricThreshold

    dashboard = StakeholderDashboard("Acme Corp")

    # Add custom threshold for SLA compliance
    dashboard.thresholds["sla_compliance"] = MetricThreshold(
        metric_name="sla_compliance",
        warning_threshold=99.0,
        critical_threshold=95.0,
        direction="higher_is_better",
    )

    # Add metric with custom threshold
    dashboard.add_metric(
        section_title="SLA Performance",
        metric_name="sla_compliance",
        value=98.5,
        unit="%",
        category=MetricCategory.PERFORMANCE,
        target=99.5,
        description="SLA compliance rate",
    )

    # Check status
    metric = dashboard.sections["SLA Performance"].metrics[0]
    print(f"Metric: {metric.name}")
    print(f"Value: {metric.value}%")
    print(f"Target: {metric.target}%")
    print(f"Status: {metric.status} (warning=99%, critical=95%)")

    return dashboard


async def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("DASHBOARD & OBSERVABILITY EXAMPLES")
    print("=" * 60)

    # Run examples
    await example_1_basic_dashboard()
    await example_2_add_insights()
    await example_3_html_export()
    await example_4_llm_observability_tracking()
    await example_5_llm_observable_decorator()
    await example_6_dashboard_with_observability()
    await example_7_custom_thresholds()

    print("\n" + "=" * 60)
    print("ALL EXAMPLES COMPLETED")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
