"""Task type constants for Hermes Pulse.

Use these instead of string literals throughout the codebase.
"""

TASK_BRAINSTORM = "brainstorm"
TASK_CODING = "coding"
TASK_RESEARCH = "research"
TASK_WRITING = "writing"
TASK_CHAT = "chat"

ALL_TASK_TYPES = {TASK_BRAINSTORM, TASK_CODING, TASK_RESEARCH, TASK_WRITING, TASK_CHAT}

NON_CODING = {TASK_BRAINSTORM, TASK_RESEARCH, TASK_WRITING, TASK_CHAT}
NON_ANALYTICAL = {TASK_BRAINSTORM, TASK_RESEARCH}

# Tool sets
READ_TOOLS = {"read_file", "search_files", "web_extract", "web_search", "vision_analyze"}
WRITE_TOOLS = {"write_file", "patch"}
RESEARCH_TOOLS = {"web_search", "web_extract", "session_search", "browser_exec"}