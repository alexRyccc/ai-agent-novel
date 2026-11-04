---
# 本行是注释：回写时必须原样保留（ARCH §2.2.5）
name: 内部下单接口规范
description: 规范内部下单接口的字段命名、错误码与幂等要求
summary: 下单接口的内部规范（字段/错误码/幂等）
version: 2
author: platform-team
enabled: true
triggers:
  - 下单
  - 订单
  - order
tags: [内部规范, 后端, 接口]
extra:
  owner: platform
  severity: high
notes: |
  这里是有意的块标量，属于"合法但超出子集"
  必须降级为 raw 并继续入库，绝不抛异常
---

# 内部下单接口规范

## 字段命名

- 金额字段一律 `amount_cents`（整数分），禁止用浮点。
- 时间字段一律 RFC3339 UTC 字符串。

## 幂等

写接口必须支持 `Idempotency-Key` 请求头，重复请求返回首次结果。
