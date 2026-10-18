"""Contract adapter for external v0.2 personal assessment. Scoring stays in the MCP server."""
import asyncio
import os
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from backend.app.config import ROOT
from backend.app.contracts import PersonInput, PersonAssessment as Assessment, PersonPriority as Priority, person_age_group as age_group
from backend.agents.scale import validate_score
from backend.tools.indicators import digest



class PersonAdapter:
    def __init__(self,store,settings):self.store,self.settings=store,settings

    async def remote(self,tool,args):
        if self.settings.person_mcp_mode=='stub':
            if self.settings.data_mode!='sample':raise ValueError('stub only allowed for synthetic sample')
            params=StdioServerParameters(command=sys.executable,args=['-m','backend.agents.person_stub'],cwd=str(ROOT))
        else:
            if not self.settings.mcp_python:raise ValueError('MCP_PYTHON required')
            params=StdioServerParameters(command=self.settings.mcp_python,args=['-m','beyond_hello_mcp.server'],
                cwd=str(self.settings.mcp_cwd) if self.settings.mcp_cwd else None)
        with open(os.devnull,'w') as log:
            async with stdio_client(params,errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    response=await session.call_tool(tool,args)
                    if response.is_error or not isinstance(response.structured_content,dict):raise ValueError('MCP result unavailable')
                    return response.structured_content

    def call(self,run_id,sim_time,tool,args):
        if tool not in ('assess_stage','priority_score'):raise ValueError('unsupported personal tool')
        mode=self.settings.person_mcp_mode;started=time.monotonic()
        self.store.append_trace(run_id,sim_time,'tool_call',{'tool':tool,'input_hash':digest(args),'mode':mode},'classify')
        try:
            async def invoke():return await asyncio.wait_for(self.remote(tool,args),self.settings.mcp_timeout_seconds)
            raw=asyncio.run(invoke())
            if raw.get('status')=='incomplete':
                output={'status':'assessment_pending','result':None,'mode':mode,'followup_questions':raw.get('followup_questions',[]),'human_review_required':True}
            else:
                result=(Assessment if tool=='assess_stage' else Priority).model_validate(raw)
                version=result.rule_version if tool=='assess_stage' else result.scorecard_version
                if mode=='live' and (version.startswith('stub') or getattr(result,'status',None)=='stub'):raise ValueError('stub cannot be a live assessment')
                if tool=='assess_stage':
                    if result.lsis6 is not None:validate_score(result.lsis6)
                    # High stages and crisis always require people, even if a provider flag is inconsistent.
                    if (result.stage>=4 or result.crisis) and not result.human_handoff:
                        result.human_handoff=True;result.warnings.append('MAS enforced mandatory human handoff')
                elif result.status in ('error','failed','unavailable'):
                    raise ValueError('priority result is not available')
                elif args['age_group'] in ('midlife','elderly') and result.grade is not None:
                    raise ValueError('this age group has no validated grade boundaries')
                output={'status':'assessed','result':result.model_dump(mode='json'),'mode':mode,'synthetic':mode=='stub','human_review_required':True}
        except Exception as exc:
            output={'status':'unavailable','result':None,'mode':mode,'error':type(exc).__name__,'human_review_required':True}
        self.store.append_trace(run_id,sim_time,'tool_result',{'tool':tool,**output},'classify',latency_ms=(time.monotonic()-started)*1000)
        return output

    def assess(self,run_id,sim_time,request):
        request=PersonInput.model_validate(request)
        return self.call(run_id,sim_time,'assess_stage',request.model_dump())

    def priority(self,run_id,sim_time,group,features):
        if group not in ('youth','midlife','prime','elderly') or not isinstance(features,dict):raise ValueError('invalid priority request')
        return self.call(run_id,sim_time,'priority_score',{'age_group':group,'features':features})
