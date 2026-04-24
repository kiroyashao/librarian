from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class ToolSynthesizer(BaseWorker):
    """Creates new tools when skills reference missing tools.

    Uses LLM to generate tool implementations following the naming
    convention tool_<skill_name>_<function_name>.

    Attributes:
        _llm: The LangChain ChatOpenAI instance for tool generation.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.tool_synthesizer.llm
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.tool_synthesizer.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Create tools for missing tool references.

        Args:
            state: Workflow state with 'missing_tools' list and 'tools_dir'.

        Returns:
            Updated state with 'created_tools' list of tool dicts.
        """
        missing_tools: list[str] = state.get("missing_tools", [])
        tools_dir = state.get("tools_dir")
        created_tools: list[dict] = []

        for tool_name in missing_tools:
            tool_content = self._generate_tool(tool_name, state)
            if tool_content and tools_dir:
                from pathlib import Path
                tool_path = Path(tools_dir) / tool_name
                tool_path.parent.mkdir(parents=True, exist_ok=True)
                tool_path.write_text(tool_content, encoding="utf-8")
                created_tools.append({
                    "name": tool_name,
                    "path": str(tool_path),
                    "status": "created",
                })

        state["created_tools"] = created_tools
        return state

    def _generate_tool(self, tool_name: str, state: dict[str, Any]) -> str | None:
        """Generate tool implementation using LLM.

        Args:
            tool_name: Name of the tool to create.
            state: Current workflow state for context.

        Returns:
            The tool implementation as a string, or None on failure.
        """
        if self._llm is None:
            return self._fallback_tool(tool_name)

        skill_context = ""
        for skill_data in state.get("pending_skills", []):
            if tool_name in skill_data.get("content", ""):
                skill_context = skill_data.get("content", "")[:1000]
                break

        prompt = (
            f"Create a shell script tool named '{tool_name}'.\n"
            f"Naming convention: tool_<skill_name>_<function_name>\n"
            f"The tool should be a bash script with proper error handling.\n"
            f"Context from the skill that needs this tool:\n{skill_context}\n\n"
            f"Return only the script content, starting with #!/bin/bash"
        )
        try:
            response = self._llm.invoke(prompt)
            content = response.content.strip()
            if content.startswith("#!/bin/bash") or content.startswith("#!/usr/bin/env"):
                return content
            return f"#!/bin/bash\n{content}"
        except Exception:
            return self._fallback_tool(tool_name)

    def _fallback_tool(self, tool_name: str) -> str:
        """Generate a placeholder tool script.

        Args:
            tool_name: Name of the tool.

        Returns:
            A basic placeholder bash script.
        """
        return f"""#!/bin/bash
# Tool: {tool_name}
# Auto-generated placeholder tool
set -e

echo "Tool {tool_name} executed with args: $@"
"""
