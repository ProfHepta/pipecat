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

## 同日更新：真实引擎身份与跨机合成客户端

- 当前Pocket4实际引擎PID `485362`，`/proc`启动标识与收据一致；`hepta_voice.deploy.attest_pocket_engine`在线证实 commit、模型/二进制SHA、37层目标配置、Vulkan+FA、GPU render FD与本地认证HTTP端点一致。**远端密钥未返回qian-qi**。
- Pocket4 `pocket_fixture_client.py`已更新并通过目标SHA256对账；真实发送了`input_end_marker`，避免旧客户端造成八阶段时间戳缺失。
- 独立模拟LLM驱动的真正跨机合成PCM测试：Pocket4本地说话末尾到首帧 **2437.129ms**；qian-qi内部输入末尾到首帧 **2433.254ms**；63帧，输入和输出哈希核对、旧帧0。**这是两台设备各自本机时钟的两个计量值，不是跨主机时钟相减，也不是真实GPU首音**。
- 新的真实GPU验收入口：`python -m hepta_voice.ops.real_gpu_acceptance`。它本身不复制凭据、不建立转发、不拨电话；前置检查要求SSH Unix socket属于当前用户、转发目标固定、远端当前PID/引擎身份有效、Pipecat权威状态正确。前置条件不存在就保存失败收据且不启动任何Pipecat服务。本轮实测因`state/llama.key`缺失而按预期拒绝，保留`real_pocket4_gpu_verified=false`。
- 新增18项引擎身份单元测试、3项真实验收安全测试；与此前88项合计**109项测试通过**，模拟跨机验证另行真实运行。真实GPU首音与电话远端首音仍为空，NPU候选维持原不晋级结论。

## 验收脚本最新状态

- 在线只读实时验真通过：固定Pocket4 GPU进程PID/启动身份、权重和引擎摘要、Vulkan/FA/F16、GPU FD及本机认证健康接口符合约束。该操作不转移模型密钥。
- `ops/real_gpu_acceptance.py`要求预存的拥有者私有凭据、SSH AF_UNIX转发的SO_PEERCRED所有者与进程身份、固定Pocket4目标、模型认证/配置、Pipecat隔离与八阶段跨机收据均通过才可启动测试；失败时不启动模型/语音服务或碰电话。现场曾因缺少真实`llama.key`按预期拒绝，留下失败收据。
- 最新完全隔离的**模拟LLM**＋实际Pocket4↔qian-qi PCM复测：63帧，首音 **2427.259ms**（Pocket4自己的时钟），内部首PCM帧 **2422.580ms**（qian-qi自己的时钟），双向哈希一致，旧帧0，明确不计真实GPU。模型端仅为临时Unix socket伪服务。
- 本轮开发回归合计**109项通过**；引擎/跨机凭据接线仍缺授权执行放行，`production_ready=false`，无真正GPU首音或电话听感。
