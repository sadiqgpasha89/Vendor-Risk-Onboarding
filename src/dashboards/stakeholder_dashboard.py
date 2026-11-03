"""Stakeholder Dashboard Module - High-level metrics and insights for business stakeholders."""

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class MetricCategory(str, Enum):
    """Categories of metrics for stakeholder dashboard."""

    VOLUME = "volume"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    COST = "cost"
    RISK = "risk"
    COMPLIANCE = "compliance"


@dataclass
class MetricThreshold:
    """Threshold for metric status."""

    metric_name: str
    warning_threshold: float
    critical_threshold: float
    direction: str = "higher_is_better"  # or "lower_is_better"

    def get_status(self, value: float) -> str:
        """Get status based on value and thresholds.

        Returns:
            'green', 'yellow', or 'red'
        """
        if self.direction == "higher_is_better":
            if value >= self.warning_threshold:
                return "green"
            elif value >= self.critical_threshold:
                return "yellow"
            else:
                return "red"
        else:  # lower_is_better
            if value <= self.warning_threshold:
                return "green"
            elif value <= self.critical_threshold:
                return "yellow"
            else:
                return "red"


@dataclass
class DashboardMetric:
    """Metric for dashboard display."""

    name: str
    category: MetricCategory
    value: float
    unit: str
    status: str = "green"  # green, yellow, red
    trend: float = 0.0  # percent change
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    target: Optional[float] = None
    historical_values: List[float] = field(default_factory=list)


