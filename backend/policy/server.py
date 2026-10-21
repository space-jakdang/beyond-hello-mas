"""Run with uv run python -m backend.policy.server (stdio only)."""
from typing import Any, Annotated
from pydantic import Field
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
def policy_search(scopes:Annotated[list[Scope],Field(min_length=1,max_length=5)],query:Annotated[str,Field(max_length=200)]='',page:Annotated[int,Field(ge=1,le=10000)]=1,per_page:Annotated[int,Field(ge=1,le=100)]=20)->dict[str,Any]:
    """Search cached policies. Empty query lists all scoped policies; follow next_page for all results."""
    return service.search(Search(scopes=scopes,query=query,page=page,per_page=per_page))


@mcp.tool()
def policy_detail(policy_id:str)->dict[str,Any]:
    """Check latest official detail and support conditions. Eligibility and remaining capacity remain unverified."""
    return service.detail(policy_id)


@mcp.tool()
def policy_analogues(local_scope:Scope,query:Annotated[str,Field(min_length=1,max_length=200)],target_group:Annotated[str,Field(min_length=1,max_length=200)])->dict[str,Any]:
    """Research up to five other-scope official examples. Similarity and local eligibility remain unverified."""
    from backend.policy.analogues import research,AnalogueRequest
    return research(service,AnalogueRequest(local_scope=local_scope,query=query,target_group=target_group))


if __name__=='__main__':mcp.run(transport='stdio')
