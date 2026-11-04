---
name: java-spring-boot-api
display_name: Spring Boot REST API 开发
description: 按团队规范构建分层清晰、异常统一、可测试的 Spring Boot REST 接口
summary: 按团队规范构建分层清晰、异常统一、可测试的 Spring Boot REST 接口；适用：新增或改造 REST 接口
tags: java, spring-boot, rest, api, 后端, 接口, 参数校验, 统一响应, controller
version: 1.0.0
author: skillforge
license: MIT
---

# Spring Boot REST API 开发

## 目标

产出符合分层架构、统一响应体、统一异常处理、可被集成测试覆盖的 REST 接口。

## 适用场景

- 新增或改造 REST 接口
- 接口返回结构不统一需要收敛
- 接口缺少参数校验或异常处理

## 工作流

1. 确认资源边界与路径命名（复数名词 + 层级，如 `/api/v1/orders/{id}/items`）。
2. 定义 DTO：请求体与响应体分离，禁止直接用 Entity 作为接口出入参。
3. Controller 只做参数绑定与结果封装，业务逻辑下沉到 Service。
4. 使用 `@Valid` + JSR-380 注解做入参校验，错误统一由 `@RestControllerAdvice` 捕获。
5. 响应统一包装为 `{code, message, data, traceId}`，HTTP 状态码语义正确。
6. 补充集成测试：正常路径 + 参数非法 + 资源不存在，三类都要有。

## 检查清单

- [ ] 路径是否符合 REST 语义，动作用 HTTP 方法表达而非路径动词
- [ ] 是否存在 Entity 直接暴露到接口层
- [ ] 分页参数是否有上限保护（避免 `size=999999`）
- [ ] 敏感字段是否在响应 DTO 中被排除
- [ ] 异常是否都被统一处理器接管，没有裸 `e.printStackTrace()`

## 产出要求

交付：Controller / Service / DTO 三层代码 + 至少 3 个集成测试用例 + 接口文档片段。
