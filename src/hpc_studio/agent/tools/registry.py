"""Native Agent Tools and Sandbox Security for HPC Studio Linux.

Provides tool registration, risk level evaluation, human-in-the-loop approval,
and execution of agent tools.
Zero-Emoji compliant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import inspect
import logging
import os
import pathlib
import shlex
import subprocess
from typing import Any, Callable, Dict, List, Optional, Set, Union, get_type_hints

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Classification of action security risks for agent tool calls."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    # Backward compatibility aliases
    READ_ONLY = "LOW"
    MODERATE = "MEDIUM"


@dataclass
class ToolParameter:
    """Schema descriptor for an agent tool parameter."""

    name: str
    param_type: str = "string"  # JSON-schema types: string, integer, number, boolean, object, array
    description: str = ""
    required: bool = True
    default: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert parameter specification to JSON-friendly schema dict."""
        res: Dict[str, Any] = {
            "type": self.param_type,
            "description": self.description,
            "required": self.required,
        }
        if self.default is not None:
            res["default"] = self.default
        return res


@dataclass
class ToolDefinition:
    """Specification of an agent-executable native tool."""

    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    parameters: Union[List[ToolParameter], Dict[str, Any]] = field(default_factory=list)
    handler: Optional[Callable[..., Any]] = None
    requires_approval: bool = False

    def to_schema(self) -> Dict[str, Any]:
        """Generate OpenAI/Anthropic/Antigravity compatible tool schema."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        if isinstance(self.parameters, list):
            for p in self.parameters:
                properties[p.name] = {
                    "type": p.param_type,
                    "description": p.description,
                }
                if p.default is not None:
                    properties[p.name]["default"] = p.default
                if p.required:
                    required.append(p.name)
        elif isinstance(self.parameters, dict):
            for p_name, p_type in self.parameters.items():
                properties[p_name] = {
                    "type": p_type if isinstance(p_type, str) else "string",
                    "description": "",
                }
                required.append(p_name)

        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class SecurityPolicyError(PermissionError):
    """Raised when a tool call violates sandbox or safety restrictions."""

    pass


class ToolSandbox:
    """Enforces sandbox restrictions on filesystem paths and commands."""

    def __init__(
        self,
        workspace_root: str,
        allowed_read_paths: Optional[List[str]] = None,
        allowed_command_prefixes: Optional[List[str]] = None,
    ) -> None:
        self.workspace_root = os.path.realpath(workspace_root)
        self.allowed_read_paths = [os.path.realpath(p) for p in (allowed_read_paths or [])]
        if self.workspace_root not in self.allowed_read_paths:
            self.allowed_read_paths.append(self.workspace_root)
        self.allowed_command_prefixes = allowed_command_prefixes or [
            "squeue",
            "sinfo",
            "sbatch",
            "scancel",
            "sacct",
            "ls",
            "cat",
            "echo",
            "pwd",
            "grep",
            "find",
            "wc",
            "head",
            "tail",
            "diff",
        ]

    def validate_path(self, target_path: str, for_write: bool = False) -> str:
        """Validate and resolve target path ensuring no path traversal escapes."""
        if not target_path or not str(target_path).strip():
            raise SecurityPolicyError("Path cannot be empty.")

        if "\x00" in str(target_path):
            raise SecurityPolicyError("Null bytes are prohibited in file paths.")

        # Resolve path
        if not os.path.isabs(target_path):
            abs_path = os.path.abspath(os.path.join(self.workspace_root, target_path))
        else:
            abs_path = os.path.abspath(target_path)

        # Realpath resolves all symlinks
        real_path = os.path.realpath(abs_path)
        real_workspace = os.path.realpath(self.workspace_root)

        # Disallow writing outside workspace root
        if for_write:
            try:
                rel = os.path.relpath(real_path, real_workspace)
                if rel.startswith("..") or rel == "..":
                    raise SecurityPolicyError(
                        f"Write access denied: Path '{abs_path}' resolves outside workspace '{real_workspace}'."
                    )
            except ValueError:
                raise SecurityPolicyError("Cross-drive access denied.")
            return real_path

        # Read access validation
        is_allowed = False
        for allowed in self.allowed_read_paths:
            real_allowed = os.path.realpath(allowed)
            try:
                rel = os.path.relpath(real_path, real_allowed)
                if not rel.startswith("..") and rel != "..":
                    is_allowed = True
                    break
            except ValueError:
                continue

        if not is_allowed:
            raise SecurityPolicyError(
                f"Read access denied: Path '{abs_path}' resolves outside permitted read locations."
            )

        return real_path

    def validate_command(self, command: str) -> List[str]:
        """Validate command string against disallowed primitives or injection patterns."""
        cmd_clean = command.strip()
        if not cmd_clean:
            raise SecurityPolicyError("Command cannot be empty.")

        if "\x00" in cmd_clean:
            raise SecurityPolicyError("Null bytes are prohibited in command execution.")

        # Dangerous operators and tokens check
        dangerous_patterns = [";", "&&", "||", "`", "$(", ">", "<", "|", "\n", "\r", "${"]
        for pattern in dangerous_patterns:
            if pattern in cmd_clean:
                raise SecurityPolicyError(
                    f"Shell metacharacter '{repr(pattern)[1:-1]}' is not permitted in sandbox command execution."
                )

        # Disallow single '&' (background execution)
        if "&" in cmd_clean:
            raise SecurityPolicyError(
                "Shell metacharacter '&' is not permitted in sandbox command execution."
            )

        args = shlex.split(cmd_clean)
        if not args:
            raise SecurityPolicyError("Invalid empty parsed command.")

        base_cmd = os.path.basename(args[0])
        if base_cmd not in self.allowed_command_prefixes:
            raise SecurityPolicyError(
                f"Command '{base_cmd}' is not in the whitelist of permitted commands."
            )

        # Prevent sub-execution via flags in allowed utilities
        if base_cmd == "find":
            for arg in args[1:]:
                if arg in ("-exec", "-execdir", "-ok", "-okdir"):
                    raise SecurityPolicyError(
                        f"Argument '{arg}' is not permitted for 'find' command in sandbox."
                    )

        return args


class ApprovalGate:
    """Manages human-in-the-loop approvals for moderate/high risk tool executions."""

    def __init__(self) -> None:
        self.session_approved_tools: Set[str] = set()
        self._interactive_callback: Optional[Callable[[str, Dict[str, Any], RiskLevel], bool]] = None

    def set_interactive_callback(
        self,
        callback: Callable[[str, Dict[str, Any], RiskLevel], bool],
    ) -> None:
        """Register interactive modal dialog or verification hook."""
        self._interactive_callback = callback

    def request_approval(
        self,
        tool_name: str,
        args: Dict[str, Any],
        risk_level: RiskLevel,
        remember_for_session: bool = False,
    ) -> bool:
        """Evaluate approval status or trigger user interaction."""
        if risk_level in (RiskLevel.LOW, RiskLevel.READ_ONLY):
            return True

        if tool_name in self.session_approved_tools:
            return True

        if self._interactive_callback is not None:
            approved = self._interactive_callback(tool_name, args, risk_level)
            if approved and remember_for_session:
                self.session_approved_tools.add(tool_name)
            return approved

        # Without callback, moderate/high/critical risk is rejected by default
        return False


class ToolRegistry:
    """Central repository and execution dispatcher for agent tools."""

    def __init__(
        self,
        sandbox: Optional[ToolSandbox] = None,
        approval_gate: Optional[ApprovalGate] = None,
        load_defaults: bool = False,
    ) -> None:
        self.sandbox = sandbox or ToolSandbox(workspace_root=os.getcwd())
        self.approval_gate = approval_gate or ApprovalGate()
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a new native tool (backward compatibility alias)."""
        self.register_tool(tool_def)

    def register_tool(
        self,
        tool_or_name: ToolDefinition | str,
        description: str = "",
        risk_level: RiskLevel = RiskLevel.LOW,
        parameters: Optional[Union[List[ToolParameter], Dict[str, Any]]] = None,
        handler: Optional[Callable[..., Any]] = None,
        requires_approval: bool = False,
    ) -> ToolDefinition:
        """Register a tool definition into the registry."""
        if isinstance(tool_or_name, ToolDefinition):
            tool_def = tool_or_name
        else:
            tool_def = ToolDefinition(
                name=tool_or_name,
                description=description,
                risk_level=risk_level,
                parameters=parameters or [],
                handler=handler,
                requires_approval=requires_approval,
            )

        if not tool_def.name:
            raise ValueError("Tool name cannot be empty.")
        if not tool_def.handler or not callable(tool_def.handler):
            raise ValueError(f"Tool '{tool_def.name}' must have a callable handler.")

        self._tools[tool_def.name] = tool_def
        logger.debug("Registered tool [%s] with risk [%s]", tool_def.name, tool_def.risk_level.value)
        return tool_def

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Look up tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Return list of all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return JSON-serializable tool schemas for LLM system prompts."""
        return [tool.to_schema() for tool in self._tools.values()]

    def validate_tool_args_security(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Validate tool arguments against sandbox constraints."""
        if tool_name in ("read_file",):
            p = args.get("path", "")
            self.sandbox.validate_path(p, for_write=False)
        elif tool_name in ("edit_file",):
            p = args.get("path", "")
            self.sandbox.validate_path(p, for_write=True)
        elif tool_name in ("run_command",):
            cmd = args.get("command", "")
            self.sandbox.validate_command(cmd)
            cwd = args.get("cwd", "")
            if cwd:
                self.sandbox.validate_path(cwd, for_write=False)
        elif tool_name in ("slurm_submit",):
            sp = args.get("script_path", "")
            if sp:
                self.sandbox.validate_path(sp, for_write=False)
        elif tool_name in ("qe_validate",):
            ip = args.get("input_path", "")
            if ip:
                self.sandbox.validate_path(ip, for_write=False)

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        remember_session_approval: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a tool with risk validation, sandboxing and approval verification."""
        tool = self.get_tool(tool_name)
        if not tool:
            raise KeyError(f"Tool '{tool_name}' is not registered.")

        # Check approval gate
        if tool.requires_approval or tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            is_approved = self.approval_gate.request_approval(
                tool_name=tool_name,
                args=args,
                risk_level=tool.risk_level,
                remember_for_session=remember_session_approval,
            )
            if not is_approved:
                raise SecurityPolicyError(
                    f"Execution of tool '{tool_name}' ({tool.risk_level.value}) was rejected by user approval policy."
                )

        # Enforce sandbox validation on tool arguments
        self.validate_tool_args_security(tool_name, args)

        call_context = dict(context or {})
        call_context["sandbox"] = self.sandbox
        call_context["approval_gate"] = self.approval_gate

        return self._invoke_handler(tool, args, call_context)

    def execute_tool(
        self,
        name: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a tool handler with security policy and sandbox enforcement."""
        tool = self.get_tool(name)
        if not tool:
            raise KeyError(f"Tool '{name}' is not registered in ToolRegistry.")

        # Require approval for HIGH and CRITICAL tools to prevent bypass
        if tool.requires_approval or tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            is_approved = self.approval_gate.request_approval(
                tool_name=name,
                args=args or {},
                risk_level=tool.risk_level,
                remember_for_session=False,
            )
            if not is_approved:
                raise SecurityPolicyError(
                    f"Execution of tool '{name}' ({tool.risk_level.value}) was rejected by user approval policy."
                )

        # Enforce sandbox validation on tool arguments
        self.validate_tool_args_security(name, args or {})

        call_context = dict(context or {})
        call_context["sandbox"] = self.sandbox
        call_context["approval_gate"] = self.approval_gate

        return self._invoke_handler(tool, args or {}, call_context)

    def _invoke_handler(
        self,
        tool: ToolDefinition,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Internal dispatch of tool handler passing arguments and context."""
        if not tool.handler:
            raise RuntimeError(f"Tool '{tool.name}' has no executable handler.")

        call_args = dict(args)

        sig = inspect.signature(tool.handler)
        if "context" in sig.parameters:
            call_args["context"] = context or {}

        try:
            return tool.handler(**call_args)
        except Exception as exc:
            logger.error("Failed executing tool [%s]: %s", tool.name, exc, exc_info=True)
            raise


# Global singleton registry instance
_default_registry: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """Retrieve or initialize the global singleton ToolRegistry with native tools."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        # Import native tools to ensure registration
        from . import hpc_tools  # noqa: F401
    return _default_registry


def hpc_tool(
    name: str,
    description: str,
    risk_level: RiskLevel = RiskLevel.LOW,
    parameters: Optional[List[ToolParameter]] = None,
    registry: Optional[ToolRegistry] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a function as an HPC Studio tool."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        params = list(parameters) if parameters is not None else []

        if parameters is None:
            sig = inspect.signature(fn)
            try:
                hints = get_type_hints(fn)
            except Exception:
                hints = {}

            for p_name, param in sig.parameters.items():
                if p_name == "context":
                    continue

                p_type_hint = hints.get(p_name, str)
                type_name = "string"
                if p_type_hint in (int, "int"):
                    type_name = "integer"
                elif p_type_hint in (float, "float"):
                    type_name = "number"
                elif p_type_hint in (bool, "bool"):
                    type_name = "boolean"
                elif p_type_hint in (dict, "dict", Dict):
                    type_name = "object"
                elif p_type_hint in (list, "list", List):
                    type_name = "array"

                has_default = param.default is not inspect.Parameter.empty
                params.append(
                    ToolParameter(
                        name=p_name,
                        param_type=type_name,
                        description="",
                        required=not has_default,
                        default=param.default if has_default else None,
                    )
                )

        target_reg = registry or get_default_registry()
        target_reg.register_tool(
            tool_or_name=name,
            description=description,
            risk_level=risk_level,
            parameters=params,
            handler=fn,
            requires_approval=risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
        )
        return fn

    return decorator