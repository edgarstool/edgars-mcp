# GitHub Actions Candidate Review

Review this repository and suggest useful GitHub Actions workflows.
**Do not create workflow files unless explicitly asked.**

## Focus

- CI（run on push / pull_request）
- tests
- lint
- typecheck
- build
- dependency checks
- docs drift
- scheduled repo patrol
- issue creation for detected problems

## For each proposed workflow include

```
- name:                  <workflow name>
  trigger:               push / pull_request / workflow_dispatch / schedule
  required permissions:  (least privilege list)
  read-only?:            yes / no
  can create issues?:    yes / no
  risk level:            low / medium / high
  needs user confirm?:   yes / no
  notes:                 (鉤環境變數、secrets 需求、外部 API 呼叫等)
```

## 規則

- 一律先 `workflow_dispatch`，跑通再上 `schedule`。
- 高風險動作（deploy、改 production、改權限）不建議 schedule，需手動觸發 + 二次確認。
- 不要建議 auto-merge。
- 不要建議 grant `write-all` permissions。
- 請使用繁體中文回覆。
