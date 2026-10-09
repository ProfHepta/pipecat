# Pocket4 单机语音部署验收 — 2026-10-09

## 服务与安全边界

所有语音运行服务已经部署在 alex-G1628-04 (Pocket4)：
- hepta-pocket-llama.service：固定 llama.cpp d81235049384534c167caea52b85a694f6103d14，Qwen3-4B-Instruct-2507 Q4_K_M、Vulkan、Flash Attention ON、F16 KV、4K、单会话，37/37 GPU层，监听本机127.0.0.1:18455。
- hepta-pocket-voice-proxy.service：仅本机的私有Unix socket。透明转发到同一主机的llama.cpp回环地址，GPU引擎已有Key仅在Pocket4原位读取，不复制跨机器、不写入Git。
- hepta-pocket-voice-tools.service：Python3.14标准库只读诊断，只允许固定 call-audio-watch.py --inspect；写工具、拨号、短信、交易、任意shell被拒绝。
- hepta-pocket-voice-agent.service：rootless Podman内Pipecat1.12.0、SenseVoice CPU、Melo FP32 CPU、原持久账本和语音输出权限Guard。镜像固定sha256:b725f5836d23e1388052104754effb598f05229da6df51181b5cdce06b5a4a2f。

四个systemd用户服务都已 enabled/active，alex Linger=yes。容器network=none、只读根、无GPU/音频设备、cap-drop ALL、no-new-privileges，4CPU／5GiB／192 PID。不使用Ollama做语音LLM；Pocket4为OpenClaw保留的其他Ollama服务不属于本次迁移，不得删除。语音入口令牌在Pocket4单独生成，qian-qi旧入口令牌没有转移。

Pocket4路径：
- /home/alex/hepta-pipecat-voice/hepta_voice/ — 源码
- /home/alex/.local/share/hepta-pipecat/ — 语音模型、venv、状态、账本和证据
- /home/alex/.local/share/hepta-inference/ — 既有GPU引擎与GGUF
- /home/alex/.local/state/hepta-voice-pocket-migration/ — 迁移审计记录

## 实测（真实Pocket4 GPU，不是模拟SSE）

8kHz合成输入经过同一Pocket4上的SenseVoice→Pipecat VAD/回合→Vulkan llama.cpp→Guard→Melo→PCM。转写「请用一句话回答三加五等于几」，回复「三加五等于八。」，63帧输出。
- 首次写入完整收据的真实首PCM为2029.766ms。更早的一次返回2.614秒，但独立验收容器证据目录只读导致测试退出1，未计PASS；只调整测试容器的证据目录写权限，不改常驻容器只读边界。
- 5轮后续同模型短句首音：1993.264、1928.829、1961.954、1960.442、2010.633ms；中位1961.954ms。这5轮不构成P95。
- 完整控制回归PASS：固定模型认证、无公网访问、401错误凭据、409单会话排他、真实只读工具收据、超时结果未知、打断旧音频帧清空、同ID请求去重、8kHz音频识别与合成。
- 强杀仅属于本任务的 hepta-pocket-voice-lab 容器，用户systemd按有界8秒重启策略自动恢复（NRestarts=1）；固定GPU模型PID、启动身份未变化。重启后真实合成首音2021.646ms，正确63帧。
- 原qian-qi SQLite账本经快照迁移且SHA256一致，原始43 done、3 failed、7 interrupted、4 unknown 请求及一条原本地备注均保留；后续新请求只在Pocket4发生。当前ledger quick_check=ok。
- 源码124项单元回归PASS，保留1项历史Pipecat弃用警告；之前的NPU Whisper未晋级，没有替换识别。
- 交易执行、Gateway、Pocket4原电话音频服务在实验后仍active，没有对其unit/驱动/固件/USB音频独占进行修改。

## 限制与下一资格

这是自带真实Pocket4 GPU的合成PCM端到端实验服务，仍不能当作真人蜂窝电话代理上线。production_ready=False、phone_authority=False，没有拨号、接听、自动接听或真人对端听感验收。各阶段已记录到本地证据，但Silero/Smart Turn的TTFS P99警告仍未以专用耐久实测关闭。

qian-qi专属旧语音目录、模型副本、独立工作树、下载构建产物及旧用户服务单元仅在上述迁移及Git推送检查成功后执行白名单清理。Desktop Commander、全球Docker镜像、其他H3/Android/交易项目不属于清理范围。
