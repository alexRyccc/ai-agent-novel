---
name: java-mybatis-mapper
display_name: MyBatis Mapper 与 SQL 编写
description: 编写可维护、防注入、索引友好的 MyBatis Mapper 与 SQL
summary: 编写可维护、防注入、索引友好的 MyBatis Mapper 与 SQL；适用：新增查询/更新语句
tags: java, mybatis, sql, 持久层, 数据库, 慢查询, 动态 SQL, mapper, 索引
version: 1.0.0
author: skillforge
license: MIT
---

# MyBatis Mapper 与 SQL 编写

## 目标

产出参数绑定安全、SQL 可读、能走索引的 Mapper 接口与 XML。

## 适用场景

- 新增查询/更新语句
- 慢 SQL 排查
- 动态条件拼接

## 工作流

1. 一律使用 `#{}` 占位符，禁止 `${}` 拼接用户输入（SQL 注入）。
2. 动态条件用 `<if>` / `<where>` / `<trim>`，避免手写 `WHERE 1=1`。
3. 复杂查询先写 EXPLAIN，确认命中索引再落地。
4. 批量操作用 `foreach` + 合理的 `batchSize`，避免超长 SQL。
5. 结果映射显式写 `resultMap`，不依赖下划线自动转换的隐式约定。

## 检查清单

- [ ] 是否存在字符串拼接 SQL
- [ ] `LIKE` 查询是否处理了 `%` 前缀导致的索引失效
- [ ] 是否有 `SELECT *`（应显式列名）
- [ ] 批量插入是否有事务与分批
- [ ] 更新语句是否都带 `WHERE`（防全表更新）

## 产出要求

交付：Mapper 接口 + XML + EXPLAIN 结果 + 关键 SQL 的索引说明。
