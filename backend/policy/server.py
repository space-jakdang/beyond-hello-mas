"""Run with uv run python -m backend.policy.server (stdio only)."""
from typing import Any
from mcp.server.mcpserver import MCPServer
from backend.app.config import Settings
from backend.policy.service import PolicyService,Search,Scope

mcp=MCPServer('beyond-hello-policy')
service=PolicyService(Settings(llm_mode='fake'))


@mcp.tool()
def policy_coverage()->dict[str,Any]:
    """Report five-scope coverage, freshness, credentials and failures. Never implies all real policies are known."""
    return service.coverage()


@mcp.tool()
def policy_refresh()->dict[str,Any]:
    """Fetch all registered government API pages within limits; preserve old inventory on failure."""
    return service.refresh()


@mcp.tool()
def policy_search(scopes:list[Scope],query:str='',page:int=1,per_page:int=20)->dict[str,Any]:
    """Search cached policies. Empty query lists all scoped policies; follow next_page for all results."""
    return service.search(Search(scopes=scopes,query=query,page=page,per_page=per_page))


@mcp.tool()
def policy_detail(policy_id:str)->dict[str,Any]:
    """Check latest official detail and support conditions. Eligibility and remaining capacity remain unverified."""
    return service.detail(policy_id)


if __name__=='__main__':mcp.run(transport='stdio')
