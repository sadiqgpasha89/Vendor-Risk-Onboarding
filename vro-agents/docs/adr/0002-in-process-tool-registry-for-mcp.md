# ADR-0002: In-process tool registry stands in for MCP servers
Status: accepted (deviation)
Decision: `vro/tools.py` implements least-privilege tools per agent (`ALLOWED_TOOLS`), taint tracking and audit of every call. Agent A4 (Reader) has no tools. No approve/reject/clear/send tool exists (R3).
Consequences: The interface is MCP-shaped so tools can move behind real MCP servers without changing agents.
