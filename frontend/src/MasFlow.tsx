import {Trace} from './api';

const roles=[
 {id:'supervisor',name:'Supervisor',tool:'업무 범위·분배',output:'지역·집단·기준 지정',href:'/workspace'},
 {id:'regional_analyst',name:'지역 분석가',tool:'고립 지수·등급 계산 도구',output:'1~5등급과 판정 근거',href:'/neighborhoods'},
 {id:'statistics',name:'통계 분석가',tool:'추이·출처·민감도 도구',output:'해석 검토·보완 요청',href:'/workspace'},
 {id:'match',name:'자원 매칭',tool:'자원 조건 필터·순위 계산 도구',output:'근거별 후보·부족 사유',href:'/policy'},
 {id:'approval',name:'Supervisor → 공무원',tool:'제안 묶기·승인 게이트',output:'승인·반려·보완 요청',href:'/console'},
];
export function MasFlow(){
 return <section className="mas-flow card" aria-label="멀티에이전트 시스템 구조"><h2>에이전트는 어떻게 함께 일하나요?</h2><p>Supervisor가 범위를 정해 위임하고, 각 분석 결과가 다음 역할의 근거가 됩니다. 계산과 조회는 도구가 수행합니다.</p><ol className="mas-nodes">{roles.map((r,i)=><li key={r.id}><span className="eyebrow">{i===0?'ORCHESTRATOR':i===4?'HUMAN REVIEW':i===3?'TOOL':'AGENT'}</span><a href={r.href}>{r.name}</a><p>{r.tool}</p><strong>{r.output}</strong>{i<4&&<span className="mas-arrow" aria-hidden="true">→</span>}</li>)}</ol><div className="mas-feedback"><p><strong>통계 분석가 ↔ 지역 분석가</strong> · 출처·결측 문제를 발견하면 추가 조회와 분석 보완을 요청합니다.</p><p><strong>자원 매칭 → 정책 조사 → Supervisor</strong> · 등록 자원이 부족하면 정부24에서 추가 후보를 조사합니다. 자격·정원은 별도 확인합니다.</p><p><strong>정책 조사 → 정책 설계 → 별도 검토</strong> · 기존 후보와 관계없이 동마다 대안 세 개를 작성합니다. 공식 사례와 지역 근거를 연결하고 자료가 부족하면 구상안으로 표시합니다. 수정·검토한 보고서는 PDF와 Word로 내려받습니다.</p><p><strong>공무원 → Supervisor</strong> · 보완 요청은 새 업무와 새 승인 대상으로 이어집니다.</p></div><p className="muted">구조 안내입니다. 실제 실행 상태와 전달 내용은 지역 업무에서 확인합니다. 업무 흐름과 지역 위험 1~5등급은 서로 다른 개념입니다.</p></section>;
}
const names:Record<string,string>=Object.fromEntries([...roles.map(r=>[r.id,r.name]),['policy','정책 조사'],['policy_design','정책 설계'],['classify','등급 계산']]);
const messageNames:Record<string,string>={workflow_candidates:'조건별 자원 후보 전달',regional_policy_candidates:'정책 조사 결과 전달',policy_design:'정책 초안·확인 과제 전달',reviewed:'근거 검토 완료',needs_human:'추가 확인 요청',lookup:'추가 근거 조회',revise:'분석 보완 요청',finish:'검토 결과 전달'};
export function AgentMessages({traces}:{traces:Trace[]}){
 const messages=traces.filter(t=>t.kind==='agent_message');
 return <section className="card" aria-label="실행별 에이전트 상호작용"><h3>이 업무에서 주고받은 근거</h3>{messages.length?<ol className="agent-messages">{messages.map(t=><li key={t.seq}><strong>{names[String(t.payload.sender)]||t.agent} → {names[String(t.payload.recipient)]||String(t.payload.recipient)}</strong><span>{String(t.payload.reason||t.payload.goal||messageNames[String(t.payload.result_kind||t.payload.action||t.payload.status)]||'분석 근거 전달')}</span><details><summary>전달 내용 확인 · {t.seq}</summary><pre>{JSON.stringify(t.payload,null,2)}</pre></details></li>)}</ol>:<p>아직 전달 기록이 없습니다.</p>}</section>;
}
