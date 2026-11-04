---
name: java-concurrency
display_name: Java 并发编程
description: 正确使用线程池、锁与并发容器，避免死锁与资源泄漏
summary: 正确使用线程池、锁与并发容器，避免死锁与资源泄漏；适用：新增异步任务
tags: java, 并发, 线程池, 多线程, 锁, 线程安全, 死锁, 异步
version: 1.0.0
author: skillforge
license: MIT
---

# Java 并发编程

## 目标

产出线程池配置合理、锁粒度恰当、无可见性缺陷的并发代码。

## 适用场景

- 新增异步任务
- 线程池参数配置
- 并发安全问题排查

## 工作流

1. 线程池一律显式构造，禁止 `Executors.newFixedThreadPool`（无界队列风险）。
2. 核心参数按任务类型定：CPU 密集 ≈ 核数 + 1，IO 密集 ≈ 核数 × (1 + 等待比)。
3. 使用有界队列 + 明确的拒绝策略（`CallerRunsPolicy` 或自定义降级）。
4. 共享可变状态用 `volatile` / `Atomic*` / 锁，明确可见性与原子性需求。
5. 加锁顺序全局统一，避免嵌套锁；优先用 `tryLock` 带超时。
6. 线程池必须在应用关闭时 `shutdown` + `awaitTermination`。

## 检查清单

- [ ] 是否有无界队列导致 OOM 的风险
- [ ] 线程池是否命名（便于排查：自定义 ThreadFactory）
- [ ] 是否存在在锁内做 IO 或远程调用
- [ ] `SimpleDateFormat` 等非线程安全类是否被共享
- [ ] 异常是否被吞掉（`submit` 的异常需 `Future.get` 才能抛出）

## 产出要求

交付：并发代码 + 线程池配置说明 + 并发正确性的测试或压测证据。
