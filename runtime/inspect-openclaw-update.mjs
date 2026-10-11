import { t as findActiveUpdateRun } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-reader-B17V1KuC.mjs';
import { _ as inspectUpdateRecoveries } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-ledger-bQeXWtPn.mjs';
const run=findActiveUpdateRun();
const rec=inspectUpdateRecoveries();
console.log(JSON.stringify({
  active: run ? {runId:run.runId,status:run.status,phase:run.phase,createdAtMs:run.createdAtMs,updatedAtMs:run.updatedAtMs,steps:(run.steps||[]).slice(-8).map(s=>({step:s.step,status:s.status}))} : null,
  recoveries:(rec||[]).map(x=>({runId:x.runId,status:x.status||null,kind:x.kind||null,stateKey:x.stateKey||null}))
},null,2));