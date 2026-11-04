---
name: java-jpa-entity
display_name: JPA / Hibernate 实体与关联映射
description: 设计无 N+1、懒加载边界清晰的 JPA 实体模型
summary: 设计无 N+1、懒加载边界清晰的 JPA 实体模型；适用：新增实体与关联
tags: java, jpa, hibernate, orm, 持久层, N+1, 懒加载
version: 1.0.0
author: skillforge
license: MIT
---

# JPA / Hibernate 实体与关联映射

## 目标

产出关联关系正确、避免 N+1、事务边界清晰的实体与 Repository。

## 适用场景

- 新增实体与关联
- 接口响应慢怀疑 N+1
- 懒加载异常排查

## 工作流

1. 明确聚合根，只在聚合内部建立双向关联，跨聚合用 ID 引用。
2. `@OneToMany` 默认 `LAZY`，需要时用 `@EntityGraph` 或 `join fetch` 显式预取。
3. 禁止在 `toString()` / `equals()` 中触发懒加载。
4. 分页查询避免 `join fetch` 集合（会导致内存分页），改用批量预取。
5. 写操作放在 `@Transactional` 内，读操作标注 `readOnly = true`。

## 检查清单

- [ ] 是否有 `EAGER` 的集合关联
- [ ] 查询是否存在 N+1（开启 SQL 日志核对条数）
- [ ] 实体是否被直接序列化返回
- [ ] 是否存在跨事务的懒加载访问

## 产出要求

交付：实体定义 + Repository + N+1 验证日志（SQL 条数前后对比）。
