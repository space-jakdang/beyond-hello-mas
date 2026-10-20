import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import {Observatory} from './Observatory';
import {Console} from './Console';
import {Evaluation} from './Evaluation';
import {GroupDashboard} from './GroupDashboard';
import {Neighborhoods} from './Neighborhoods';
import {Home, destinations} from './Home';
import {Policy} from './Policy';
import {Workflow} from './Workflow';

const pages: Record<string, string> = {'/': '프로젝트 안내', ...Object.fromEntries(destinations.map(p=>[p.href,p.title])), '/neighborhoods/legacy':'과거 6연령 분석'};
function App() {
  const [health, setHealth] = useState('서버 연결 중');
  useEffect(() => {
    fetch('/health').then(async response => {
      if (!response.ok) throw new Error('Health request failed');
      const data = await response.json();
      setHealth(`서버 연결됨 · 데이터 ${data.data_mode} · LLM ${data.llm_mode}`);
    }).catch(() => setHealth('서버 연결 실패'));
  }, []);
  const path = location.pathname;
  return <div className="app-shell"><a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
    <header className="site-header"><div className="header-inner"><a className="brand" href="/" aria-label="Beyond Hello MAS 인덱스"><span className="brand-mark" aria-hidden="true">B</span><span>Beyond Hello<small>지역 고립 대응 · 개발 대시보드</small></span></a>
      <nav aria-label="주 메뉴"><a href="/" aria-current={path==='/'?'page':undefined}>인덱스</a>{destinations.map(p=><a key={p.href} href={p.href} aria-current={path===p.href?'page':undefined}>{p.title}</a>)}</nav>
    </div></header>
    <main id="main-content" tabIndex={-1}><div className="page-heading"><div><p className="eyebrow">BEYOND HELLO / WORKSPACE</p><h1>{pages[path] ?? '페이지를 찾을 수 없습니다'}</h1></div><p className="connection-status" role="status">{health}</p></div>
      {path==='/' && <Home/>}{path==='/workspace' && <Workflow/>}{path==='/observatory' && <Observatory/>}{path==='/policy' && <Policy/>}{path==='/neighborhoods' && <GroupDashboard/>}{path==='/neighborhoods/legacy' && <Neighborhoods/>}{path==='/console' && <Console/>}{path==='/evaluation' && <Evaluation/>}
      {!pages[path] && <p>주소를 확인하거나 <a href="/">인덱스로 돌아가세요.</a></p>}
    </main><footer className="site-footer"><div><strong>Beyond Hello MAS</strong><p>지역의 근거를 검토하고, 사람의 판단으로 대응합니다.</p></div><p>연구·개발용 대시보드 · 자동 자격 판정 및 실제 자원 배정 아님<br/><a href="/">프로젝트 안내로 돌아가기</a></p></footer>
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
