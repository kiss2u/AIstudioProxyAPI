"""
Logging Context Variables
"""

from contextvars import ContextVar
from typing import List

# =============================================================================
# Context Variables (Thread-safe request tracking)
# =============================================================================

# Request ID for the current context (e.g., 'akvdate')
request_id_var: ContextVar[str] = ContextVar("request_id", default="       ")

# Source identifier for the current context (e.g., 'SERVER', 'PROXY')
source_var: ContextVar[str] = ContextVar("source", default="SYS")

# Tree depth for hierarchical logging (0 = root level)
tree_depth_var: ContextVar[int] = ContextVar("tree_depth", default=0)

# Stack tracking whether each tree level continues (for proper pipe rendering)
tree_stack_var: ContextVar[List[bool]] = ContextVar("tree_stack", default=[])

# Flag indicating if current log is the last in a context block
is_last_in_context_var: ContextVar[bool] = ContextVar(
    "is_last_in_context", default=False
)
