"""Official MCP stdio transport for the existing agent tool gateway.

Thin adapter only: all validation, idempotency, owner policy, journaling and
locks stay in ``agentos_runtime.gateway.AgentGateway``. This module maps
``tools/list`` and ``tools/call`` onto ``gateway.tools()``/``gateway.call()``.
stdio transport only; no network listener. Protocol frames on stdout are
UTF-8 JSON-RPC owned by ``mcp.server.stdio``; diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .errors import RuntimeFault
from .gateway import AgentGateway

SERVER_NAME = 'agentos-runtime-mcp'


def create_server(home: Path) -> Server:
    """Build an MCP ``Server`` bound to an owner-initialized gateway home.

    ``AgentGateway(home)`` re-validates the home (owner policy, dataset
    registry, registry version); nothing is created here as a side effect.
    """
    gateway = AgentGateway(Path(home))
    listed = gateway.tools()

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=tool['name'], description=tool['description'],
                       input_schema=tool['inputSchema'])
            for tool in listed])

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        arguments = params.arguments if isinstance(params.arguments, dict) else {}
        # Gateway calls are synchronous and may hold workspace locks; run them
        # on a worker thread so the JSON-RPC loop stays responsive and a
        # RPC cancellation stops awaiting this call; its worker may continue.
        # Owners use task_cancel and inspect state before attempting resume.
        envelope = await anyio.to_thread.run_sync(
            lambda: gateway.call(params.name, arguments), abandon_on_cancel=True)
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(envelope, ensure_ascii=False))],
            structured_content=envelope,
            is_error=not envelope['ok'])

    return Server(SERVER_NAME, version=__version__,
                  on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='agentos-mcp',
        description='MCP stdio server exposing the 8 gateway tools; stdio only, no listener.')
    parser.add_argument('--home', type=Path, required=True,
                        help='owner-initialized task space (see: agentos init-demo)')
    args = parser.parse_args(argv)
    try:
        server = create_server(args.home)
    except (RuntimeFault, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, RuntimeFault) else 'CONFIG_OR_IO_ERROR'
        print(json.dumps({'status': 'REJECTED', 'error_code': code}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    init_options = server.create_initialization_options()

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)

    print(f'{SERVER_NAME} {__version__}: serving 8 tools over stdio', file=sys.stderr)
    try:
        anyio.run(serve)
    except KeyboardInterrupt:
        return 2
    except Exception:
        print(json.dumps({'status': 'REJECTED', 'error_code': 'MCP_TRANSPORT_ERROR'},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