@dataclass
class DashboardSection:
    """Section of the dashboard."""

    title: str
    category: MetricCategory
    metrics: List[DashboardMetric] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class StakeholderDashboard:
    """Dashboard for stakeholder consumption."""

    def __init__(self, organization_name: str):
        """Initialize stakeholder dashboard.

        Args:
            organization_name: Name of organization
        """
        self.organization_name = organization_name
        self.sections: Dict[str, DashboardSection] = {}
        self.thresholds: Dict[str, MetricThreshold] = {}
        self._setup_default_thresholds()

    def _setup_default_thresholds(self) -> None:
        """Setup default metric thresholds."""
        self.thresholds = {
            "quality_score": MetricThreshold(
                "quality_score",
                warning_threshold=0.8,
                critical_threshold=0.6,
                direction="higher_is_better",
            ),
            "processing_latency": MetricThreshold(
                "processing_latency",
                warning_threshold=2000,  # ms
                critical_threshold=5000,
                direction="lower_is_better",
            ),
            "success_rate": MetricThreshold(
                "success_rate",
                warning_threshold=0.95,
                critical_threshold=0.8,
                direction="higher_is_better",
            ),
            "compliance_score": MetricThreshold(
                "compliance_score",
                warning_threshold=0.9,
                critical_threshold=0.7,
                direction="higher_is_better",
            ),
            "cost_per_transaction": MetricThreshold(
                "cost_per_transaction",
                warning_threshold=1.0,
                critical_threshold=5.0,
                direction="lower_is_better",
            ),
        }

    def add_metric(
        self,
        section_title: str,
        metric_name: str,
        value: float,
        unit: str,
        category: MetricCategory,
        target: Optional[float] = None,
        description: str = "",
    ) -> None:
        """Add a metric to the dashboard.

        Args:
            section_title: Section title
            metric_name: Metric name
            value: Current value
            unit: Unit of measurement
            category: Metric category
            target: Optional target value
            description: Metric description
        """
        # Get or create section
        if section_title not in self.sections:
            self.sections[section_title] = DashboardSection(
                title=section_title,
                category=category,
            )

        section = self.sections[section_title]

        # Determine status
        status = "green"
        if metric_name in self.thresholds:
            status = self.thresholds[metric_name].get_status(value)

        # Create metric
        metric = DashboardMetric(
            name=metric_name,
            category=category,
            value=value,
            unit=unit,
            status=status,
            target=target,
            description=description,
        )

        # Add to section
        section.metrics.append(metric)
        logger.info(f"Added metric '{metric_name}' to section '{section_title}'")

    def add_insight(
        self,
        section_title: str,
        insight: str,
    ) -> None:
        """Add an insight to a section.

        Args:
            section_title: Section title
            insight: Insight text
        """
        if section_title not in self.sections:
            self.sections[section_title] = DashboardSection(
                title=section_title,
                category=MetricCategory.VOLUME,
            )

        self.sections[section_title].insights.append(insight)

    def add_recommendation(
        self,
        section_title: str,
        recommendation: str,
    ) -> None:
        """Add a recommendation to a section.

        Args:
            section_title: Section title
            recommendation: Recommendation text
        """
        if section_title not in self.sections:
            self.sections[section_title] = DashboardSection(
                title=section_title,
                category=MetricCategory.VOLUME,
            )

        self.sections[section_title].recommendations.append(recommendation)

    def get_summary(self) -> Dict[str, Any]:
        """Get dashboard summary for executive view."""
        summary = {
            "organization": self.organization_name,
            "generated_at": datetime.utcnow().isoformat(),
            "sections": [],
            "key_metrics": {},
            "alerts": [],
        }

        for section in self.sections.values():
            section_summary = {
                "title": section.title,
                "category": section.category.value,
                "metrics": [],
                "insights": section.insights[:3],  # Top 3
                "recommendations": section.recommendations[:3],  # Top 3
            }

            for metric in section.metrics:
                metric_display = {
                    "name": metric.name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "status": metric.status,
                    "target": metric.target,
                    "trend": metric.trend,
                }

                section_summary["metrics"].append(metric_display)

                # Collect key metrics
                if metric.status != "green":
                    summary["key_metrics"][metric.name] = metric_display

                # Collect alerts
                if metric.status == "red":
                    summary["alerts"].append({
                        "metric": metric.name,
                        "value": metric.value,
                        "unit": metric.unit,
                        "severity": "critical",
                    })
                elif metric.status == "yellow":
                    summary["alerts"].append({
                        "metric": metric.name,
                        "value": metric.value,
                        "unit": metric.unit,
                        "severity": "warning",
                    })

            summary["sections"].append(section_summary)

        return summary

    def get_health_score(self) -> float:
        """Calculate overall health score (0-100).

        Returns:
            Health score percentage
        """
        if not self.sections:
            return 0.0

        total_metrics = 0
        green_count = 0

        for section in self.sections.values():
            for metric in section.metrics:
                total_metrics += 1
                if metric.status == "green":
                    green_count += 1

        if total_metrics == 0:
            return 0.0

        return (green_count / total_metrics) * 100

    def get_json_for_export(self) -> Dict[str, Any]:
        """Get dashboard as JSON for export."""
        export_data = {
            "organization": self.organization_name,
            "generated_at": datetime.utcnow().isoformat(),
            "health_score": self.get_health_score(),
            "sections": [],
        }

        for section in self.sections.values():
            section_data = {
                "title": section.title,
                "category": section.category.value,
                "metrics": [
                    {
                        "name": m.name,
                        "value": m.value,
                        "unit": m.unit,
                        "status": m.status,
                        "target": m.target,
                        "trend": m.trend,
                        "timestamp": m.timestamp,
                    }
                    for m in section.metrics
                ],
                "insights": section.insights,
                "recommendations": section.recommendations,
            }
            export_data["sections"].append(section_data)

        return export_data

    def get_html_report(self) -> str:
        """Generate HTML report for stakeholders."""
        health_score = self.get_health_score()

        # Determine health color
        if health_score >= 80:
            health_color = "#2ecc71"  # green
        elif health_score >= 60:
            health_color = "#f39c12"  # orange
        else:
            health_color = "#e74c3c"  # red

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Vendor Risk System - Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .header {{ background-color: #2c3e50; color: white; padding: 20px; border-radius: 5px; }}
                .health-score {{ font-size: 48px; font-weight: bold; text-align: center; }}
                .metric-card {{ background: white; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .status-green {{ color: #2ecc71; font-weight: bold; }}
                .status-yellow {{ color: #f39c12; font-weight: bold; }}
                .status-red {{ color: #e74c3c; font-weight: bold; }}
                .section {{ margin: 30px 0; }}
                .insight {{ background: #ecf0f1; padding: 10px; margin: 5px 0; border-left: 4px solid #3498db; }}
                .recommendation {{ background: #e8f8f5; padding: 10px; margin: 5px 0; border-left: 4px solid #27ae60; }}
                table {{ width: 100%; border-collapse: collapse; background: white; margin: 10px 0; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #34495e; color: white; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{self.organization_name} - System Dashboard</h1>
                <p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </div>

            <div class="metric-card" style="text-align: center; font-size: 24px;">
                <p>Overall Health Score</p>
                <div class="health-score" style="color: {health_color};">{health_score:.1f}%</div>
            </div>
        """

        # Add sections
        for section in self.sections.values():
            html += f"<div class='section'><h2>{section.title}</h2>"

            # Metrics table
            html += "<table><tr><th>Metric</th><th>Value</th><th>Target</th><th>Status</th><th>Trend</th></tr>"
            for metric in section.metrics:
                status_class = f"status-{metric.status}"
                trend_arrow = "↑" if metric.trend > 0 else "↓" if metric.trend < 0 else "→"
                html += f"""
                <tr>
                    <td>{metric.name}</td>
                    <td>{metric.value:.2f} {metric.unit}</td>
                    <td>{metric.target or 'N/A'}</td>
                    <td class="{status_class}">{metric.status.upper()}</td>
                    <td>{trend_arrow} {metric.trend:.1f}%</td>
                </tr>
                """
            html += "</table>"

            # Insights
            if section.insights:
                html += "<h3>Key Insights</h3>"
                for insight in section.insights:
                    html += f"<div class='insight'>{insight}</div>"

            # Recommendations
            if section.recommendations:
                html += "<h3>Recommendations</h3>"
                for rec in section.recommendations:
                    html += f"<div class='recommendation'>{rec}</div>"

            html += "</div>"

        html += """
        </body>
        </html>
        """

        return html


class DashboardBuilder:
    """Builder for creating stakeholder dashboards."""

    def __init__(self, organization_name: str):
        """Initialize dashboard builder."""
        self.dashboard = StakeholderDashboard(organization_name)

    def add_volume_metrics(
        self,
        vendors_processed: int,
        documents_analyzed: int,
        workflows_completed: int,
    ) -> "DashboardBuilder":
        """Add volume metrics section."""
        self.dashboard.add_metric(
            "Processing Volume",
            "vendors_processed",
            vendors_processed,
            "count",
            MetricCategory.VOLUME,
            description="Number of vendors processed",
        )

        self.dashboard.add_metric(
            "Processing Volume",
            "documents_analyzed",
            documents_analyzed,
            "count",
            MetricCategory.VOLUME,
            description="Total documents analyzed",
        )

        self.dashboard.add_metric(
            "Processing Volume",
            "workflows_completed",
            workflows_completed,
            "count",
            MetricCategory.VOLUME,
            description="Workflows completed successfully",
        )

        return self

    def add_quality_metrics(
        self,
        quality_score: float,
        accuracy: float,
        consistency: float,
    ) -> "DashboardBuilder":
        """Add quality metrics section."""
        self.dashboard.add_metric(
            "Quality Metrics",
            "quality_score",
            quality_score,
            "%",
            MetricCategory.QUALITY,
            target=90,
            description="Overall quality assessment score",
        )

        self.dashboard.add_metric(
            "Quality Metrics",
            "accuracy",
            accuracy * 100,
            "%",
            MetricCategory.QUALITY,
            target=95,
            description="Accuracy of assessments",
        )

        self.dashboard.add_metric(
            "Quality Metrics",
            "consistency",
            consistency * 100,
            "%",
            MetricCategory.QUALITY,
            target=90,
            description="Consistency across evaluations",
        )

        return self

    def add_performance_metrics(
        self,
        avg_latency: float,
        success_rate: float,
        throughput: float,
    ) -> "DashboardBuilder":
        """Add performance metrics section."""
        self.dashboard.add_metric(
            "System Performance",
            "avg_latency",
            avg_latency,
            "ms",
            MetricCategory.PERFORMANCE,
            target=1000,
            description="Average processing latency",
        )

        self.dashboard.add_metric(
            "System Performance",
            "success_rate",
            success_rate * 100,
            "%",
            MetricCategory.PERFORMANCE,
            target=99,
            description="Successful operations percentage",
        )

        self.dashboard.add_metric(
            "System Performance",
            "throughput",
            throughput,
            "ops/sec",
            MetricCategory.PERFORMANCE,
            description="Operations per second",
        )

        return self

    def add_cost_metrics(
        self,
        total_cost: float,
        cost_per_vendor: float,
        cost_optimization: float,
    ) -> "DashboardBuilder":
        """Add cost metrics section."""
        self.dashboard.add_metric(
            "Cost Analysis",
            "total_cost",
            total_cost,
            "$",
            MetricCategory.COST,
            description="Total operational cost",
        )

        self.dashboard.add_metric(
            "Cost Analysis",
            "cost_per_vendor",
            cost_per_vendor,
            "$/vendor",
            MetricCategory.COST,
            target=50,
            description="Average cost per vendor processed",
        )

        self.dashboard.add_metric(
            "Cost Analysis",
            "cost_optimization",
            cost_optimization * 100,
            "%",
            MetricCategory.COST,
            description="Cost optimization vs baseline",
        )

        return self

    def add_compliance_metrics(
        self,
        compliance_score: float,
        audit_passed: int,
        audit_total: int,
    ) -> "DashboardBuilder":
        """Add compliance metrics section."""
        pass_rate = (audit_passed / audit_total * 100) if audit_total > 0 else 0

        self.dashboard.add_metric(
            "Compliance",
            "compliance_score",
            compliance_score * 100,
            "%",
            MetricCategory.COMPLIANCE,
            target=100,
            description="Overall compliance score",
        )

        self.dashboard.add_metric(
            "Compliance",
            "audit_pass_rate",
            pass_rate,
            "%",
            MetricCategory.COMPLIANCE,
            target=100,
            description=f"Audit pass rate ({audit_passed}/{audit_total})",
        )

        return self

    def add_insights_and_recommendations(
        self,
        insights: Dict[str, List[str]],
        recommendations: Dict[str, List[str]],
    ) -> "DashboardBuilder":
        """Add insights and recommendations.

        Args:
            insights: Dict mapping section titles to lists of insights
            recommendations: Dict mapping section titles to lists of recommendations
        """
        for section, insight_list in insights.items():
            for insight in insight_list:
                self.dashboard.add_insight(section, insight)

        for section, rec_list in recommendations.items():
            for rec in rec_list:
                self.dashboard.add_recommendation(section, rec)

        return self

    def build(self) -> StakeholderDashboard:
        """Build and return the dashboard."""
        return self.dashboard
