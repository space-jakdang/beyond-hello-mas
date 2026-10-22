"""Call the existing private MCP installation; never copy its scoring rules."""
import asyncio
import json
import os
import subprocess
import time

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.tools.indicators import digest

# Both transport and optional fallback use the same interpreter, cwd and package files.
PACKAGE_INFO = '''import hashlib,json,importlib.metadata
from pathlib import Path
from beyond_hello_mcp import scoring
p=Path(scoring.__file__)
print(json.dumps({'package_version':importlib.metadata.version('beyond-hello-mcp'),
'scoring_hash':hashlib.sha256(p.read_bytes()).hexdigest(),
'scale_hash':hashlib.sha256((p.parent/'scales/lsis-6.yaml').read_bytes()).hexdigest()}))'''
DIRECT_SCORE = '''import json,sys
from beyond_hello_mcp.scoring import score
print(json.dumps(score('lsis-6',json.load(sys.stdin)),ensure_ascii=False))'''


def validate_responses(responses):
    if (not isinstance(responses, dict) or set(responses) != {f'q{i}' for i in range(1, 7)} or
            any(type(v) is not int or v not in range(4) for v in responses.values())):
        raise ValueError('LSIS-6 requires exactly q1..q6 with explicit integer option values 0..3')


def validate_score(result):
    if (not isinstance(result, dict) or result.get('scale_id') != 'lsis-6' or result.get('version') != '1.0.0'
            or result.get('status') != 'verified' or not isinstance(result.get('source'), dict) or not result['source'].get('citation')
            or not isinstance(result.get('safety_note'), str) or not result['safety_note']):
        raise ValueError('unexpected LSIS-6 result contract/version')
    subscales = result.get('subscales', {})
    if set(subscales) != {'loneliness', 'support', 'network'} or any(type(v) is not int or not 0 <= v <= 6 for v in subscales.values()):
        raise ValueError('invalid LSIS-6 subscales')
    if not isinstance(result.get('matched'), list) or any(not isinstance(r, dict) or r.get('label') not in {'외로움 고위험군', '사회적 고립 고위험군'} for r in result['matched']):
        raise ValueError('invalid LSIS-6 matched results')
    return result


class ScaleAdapter:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def local_python(self, program, responses=None):
        completed = subprocess.run([self.settings.mcp_python, '-c', program], cwd=self.settings.mcp_cwd,
            input=json.dumps(responses), text=True, capture_output=True, timeout=self.settings.mcp_timeout_seconds)
        if completed.returncode:
            raise ValueError('local MCP package command failed; details omitted')
        return json.loads(completed.stdout)

    async def remote(self, responses):
        parameters = StdioServerParameters(command=self.settings.mcp_python, args=['-m', 'beyond_hello_mcp.server'],
                                           cwd=str(self.settings.mcp_cwd) if self.settings.mcp_cwd else None)
        with open(os.devnull, 'w') as log:
            async with stdio_client(parameters, errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    response = await session.call_tool('score', {'scale_id': 'lsis-6', 'responses': responses})
                    if response.is_error:
                        raise ValueError('MCP rejected score request')
                    return validate_score(response.structured_content)

    def score(self, run_id, sim_ts, responses):
        if responses is None:
            return {'status': 'assessment_pending', 'result': None}
        validate_responses(responses)
        if not self.settings.mcp_python:
            raise ValueError('MCP_PYTHON is required for explicit scale responses')
        started = time.monotonic()
        provenance = self.local_python(PACKAGE_INFO)
        self.store.append_trace(run_id, sim_ts, 'tool_call', {'tool': 'score', 'scale_id': 'lsis-6',
            'responses': responses, 'package': provenance}, 'classify')
        path, transport_error = 'mcp_stdio', None
        try:
            async def invoke():
                return await asyncio.wait_for(self.remote(responses), timeout=self.settings.mcp_timeout_seconds)
            try:
                result = asyncio.run(invoke())
            except BaseExceptionGroup as group:
                leaves = []
                def collect(error):
                    if isinstance(error, BaseExceptionGroup):
                        for child in error.exceptions:
                            collect(child)
                    else:
                        leaves.append(error)
                collect(group)
                if not all(isinstance(e, (OSError, TimeoutError, anyio.EndOfStream, anyio.BrokenResourceError)) for e in leaves):
                    raise ValueError('MCP protocol or input error; fallback forbidden') from None
                raise ConnectionError('MCP transport failed') from None
        except (OSError, TimeoutError, anyio.EndOfStream, anyio.BrokenResourceError) as exc:
            if not self.settings.mcp_allow_fallback:
                raise ValueError('MCP transport failed; fallback disabled') from None
            transport_error = type(exc).__name__
            if self.local_python(PACKAGE_INFO) != provenance:
                raise ValueError('MCP package changed; fallback forbidden')
            result = validate_score(self.local_python(DIRECT_SCORE, responses))
            path = 'same_package_python_fallback'
        result = validate_score(result)
        if self.local_python(PACKAGE_INFO) != provenance:
            raise ValueError('MCP package changed during scoring')
        output = {'status': 'assessed', 'result': result, 'path': path, 'transport_error': transport_error,
                  'package': provenance, 'responses_hash': digest(responses)}
        self.store.append_trace(run_id, sim_ts, 'tool_result', {'tool': 'score', **output}, 'classify',
                                latency_ms=(time.monotonic()-started)*1000)
        return output
