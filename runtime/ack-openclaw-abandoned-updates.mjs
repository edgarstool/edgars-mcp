import { s as listUpdateRuns } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-reader-B17V1KuC.mjs';
import { t as acknowledgeAbandonedUpdateRun } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-ledger-bQeXWtPn.mjs';
const runs=listUpdateRuns()||[];
const targets=runs.filter(r=>r.status==='failed'&&r.reason==='abandoned'&&!(r.steps||[]).some(s=>s.step==='reconcile:acknowledged'));
const results=targets.map(r=>({runId:r.runId,acknowledged:acknowledgeAbandonedUpdateRun(r.runId)}));
console.log(JSON.stringify({count:results.length,results},null,2));