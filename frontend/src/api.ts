export class ApiError extends Error {
  constructor(public status:number,message:string){super(message);this.name='요청 오류';}
  get terminal(){return [400,401,403,404,410,422].includes(this.status);}
}
export async function request(path:string,body?:unknown):Promise<Response>{
  let response:Response;
  try{response=await fetch(path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  catch{throw new ApiError(0,'서버에 연결하지 못했습니다. 네트워크와 서버 주소를 확인하세요. 실행 요청은 자동으로 다시 보내지 않았습니다.');}
  if(response.ok)return response;
  const messages:Record<number,string>={401:'로그인 또는 배포 접근 인증이 필요합니다.',403:'접근이 거부되었습니다. 배포 접근 권한 또는 API 인증 설정을 확인하세요.',404:'요청한 자료 또는 실행을 찾을 수 없습니다. 실행 목록과 현재 데이터 모드를 확인하세요. 임시 저장 서버라면 재배포 후 이력이 없을 수 있습니다.',409:'다른 변경과 충돌했습니다. 최신 결과를 다시 조회한 뒤 검토하세요.',429:'요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.',503:'분석 자료 또는 서버 준비가 완료되지 않았습니다. 데이터 설정과 서버 상태를 확인하세요.'};
  let detail='';
  if(response.headers.get('content-type')?.includes('application/json')){
    try{const value=await response.json();if(typeof value.detail==='string')detail=value.detail.slice(0,400);}catch{/* The status remains useful even when an upstream body is invalid. */}
  }
  throw new ApiError(response.status,`${response.status}: ${messages[response.status]||'요청을 처리하지 못했습니다. 서버 상태를 확인하세요.'}${detail?' ('+detail+')':''}`);
}
export async function api<T>(path:string,body?:unknown):Promise<T>{
  const response=await request(path,body);
  const text=await response.text();
  if(response.headers.get('content-type')?.includes('text/html')||/^\s*<(?:!doctype|html|head|body)/i.test(text))throw new ApiError(502,'API 대신 웹페이지가 반환되었습니다. 배포의 API 경로와 접근 인증을 확인하세요.');
  try{return JSON.parse(text) as T;}catch{throw new ApiError(502,'서버 응답을 읽지 못했습니다. 잠시 후 다시 조회하세요.');}
}
export type Run = {id: string; scenario_id: string; status: string; error?:string|null; data_mode: string; llm_mode: string; model_version: string; started_at: string};
export type Trace = {run_id: string; seq: number; agent: string; kind: string; sim_ts: string; wall_ts: string; latency_ms: number; tokens_in: number; tokens_out: number; payload: Record<string, unknown>};
export const statusText: Record<string, string> = {cancelled:'취소', pending:'대기', running: '실행 중', awaiting_approval: '승인 대기', completed: '완료', rejected: '반려', failed: '실패'};
export const scenarios = [
  {id: 'case-pending', type: 'case', sim_time: '2025-07-01T09:00:00+09:00', payload: {text: '합성 사례: 외로워서 상담을 요청합니다.'}},
  {id: 'crisis-direct', type: 'crisis', sim_time: '2025-07-01T09:00:00+09:00', payload: {text: '합성 위기: 죽고 싶어요.'}},
  ...['07','08','09','10','11','12'].map(month => ({id: `monthly-${month}`, type: 'monthly', sim_time: `2025-${month}-01T09:00:00+09:00`, payload: {ym: `2025-${month}`, analysis_version:'legacy-v1'}})),
  {id:'monthly-groups-v3',type:'monthly',sim_time:'2025-09-01T09:00:00+09:00',payload:{ym:'2025-09',week:'2025-09-08'}},
  {id:'admin-synthetic',type:'admin',sim_time:'2025-07-01T09:00:00+09:00',payload:{person:{person_id:'synthetic-01',age:45,sgg:'11230',admin_flags:{became_alone:true}}}},
  {id:'case-handoff-synthetic',type:'case',sim_time:'2025-07-01T09:00:00+09:00',payload:{person:{person_id:'synthetic-02',age:24,sgg:'11230',consent:true,responses_confirmed:true,responses:{'synthetic-contract-fixture':{case:201}}}}},
  {id: 'question-history', type: 'question', sim_time: '2025-12-01T09:00:00+09:00', payload: {text: '이력을 보여 주세요.'}},
  {id:'monthly-resource-research',type:'monthly',sim_time:'2025-09-30T12:00:00+09:00',payload:{ym:'2025-09',collaboration:true,research_gaps:true}},
  {id:'monthly-evidence-loop',type:'monthly',sim_time:'2025-09-30T12:00:00+09:00',payload:{ym:'2025-09',collaboration:true,verify_sources:true}},
  {id:'monthly-collaboration',type:'monthly',sim_time:'2025-09-30T12:00:00+09:00',payload:{ym:'2025-09',collaboration:true}},
];
