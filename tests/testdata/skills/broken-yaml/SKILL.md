---
name: 故意写坏的 skill
这一行没有冒号，结构不可恢复
description: 用于验证 FR-02 的跳过行为
---

# 正文

这个文件应当被 scanner 跳过并报出行号，但**不能**影响其它 skill 的扫描。
