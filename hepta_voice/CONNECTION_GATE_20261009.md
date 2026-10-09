# Pocket4 GPU → Pipecat：授权接线前的剩余门槛

## 现状（2026-10-09 再次核查）

- Pocket4 的固定 `hepta-pocket-llama.service` 仍运行，回环地址 `127.0.0.1:18455`。原模型 Qwen3-4B-Instruct-2507 Q4_K_M 的已验收引擎为 llama.cpp `d81235049384534c167caea52b85a694f6103d14`、Vulkan + FA、4K、F16 KV、单会话；历史收据包含 37/37 层卸载。
- qian-qi 侧 `hepta-pipecat.service`、`hepta-pipecat-tools.service` 均 inactive/disabled；`state/llama.key`、`state/llama.sock` 均未创建。正式跨机连接未完成。
- 跨机凭据复制工具调用仍被平台安全检查拒绝；不得通过自制代理、禁用认证、打印密钥、暴露 `0.0.0.0` 或换执行入口绕过拒绝。需要获准的执行环境完成连接配置。
- 没有本轮真实 GPU 完整语音首音或电话对端首音数据；生产/电话上线门禁保持关闭。

## 新增的可复现实测

在仅 `lo` 的网络隔离容器里，使用独立生成的临时 Unix socket 凭据和 **模拟模型 SSE**，配合真实 Pipecat 1.12.0、SenseVoice CPU、Melo FP32、8kHz PCM，得到 63 帧实际音频输出，回复“三加五等于八。”。

先后两轮从同机输入结束标记到收到首帧约 **2.311s / 2.226s**，均不包括真实 Pocket4 GPU 模型，也不包含真实电话。后一轮分段：最终转写约1197ms（其中识别计算276ms）、转写到 LLM 请求90ms、模拟模型首 token 116ms、回复校验10ms、首段合成806ms、合成结束到首帧5ms；纯合成样例不能充当 P95。两次差异属于实际测量波动，不得拿来推算替换真实模型后的速度。

`tests/test_uds_llama_client.py` 使用独立合成 key 测试 httpx2/OpenAI SDK 经认证 Unix socket 正确获得流式结果；不创建真实 `llama.key`、不连接 Pocket4。

`endpoint_attestation.py` 新增开机前的 key/socket 所有者、文件类型、权限、私有目录、长度检查。Unix socket 不存在、公开权限、密钥符号链接或普通文件假冒 socket 均必须拒绝，不能自动回退 Ollama 或公共网络。

`acceptance_evidence.py` 与跨机合成音频脚本要求真实首音收据、同一音频帧哈希、8 个主机阶段时间戳和 Pocket4 单调时钟首音数据，明确禁止两台机器单调时钟直接相减。收据缺失、阶段逆序、旧帧未清空、时间冲突不能晋级。

## 接线放行检查（尚未执行）

1. 由获准执行环境建立**私有且有认证**的 Pocket4 `127.0.0.1:18455` → qian-qi AF_UNIX 转发。先核对不涉及秘密输出的 PID、启动标识、引擎 SHA、权重 SHA、37/37 GPU 层及独占维护者。
2. 在 qian-qi 受限目录准备真实凭据与 Unix socket，均仅允许拥有者访问，并由应用启动时验证；不在源码、Git、日志、shell 历史或测试报告中暴露密钥。若执行环境禁止这步，保持阻塞，不更换未经授权的通道。
3. 在网络隔离下启动 Pipecat，实时检查 `/health`、`/props` 和上游进程证明一致，执行至少一次真实 GPU 文本对话，再执行 Pocket4 的固定合成 PCM 双向回路。
4. 核验同机阶段：输入结束标记、ASR、最终转写、LLM 开始、首 token、校验完成、首段合成、首 PCM 输出。Pocket4 客户端单独计时合成声学端点到本地收到首帧，不能把它称为真人实际听感。
5. 完成原请求去重、中断清空、晚到结果丢弃、断连与 GPU 服务恢复。每一项失败都不得宣称 `production_ready=true`。
6. 真实电话需另获对端同意，独占切换 PipeWire 与 ModemManager 电话音频，再测远端听感；不自动接听或拨号。

**本提交仅关闭接线前代码正确性与证据质量问题，不改变运行中的 Pocket4 推理服务，不把模拟模型测试算成 GPU 合格。**
