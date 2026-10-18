import {chromium} from '@playwright/test';
const browser=await chromium.launch();
const page=await browser.newPage();
const [base,client]=process.argv.slice(2);
await page.goto(`${base}/health`);
await page.evaluate(({base,client})=>new Promise((resolve,reject)=>{
  const pending=new Map();
  async function receive(alert){
    if(pending.has(alert.id))return;
    const task=fetch(`${base}/alerts/${alert.id}/receipt`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:client,browser_received_at:new Date().toISOString(),sim_ts:alert.sim_ts})}).then(response=>{if(!response.ok)throw new Error('receipt failed');}).catch(()=>pending.delete(alert.id));
    pending.set(alert.id,task);
  }
  const source=new EventSource(`${base}/alerts/stream`);
  source.onopen=()=>resolve(true);
  source.addEventListener('alert',event=>receive(JSON.parse(event.data)));
  setInterval(()=>fetch(`${base}/alerts?limit=1000`).then(r=>r.json()).then(rows=>rows.forEach(receive)).catch(()=>{}),1000);
  setTimeout(()=>reject(new Error('receiver startup timeout')),15000);
}),{base,client});
console.log('READY');
process.on('SIGTERM',async()=>{await browser.close();process.exit(0);});
