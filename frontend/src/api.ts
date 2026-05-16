import type { Result } from './types';
const base='';
export async function predict(payload:any):Promise<Result>{const r=await fetch(`${base}/api/predict`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok) throw new Error('predict failed'); return r.json();}
export async function predictFile(form:FormData):Promise<Result>{const r=await fetch(`${base}/api/predict/file`,{method:'POST',body:form}); if(!r.ok) throw new Error(await r.text()); return r.json();}
export async function updateData(){const r=await fetch(`${base}/api/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); if(!r.ok) throw new Error('update failed'); return r.json();}
