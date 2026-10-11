import { s as listUpdateRuns } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-reader-B17V1KuC.mjs';
const runs=listUpdateRuns();
const rows=(runs||[]).map(r=>({
  runId:r.runId,status:r.status,phase:r.phase,reason:r.reason||null,
  acknowledged:(r.steps||[]).some(s=>s.step==='reconcile:acknowledged'),
  createdAtMs:r.createdAtMs,updatedAtMs:r.updatedAtMs
}));
console.log(JSON.stringify(rows,null,2));