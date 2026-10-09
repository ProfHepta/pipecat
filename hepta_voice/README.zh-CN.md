## 2026-10-09 最新验收门槛（已核验，尚未正式接管）

Pocket4固定Vulkan/FA GPU引擎的真实PID/启动身份/GPU FD/摘要与本机健康接口再次验证通过，qian-qi真实`llama.key`与`llama.sock`仍缺，平台此前禁止跨机凭据/转发配置，本轮没有绕行。同步Pocket4最新版合成PCM客户端并实际验收远端首帧2427ms（模拟LLM而非真实GPU），63帧、哈希一致、旧帧0。新增严格只读引擎身份验证和`ops/real_gpu_acceptance.py`，要求正式私有SSH Unix连接具备条件后才允许真实GPU验收；缺key时已按预期拒绝且没有启动Pipecat。当前109项单元测试通过，生产/电话资格未变。

---

## 2026-10-09 最新：GPU进程身份复核＋跨机合成音频验收

**仍未完成正式GPU→Pipecat接线。** Pocket4上的固定Vulkan/FA引擎已通过在线进程启动身份、进程参数、GPU FD、本地认证健康接口与引擎/模型摘要核对；这一检查不复制或显示引擎凭据。qian-qi缺`state/llama.key`与`state/llama.sock`，因既有平台安全检查拒绝凭据/转发配置，没有变换方式绕过。

已找到并修正Pocket4上的旧版合成测试客户端：当前源端与已验收仓库脚本SHA256一致，输入结束标记能够真实发出。使用**独立模拟LLM**（不是GPU）实测Pocket4合成音频→qian-qi真实SenseVoice/Pipecat/Melo→Pocket4返回音频，Pocket4同机首音为**2.437秒**、qian-qi本机对应阶段为**2.433秒**、63帧、双向SHA一致、旧帧0；两台单调时钟不交叉相减。报告见`benchmarks/mock-cross-host-20261009.json`。

新增`deploy/attest_pocket_engine.py`与`ops/real_gpu_acceptance.py`：在正式凭据和受限SSH Unix socket已获准部署后，才验证真实GPU进程身份和固定配置、实际Pipecat合成语音、取消去重与工具故障回归。运行前门槛未满足会停止且不启动Pipecat。本轮现场运行确实在缺少真实key时**拒绝**，没有产生假GPU首音。当前**109项单元测试通过**，无电话接管或自动接听。

---

## 2026-10-09：接线前安全与合成整链路验收

新增加密凭据/Unix socket 文件类型与权限的拒绝检查、认证Unix socket流式客户端测试、跨主机双时钟首音收据校验。合计 **88项单元测试通过**。网络隔离中以真正 SenseVoice + Pipecat + Melo 和**模拟LLM**完成63帧音频输出；最后一轮输入结束到第一帧为 **2.226秒**（前一轮2.311秒），只能证明不依赖真实GPU的语音链路和埋点。对应源码与不含秘密的收据见 `ops/mock_uds_audio_acceptance.py`、`benchmarks/mock-uds-audio-20261009.json`、`CONNECTION_GATE_20261009.md`。

正式 Pocket4 GPU 引擎仍在其本机运行，但跨机凭据和SSH Unix socket 接线因平台安全检查未获执行放行，**不能以模拟LLM结果代替真实GPU首音**。未执行真实电话测试，Pipecat仍处于停止、未自启状态。

---

## 本轮新增记录：GPU接线仍阻塞，NPU候选实测不晋级

详见 `NPU_TIMING_20261009.md`。新增首音分段埋点和69项单元测试；没有新的完整GPU首音成绩。Pocket4真实通过XRT GEMM和FastFlowLM栈验证，并完成Whisper NPU转写实验，但短句响应和质量未达到替换门槛。没有替换SenseVoice，也没有开启电话接管。

# 当前分支：Pocket4 llama.cpp GPU 迁移草稿

本分支固定同一 Qwen3 4B Q4_K_M，完成了 Pocket4 上 llama.cpp v0.6.0 / b11429 的 Vulkan/HIP × FA开关四组实测。首选 **Vulkan + FA on + F16 KV + 4K + 单会话**。结果见 `benchmarks/pocket4-20261009.json` 与 `GPU_AB_20261009.md`。

Pipecat 的模型适配和启动检查已改为本地 llama.cpp 兼容接口；ASR/TTS继续在 qian-qi 的CPU运行，qian-qi GPU保持不启用。无Ollama回退。**跨机端点部署与凭据转移调用被安全检查拦截，没有重试；服务保持停止，不应把源码修改当成接管成功。** 缺少端点文件时启动会明确拒绝。

64项单元测试通过，但没有新的完整首音/电话对端首音数据。GPU基准与语音验收必须分开。接口要求的 `state/llama.key`、`state/llama.sock` 尚未部署；不要执行下方历史版本的启动流程来推断当前分支可用。

---
## 以下为迁移前的历史说明

# Hepta Local Voice — Pipecat 适配层

本目录建立在 Pipecat **v1.12.0 / 1559a684b1ee9771b36454b72418d7364b518e7f** 上。运行依赖固定到 `requirements.lock`；当前使用发行版 wheel 提供完整 Python 包和内置 Silero/Smart Turn 模型，而不是从不完整的稀疏检出中直接导入。

## 范围

