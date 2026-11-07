# 多语言 ASR 测评平台实施计划

> 此文保留首版实施计划。当前模块路径、启动方式与开发检查请参阅 [README](../README.md)。

用户已授权规格完成后继续 Python 开发，本轮在独立 asr_eval 目录实现，sources 为只读。

目标为实现 SPEC.md 中首版测评与 Case 闭环。技术采用 Flask、SQLite、FFmpeg 和原生前端。

1. 先写回归测试，覆盖账号隔离、盲测、错误音频、补传、重测、标注与审计冲突。
2. app.py 实现认证、数据库、音频处理、任务执行、REST 接口和命令行账号管理；providers.py 实现两个适配器及参数快照。
3. templates/index.html、static/app.js、static/style.css 实现四页工作台、录音、历史、详情、标注与研发复核。
4. 运行 pytest、真实 HTTP 冒烟与浏览器页面核查，修复问题。README.md 提供 Windows/Linux 启动及部署边界。
5. 将源码、规格、配置和测试打包交付，排除运行数据、密码、密钥和缓存。

检查重点为并发写入、跨账号读写、第三方接口失败、非音频文件、链接时间与实际片段一致性。首版不使用外部 JavaScript CDN，避免内网依赖。
