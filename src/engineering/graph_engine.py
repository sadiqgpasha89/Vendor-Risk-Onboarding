"""Graph Engineering Module - Robust workflow graphs with state management and error handling."""

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from langgraph.graph import StateGraph, END
import json

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """Types of nodes in the workflow graph."""

    AGENT = "agent"
    DECISION = "decision"
    AGGREGATOR = "aggregator"
    ERROR_HANDLER = "error_handler"
    VALIDATOR = "validator"
    TRANSFORMER = "transformer"


class EdgeType(str, Enum):
    """Types of edges in the workflow graph."""

    NORMAL = "normal"
    CONDITIONAL = "conditional"
    ERROR = "error"
    RETRY = "retry"
    BYPASS = "bypass"


@dataclass
class NodeMetrics:
    """Metrics for a node execution."""

    node_id: str
    node_type: NodeType
    execution_time: float = 0.0
    call_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    success_rate: float = 1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GraphMetrics:
    """Metrics for entire graph execution."""

    graph_id: str
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    node_metrics: Dict[str, NodeMetrics] = field(default_factory=dict)
    total_path_length: int = 0
    total_retries: int = 0
    total_errors: int = 0

    def get_duration(self) -> float:
        """Get total execution duration."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()

    def get_node_summary(self) -> Dict[str, Any]:
        """Get summary of all node metrics."""
        return {
            node_id: {
                "type": metrics.node_type.value,
                "calls": metrics.call_count,
                "errors": metrics.error_count,
                "success_rate": metrics.success_rate,
                "avg_time": metrics.execution_time / max(metrics.call_count, 1),
            }
            for node_id, metrics in self.node_metrics.items()
        }


@dataclass
class GraphState:
    """State object for workflow graph."""

    graph_id: str
    current_node: str = "start"
    visited_nodes: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Optional[GraphMetrics] = None
    retry_count: int = 0
    status: str = "running"

    def add_error(self, error: str, node_id: Optional[str] = None) -> None:
        """Add error to state."""
        full_error = f"[{node_id}] {error}" if node_id else error
        self.errors.append(full_error)
        logger.error(f"Graph Error: {full_error}")

    def add_warning(self, warning: str, node_id: Optional[str] = None) -> None:
        """Add warning to state."""
        full_warning = f"[{node_id}] {warning}" if node_id else warning
        self.warnings.append(full_warning)
        logger.warning(f"Graph Warning: {full_warning}")

    def is_error_state(self) -> bool:
        """Check if graph is in error state."""
        return len(self.errors) > 0

    def has_data(self, key: str) -> bool:
        """Check if state has data for key."""
        return key in self.data


class GraphNode:
    """Represents a node in the workflow graph."""

    def __init__(
        self,
        node_id: str,
        node_type: NodeType,
        execute_func: Callable,
        error_handler: Optional[Callable] = None,
        retry_on_error: bool = False,
    ):
        """Initialize graph node.

        Args:
            node_id: Unique node identifier
            node_type: Type of node
            execute_func: Async function to execute
            error_handler: Optional error handling function
            retry_on_error: Whether to retry on error
        """
        self.node_id = node_id
        self.node_type = node_type
        self.execute_func = execute_func
        self.error_handler = error_handler
        self.retry_on_error = retry_on_error
        self.metrics = NodeMetrics(node_id=node_id, node_type=node_type)

    async def execute(self, state: GraphState) -> GraphState:
        """Execute the node.

        Args:
            state: Current graph state

            Returns:
            Updated graph state
        """
        import time

        start_time = time.time()
        self.metrics.call_count += 1

        try:
            result = await self.execute_func(state)
            execution_time = time.time() - start_time
            self.metrics.execution_time += execution_time
            state.visited_nodes.append(self.node_id)
            logger.info(
                f"Node '{self.node_id}' executed successfully in {execution_time:.2f}s"
            )
            return result

        except Exception as e:
            self.metrics.error_count += 1
            self.metrics.last_error = str(e)
            self.metrics.success_rate = (
                self.metrics.call_count - self.metrics.error_count
            ) / self.metrics.call_count
            state.add_error(str(e), self.node_id)

            if self.error_handler:
                logger.info(f"Executing error handler for node '{self.node_id}'")
                return await self.error_handler(state, e)

            raise


class GraphEdge:
    """Represents an edge in the workflow graph."""

    def __init__(
        self,
        source: str,
        target: str,
        edge_type: EdgeType = EdgeType.NORMAL,
        condition: Optional[Callable[[GraphState], bool]] = None,
    ):
        """Initialize graph edge.

        Args:
            source: Source node ID
            target: Target node ID
            edge_type: Type of edge
            condition: Optional condition function for conditional edges
        """
        self.source = source
        self.target = target
        self.edge_type = edge_type
        self.condition = condition

    def should_traverse(self, state: GraphState) -> bool:
        """Determine if this edge should be traversed."""
        if self.edge_type == EdgeType.CONDITIONAL:
            return self.condition(state) if self.condition else True
        return True


class WorkflowGraph:
    """Robust workflow graph implementation."""

    def __init__(self, name: str, graph_id: str):
        """Initialize workflow graph.

        Args:
            name: Name of the graph
            graph_id: Unique graph identifier
        """
        self.name = name
        self.graph_id = graph_id
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.metrics = GraphMetrics(graph_id=graph_id)

    def add_node(self, node: GraphNode) -> "WorkflowGraph":
        """Add a node to the graph."""
        self.nodes[node.node_id] = node
        return self

    def add_edge(self, edge: GraphEdge) -> "WorkflowGraph":
        """Add an edge to the graph."""
        self.edges.append(edge)
        return self

    def add_conditional_flow(
        self,
        source: str,
        condition_func: Callable[[GraphState], str],
        targets: Dict[str, Callable[[GraphState], bool]],
    ) -> "WorkflowGraph":
        """Add conditional flow logic.

        Args:
            source: Source node
            condition_func: Function that returns target node ID
            targets: Dictionary mapping conditions to target nodes
        """
        for target, cond in targets.items():
            edge = GraphEdge(
                source=source,
                target=target,
                edge_type=EdgeType.CONDITIONAL,
                condition=cond,
            )
            self.add_edge(edge)
        return self

    def add_error_path(self, source: str, target: str) -> "WorkflowGraph":
        """Add error recovery path."""
        edge = GraphEdge(source=source, target=target, edge_type=EdgeType.ERROR)
        self.add_edge(edge)
        return self

    def get_next_nodes(self, current_node: str, state: GraphState) -> List[str]:
        """Get valid next nodes based on current state."""
        next_nodes = []
        for edge in self.edges:
            if edge.source == current_node and edge.should_traverse(state):
                next_nodes.append(edge.target)
        return next_nodes

    async def execute(self) -> GraphState:
        """Execute the workflow graph.

        Returns:
            Final graph state
        """
        state = GraphState(graph_id=self.graph_id)
        state.metrics = self.metrics
        state.current_node = "start"

        logger.info(f"Starting graph execution: {self.name}")

        visited = set()
        max_steps = 1000  # Prevent infinite loops

        while state.current_node != END and len(visited) < max_steps:
            visited.add((state.current_node, len(visited)))

            if state.current_node not in self.nodes:
                if state.current_node == "start":
                    next_nodes = self.get_next_nodes("start", state)
                    if next_nodes:
                        state.current_node = next_nodes[0]
                        continue
                logger.warning(f"Node '{state.current_node}' not found in graph")
                break

            node = self.nodes[state.current_node]

            try:
                state = await node.execute(state)

                # Update metrics
                if state.current_node in self.metrics.node_metrics:
                    existing = self.metrics.node_metrics[state.current_node]
                    self.metrics.node_metrics[state.current_node] = node.metrics
                else:
                    self.metrics.node_metrics[state.current_node] = node.metrics

                # Get next nodes
                next_nodes = self.get_next_nodes(state.current_node, state)

                if not next_nodes:
                    if state.is_error_state():
                        state.status = "failed"
                    else:
                        state.status = "completed"
                    state.current_node = END
                else:
                    state.current_node = next_nodes[0]

            except Exception as e:
                logger.error(f"Error executing node '{state.current_node}': {e}")
                state.status = "error"
                state.current_node = END
                break

        self.metrics.end_time = datetime.utcnow()
        self.metrics.total_path_length = len(visited)

        logger.info(
            f"Graph execution completed: {self.name} "
            f"in {self.metrics.get_duration():.2f}s. "
            f"Status: {state.status}"
        )

        return state

    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        return {
            "graph_name": self.name,
            "graph_id": self.graph_id,
            "duration": self.metrics.get_duration(),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_metrics": self.metrics.get_node_summary(),
            "total_errors": self.metrics.total_errors,
            "total_retries": self.metrics.total_retries,
        }


class GraphBuilder:
    """Builder pattern for constructing complex graphs."""

    def __init__(self, name: str, graph_id: str):
        """Initialize graph builder."""
        self.graph = WorkflowGraph(name, graph_id)

    def add_agent_node(
        self,
        node_id: str,
        execute_func: Callable,
        error_handler: Optional[Callable] = None,
    ) -> "GraphBuilder":
        """Add an agent node."""
        node = GraphNode(
            node_id=node_id,
            node_type=NodeType.AGENT,
            execute_func=execute_func,
            error_handler=error_handler,
            retry_on_error=True,
        )
        self.graph.add_node(node)
        return self

    def add_decision_node(
        self,
        node_id: str,
        decision_func: Callable,
    ) -> "GraphBuilder":
        """Add a decision node."""
        node = GraphNode(
            node_id=node_id,
            node_type=NodeType.DECISION,
            execute_func=decision_func,
        )
        self.graph.add_node(node)
        return self

    def connect(
        self,
        source: str,
        target: str,
        condition: Optional[Callable[[GraphState], bool]] = None,
    ) -> "GraphBuilder":
        """Connect two nodes."""
        edge = GraphEdge(
            source=source,
            target=target,
            edge_type=EdgeType.CONDITIONAL if condition else EdgeType.NORMAL,
            condition=condition,
        )
        self.graph.add_edge(edge)
        return self

    def build(self) -> WorkflowGraph:
        """Build and return the graph."""
        return self.graph
