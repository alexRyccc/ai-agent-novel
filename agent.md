
<!-- SKILLFORGE:BEGIN -->

你是运行在本项目的 AI 助手。请遵循下面的技能路由规则：

1. 收到用户任务后，先对照下方「技能路由索引」，判断最匹配的一个技能。
2. 用你的文件读取能力，打开该技能对应的「定义文件路径」，完整阅读并严格遵循其中的规则、工作流与产出规范。
3. 如果没有任何技能匹配，就用你的通用能力直接完成任务，不要编造不存在的技能或文件。
4. 上面列出的路径是本机绝对路径，请直接读取，不要臆测或改写。

## 技能路由索引（由 SkillForge 自动生成，请勿手改本块）

| 技能 | 摘要 | 触发词 | 定义文件路径 |
| --- | --- | --- | --- |
| game-art-prompt-pack | game-art-prompt-pack 元数据待补全 | game-art-prompt-pack | C:\Users\吴丽莎\.workbuddy\skills\game-art-prompt-pack\SKILL.md |
| java-concurrency | 正确使用线程池、锁与并发容器，避免死锁与资源泄漏；适用：新增异步任务 | java、并发、线程池、多线程、锁 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-concurrency\SKILL.md |
| java-ddd-modeling | 从业务语言提炼聚合、实体与值对象；适用：新业务建模 | java、ddd、领域建模、架构、聚合 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-ddd-modeling\SKILL.md |
| java-exception-handling | 建立分层清晰的异常体系与统一出口；适用：异常处理混乱 | java、异常、错误处理、规范、全局异常 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-exception-handling\SKILL.md |
| java-gradle-build | 编写可维护、可缓存、版本集中的 Gradle 构建；适用：迁移或新建 Gradle 工程 | java、gradle、构建、依赖管理、构建缓存 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-gradle-build\SKILL.md |
| java-jpa-entity | 设计无 N+1、懒加载边界清晰的 JPA 实体模型；适用：新增实体与关联 | java、jpa、hibernate、orm、持久层 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-jpa-entity\SKILL.md |
| java-junit5-test | 编写快速、独立、断言明确、覆盖边界的单元测试；适用：为新逻辑补测试 | java、junit5、测试、单元测试、tdd | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-junit5-test\SKILL.md |
| java-jvm-tuning | 基于真实指标而非猜测做 JVM 参数调优；适用：服务 GC 频繁或停顿长 | java、jvm、gc、性能、调优 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-jvm-tuning\SKILL.md |
| java-logging-standard | 输出结构化、可检索、不含敏感信息的日志；适用：日志混乱难以排查 | java、日志、logback、可观测性、排查 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-logging-standard\SKILL.md |
| java-maven-build | 治理依赖冲突、加速构建、保持 POM 整洁；适用：依赖冲突排查 | java、maven、构建、依赖管理、pom | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-maven-build\SKILL.md |
| java-microservice-design | 以业务能力为边界拆分服务，避免分布式单体；适用：单体服务拆分 | java、微服务、架构、服务拆分、ddd | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-microservice-design\SKILL.md |
| java-mybatis-mapper | 编写可维护、防注入、索引友好的 MyBatis Mapper 与 SQL；适用：新增查询/更新语句 | java、mybatis、sql、持久层、数据库 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-mybatis-mapper\SKILL.md |
| java-spring-boot-api | 按团队规范构建分层清晰、异常统一、可测试的 Spring Boot REST 接口；适用：新增或改造 REST 接口 | java、spring-boot、rest、api、后端 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\java-spring-boot-api\SKILL.md |
| pixel-asset-forge | 生成游戏素材:像素角色、道具、图标、场景物件,一句话输入 → 输出原图、精灵图、 元数据待补全 | pixel-art、game-asset、sprite-sheet、animation、wechat-game | C:\Users\吴丽莎\.workbuddy\skills\pixel-asset-forge\SKILL.md |
| scan-code-smell | 定位可维护性缺陷并给出重构优先级；适用：重构前评估 | java、代码扫描、重构、坏味道、可维护性 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-code-smell\SKILL.md |
| scan-complexity | 降低条件嵌套与分支密度，提升可测试性；适用：复杂度门禁超限 | java、代码扫描、复杂度、可测试性、重构 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-complexity\SKILL.md |
| scan-license-compliance | 识别依赖与代码片段的许可证风险；适用：开源合规审查 | java、代码扫描、许可证、合规、开源 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-license-compliance\SKILL.md |
| scan-sast-security | 在编码阶段发现注入、越权、反序列化等安全问题；适用：上线前安全评审 | java、代码扫描、安全、sast、漏洞 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-sast-security\SKILL.md |
| scan-sca-dependency | 识别第三方依赖的已知漏洞与许可证风险；适用：供应链安全审查 | java、代码扫描、sca、依赖、供应链安全 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-sca-dependency\SKILL.md |
| scan-secret-detection | 在提交前发现硬编码密钥、Token、证书；适用：提交前检查 | java、代码扫描、安全、密钥、泄露 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-secret-detection\SKILL.md |
| scan-sonarqube-rules | 把 SonarQube 告警转成可执行的修复动作，而非盲目忽略；适用：质量门禁不通过 | java、代码扫描、sonarqube、静态分析、质量门禁 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-sonarqube-rules\SKILL.md |
| scan-static-analysis | 用工具链系统性发现代码缺陷而非抽样目测；适用：引入静态分析 | java、代码扫描、静态分析、spotbugs、checkstyle | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\scan-static-analysis\SKILL.md |
| ui-accessibility-wcag | 让界面可被键盘、读屏与低视力用户正确使用；适用：对外产品合规 | ui、无障碍、a11y、wcag、可访问性 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-accessibility-wcag\SKILL.md |
| ui-color-system | 建立语义化色板并保证所有组合对比达标；适用：建立品牌色板 | ui、色彩、对比度、设计系统、css | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-color-system\SKILL.md |
| ui-component-design | 每个组件覆盖 loading / empty / error / 边界状态；适用：新增组件 | ui、组件、设计系统、状态、前端 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-component-design\SKILL.md |
| ui-dark-mode | 做出对比达标、层次清晰的深色主题，而非简单反色；适用：新增深色主题 | ui、深色模式、主题、css、设计 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-dark-mode\SKILL.md |
| ui-design-tokens | 用语义化令牌统一颜色、间距、字号、圆角、阴影，支撑主题切换与一致性；适用：新建或重构样式体系 | ui、设计系统、design-tokens、css、前端 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-design-tokens\SKILL.md |
| ui-form-ux | 让表单填写顺畅、错误可定位、提交可恢复；适用：表单难填 | ui、表单、交互、校验、体验 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-form-ux\SKILL.md |
| ui-motion | 用克制的动效表达状态变化，不干扰任务；适用：界面生硬缺反馈 | ui、动效、过渡、css、交互 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-motion\SKILL.md |
| ui-responsive-layout | 用移动优先与流式布局适配多端，而非堆砌断点；适用：多端适配 | ui、响应式、布局、css、移动端 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-responsive-layout\SKILL.md |
| ui-typography | 建立字号、行高、字重、字距的层级体系；适用：文字层级混乱 | ui、排版、字体、css、设计 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-typography\SKILL.md |
| ui-web-performance | 优化 LCP、CLS、INP，让首屏快且稳定；适用：首屏慢 | ui、性能、web-vitals、lcp、前端 | C:\Users\吴丽莎\WorkBuddy\2026-10-29-19-35-22\demo-skills\ui-web-performance\SKILL.md |
| zxh-game-designer | 把游戏创意、参考作品、现有方案、配置或试玩证据转化为可进入制作的 GDD、玩法方 元数据待补全 | 游戏设计、Game Designer、GDD、core loop、economy | C:\Users\吴丽莎\.workbuddy\skills\zxh-game-designer\SKILL.md |

<!-- SKILLFORGE:END -->