使用上游 `Pipeline`、`PipelineWorker`、`WorkerRunner`、`LLMContextAggregatorPair`、Silero VAD、Local Smart Turn、原生 `OLLamaLLMService`、函数调用与 `BaseInputTransport` / `BaseOutputTransport`。本目录只提供本地模型、PCM端点、输出权限和持久请求收据适配。

`SenseVoiceSTTService` 继承原生分段 STT 服务，`MeloTTSService` 继承原生 TTS 服务。不使用云端识别、合成或推理。对话回复先经权限检查，再进入 TTS；不能把该模式称为逐 token 到声音的无缓冲管线。

只暴露 `telephone_status` 固定只读工具，实际执行既有 Pocket4 电话诊断。不允许模型指定命令、主机、电话号码，不接听、不拨号、不发短信、不进行交易、预约或支付。未知参数会拒绝，不能通过丢弃参数或补造收据绕过。

**这是实验适配，不是获得生产放行的电话助理。** `production_ready=false`、`phone_authority=false`、`microphone_open=false`。所有音频验证输入均为合成样例，没有替换现有人工通话音频路由。现有 ModemManager / PipeWire 电话守护及其设备校验保持原样。

## 目录和运行边界

默认数据目录为 `~/.local/share/hepta-pipecat`，可用 `HEPTA_VOICE_DATA` 显式指定。源码与数据分离，数据目录**绝不能提交 Git**：

- `models/`：原有 Qwen3 4B Instruct、SenseVoice、Melo 全精度模型及许可证。
- `state/`：权限0700；原请求账本、鉴权凭证、Unix sockets。迁移保留旧 `voice-r2` 请求摘要格式；崩溃中的未知结果不能清账重放。
- `fixtures/`：已验证的合成音频输入。
- `runtime/` 和 `venv/`：私有 CPU Ollama 运行库与固定依赖环境。
- `evidence/`：本机验收收据，与源码分离。

`ops/run-cpu.sh` 使用固定镜像、本地权重，容器 `network=none`、只读根、无 GPU、无音频设备，限制4CPU/6GiB。模型内部只访问自身 loopback；宿主侧工具代理只执行固定 SSH 只读诊断。原默认 Ollama 与 H3 不受管理。

**语音 GPU 保持停用。** 当前 CPU 路径用于迁移正确性验收，不承诺满足实时电话响应目标；GPU 不能因迁移自动重新启用。

## 启动与验证

这些命令针对已经迁移资产的本机环境，不是包含权重的一键安装包。初次安装需要事先准备清单中已固定的模型和 CPU 运行库。不要重新下载/创建账本冒充已保留的原始请求状态。

```bash
python -m pip install -r hepta_voice/requirements.lock
python -m pytest hepta_voice/tests
python hepta_voice/ops/install_units.py
systemctl --user start hepta-pipecat-tools.service
systemctl --user start hepta-pipecat.service
python hepta_voice/ops/acceptance.py
systemctl --user stop hepta-pipecat.service
```

安装脚本不会启用模型开机自启。服务鉴权凭证保存在本机 `state/access.token`，不得把它打印到日志或分发给 Pocket4。启动前保留单一所有者锁；锁不是电话音频交接的完成证明。

`ops/cross_host.py` 通过已有严格主机密钥验证的 SSH，将 Pocket4 合成输入送入 Pipecat，再把输出帧送回；对比实际两端的哈希。它不是实际电话或真人听感验收。

`ops/tool_failure.py` 只对新建只读工具代理做有界失联测试，并在 finally 中恢复；不会停止 ModemManager、交易或电话守护。

## 迁移验收与剩余边界

本地收据区分上游组件运行、模型质量、传输延迟、真实电话和真人听感。没有任何自动评分替代真人电话验收。仍需关闭的项包括：CPU/所选计算节点的实际延迟、电话人工/AI媒体独占交接、真实入呼/外呼对端验证及被授权的业务写操作。不能通过关闭日志或弱化断言伪造这些结果。

旧 10000 尝试的防重记录保留在原 Pocket4 状态目录。本迁移不重置该记录，也不重新拨号。

## 2026-10-09 本机迁移收据摘要

本机60项控制/适配测试通过。实际运行了原生 Pipecat 文本对话、纠正、8k音频经 Silero/Smart Turn → SenseVoice → Ollama → Melo、只读函数调用、音频打断、跨连接去重。

初次无参数工具调用产生了额外参数，按规则拒绝；随后补上封闭参数模式，并修正原生工具调用中间轮次尚未完成时不能提前播报的适配逻辑。首次失败收据未删除。

CPU-only一组测试中，简单问答的客户端首帧为26.26秒和4.98秒；跨机合成音频最后一次为3.78秒、63帧、双向哈希一致。不是与旧GPU跑分的同条件比较，也不是P95或电话另一端听感。显式打断确认23.39毫秒，确认后旧帧0。不能因此认为实时延迟目标已经达标。

只读工具代理失联时播报“结果尚未确认”，没有成功收据；代理恢复后取得真实诊断收据。清理旧目录和依赖缓存后，强制终止新模型容器，约14.10秒通过显式CPU-only启动恢复；原pending请求为unknown，同ID重提只返回duplicate，原本地测试记录仍只一条。

旧自写语音项目、废弃模型和安装缓存已清理；原始账本、10000尝试记录、必要模型和轻量验收凭据保留。新模型服务不自动启用，GPU继续停用。
