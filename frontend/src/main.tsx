import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import {Observatory} from './Observatory';
import {Console} from './Console';

const pages: Record<string, string> = {'/': '관찰', '/observatory': '관찰', '/console': '담당자 콘솔', '/evaluation': '평가'};
function App() {
  const [health, setHealth] = useState('서버 연결 중');
  useEffect(() => {
    fetch('/health').then(async response => {
      if (!response.ok) throw new Error('Health request failed');
      const data = await response.json();
      setHealth(`서버 연결됨 · 데이터 ${data.data_mode} · LLM ${data.llm_mode}`);
    }).catch(() => setHealth('서버 연결 실패'));
  }, []);
  return <><header><strong>Beyond Hello MAS</strong><nav aria-label="주 메뉴">
    <a href="/observatory">관찰</a><a href="/console">담당자 콘솔</a><a href="/evaluation">평가</a>
  </nav></header><main><h1>{pages[location.pathname] ?? '페이지를 찾을 수 없습니다'}</h1>
    <p role="status">{health}</p>{["/", "/observatory"].includes(location.pathname) && <Observatory/>}{location.pathname === "/console" && <Console/>}
  </main></>;
}
createRoot(document.getElementById('root')!).render(<App/>);
