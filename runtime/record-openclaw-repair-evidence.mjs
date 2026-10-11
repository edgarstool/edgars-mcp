import { s as listUpdateRuns } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-reader-B17V1KuC.mjs';
import { d as recordUpdateRunDiagnostic } from 'file:///G:/AI_WORK_512/runtimes/openclaw-2026.9.6/node_modules/openclaw/dist/update-run-ledger-bQeXWtPn.mjs';
const run=(listUpdateRuns()||[]).find(r=>r.status==='failed'&&r.reason==='finalize:doctor');
if(!run) throw new Error('No finalize:doctor failed run found');
const detail='Post-repair live verification: Gateway restored on 0.0.0.0:19999; local gateway probe ok/rpcOk on 2026.9.6 build 2026.9.6-release-eb377ac59e6c-2026-09-23T16-33-12.144Z; public https://openclaw.edgars.tools returned HTTP 200; openclaw mcp doctor exited 0 with 1password and youtrack ok. Full update finalization remains blocked by Windows Scheduled Task ACL (schtasks disable/change Access is denied) from the current medium-integrity shell.';
recordUpdateRunDiagnostic(run.runId,detail,{},'reconcile:post-repair-live-verification');
console.log(JSON.stringify({runId:run.runId,recorded:true},null,2));