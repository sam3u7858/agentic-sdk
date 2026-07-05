# src/ai_core/tool_executor.py
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Union

logger = logging.getLogger(__name__)

class BaseTool(ABC):
    """Abstract base class for all Agent tools"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (identifier used by LLM, limited to alphanumeric and underscore)"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description (tells LLM when to use this tool)"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema parameters block (defines input parameters)"""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Union[str, Dict[str, Any]]:
        """Actual tool execution logic, should return string or structured payload"""
        pass

    def get_schema(self) -> Dict[str, Any]:
        """Automatically assemble properties into an LLM-supported Function Calling Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }

class ToolExecutor:
    """Manages and executes registered tools"""
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a single tool"""
        if not isinstance(tool, BaseTool):
            raise TypeError("Tool must inherit from BaseTool")
        self._tools[tool.name] = tool
        logger.info(f"Successfully registered tool: {tool.name}")

    def register_tools(self, tools: List[BaseTool]) -> None:
        """Batch register tools"""
        for tool in tools:
            self.register_tool(tool)

    @property
    def schemas(self) -> List[Dict[str, Any]]:
        """Get a list of all registered tool schemas, ready to feed to LLM"""
        return [tool.get_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
        """Execute the specified tool and capture exceptions"""
        if tool_name not in self._tools:
            return f"Error: 系統中找不到工具 '{tool_name}'"
        
        try:
            # 展開 arguments 傳入工具的 execute 函式
            result = self._tools[tool_name].execute(**arguments)
            if isinstance(result, dict):
                return result
            return str(result)
        except Exception as e:
            logger.exception(f"執行工具 '{tool_name}' 時發生異常")
            return f"Error: 執行工具 '{tool_name}' 時發生異常: {str(e)}"