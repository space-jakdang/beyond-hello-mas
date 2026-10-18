"""Synthetic MCP protocol fixtures only. Never implements or approximates clinical scoring."""
from typing import Any
from mcp.server.mcpserver import MCPServer
from backend.agents.person import PersonInput

mcp=MCPServer('synthetic-person-v02')
WARNING='SYNTHETIC_STUB: contract fixture; no clinical scoring or real scorecard applied'


@mcp.tool()
def assess_stage(age_group:str,age:int,responses:dict,admin_flags:dict)->dict[str,Any]:
    """Synthetic fixture. synthetic-contract-fixture.case selects 201 (handoff), 202 (crisis), 203 (care)."""
    request=PersonInput(age=age,age_group=age_group,responses=responses,admin_flags=admin_flags)
    fixture=request.responses.get('synthetic-contract-fixture',{}).get('case',0)
    if not request.responses:
        return {'status':'incomplete','followup_questions':['검증된 문항 응답을 확인해야 합니다.'],'warnings':[WARNING]}
    stage={201:4,202:5}.get(fixture,2)
    return {'stage':stage,'track':'care_health' if fixture==203 else 'isolation','rules_applied':['synthetic-fixture'],
        'drivers':[],'human_handoff':stage>=4,'crisis':fixture==202,'followup_questions':[],
        'lsis6':None,'rule_version':'stub-v02','sources':['synthetic protocol fixture'],'warnings':[WARNING],
        'safety_notice':'실제 판정이 아닙니다. 사람의 확인이 필요합니다.'}


@mcp.tool()
def priority_score(age_group:str,features:dict)->dict[str,Any]:
    """Synthetic zero score with no inferred grade or band. Real scorecards stay external."""
    if age_group not in ('youth','midlife','prime','elderly'):raise ValueError('invalid age group')
    return {'score':0,'grade':None,'band':None,'contributions':[],'scorecard_version':'stub-v02',
        'status':'stub','sources':['synthetic protocol fixture'],'warnings':[WARNING]}


if __name__=='__main__':mcp.run(transport='stdio')
