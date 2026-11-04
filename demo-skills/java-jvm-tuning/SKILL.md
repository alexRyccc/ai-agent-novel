---
name: java-jvm-tuning
display_name: JVM 调优与 GC 分析
description: 基于真实指标而非猜测做 JVM 参数调优
summary: 基于真实指标而非猜测做 JVM 参数调优；适用：服务 GC 频繁或停顿长
tags: java, jvm, gc, 性能, 调优, 内存溢出, oom, 停顿
version: 1.0.0
author: skillforge
license: MIT
---

# JVM 调优与 GC 分析

## 目标

给出有数据支撑的 JVM 参数建议，并说明每个参数的依据。

## 适用场景

- 服务 GC 频繁或停顿长
- 内存占用异常
- 上线前容量评估

## 工作流

1. 先采集基线：`jstat -gc`、GC 日志、堆直方图（`jmap -histo`）。
2. 判断瓶颈类型：吞吐（Parallel）/ 低延迟（G1、ZGC）/ 小堆（Serial）。
3. 堆大小按存活对象集估算，`-Xmx` 与 `-Xms` 设为相等避免动态扩容。
4. 开启 GC 日志：`-Xlog:gc*:file=gc.log:time,uptime:filecount=5,filesize=50m`。
5. 每次只改一组参数，压测对比后再进入下一轮。

## 检查清单

- [ ] 是否基于采集数据而非经验值给参数
- [ ] 元空间是否设置了上限 `-XX:MaxMetaspaceSize`
- [ ] 是否开启 OOM 时自动 dump：`-XX:+HeapDumpOnOutOfMemoryError`
- [ ] 容器环境是否考虑了 cgroup 内存限制（`-XX:MaxRAMPercentage`）

## 产出要求

交付：基线数据表 + 参数变更清单（含依据）+ 压测对比结果。
