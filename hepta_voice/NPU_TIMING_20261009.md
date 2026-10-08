# GPU语音接线与独立NPU实验：2026-10-09

## 状态结论

GPU→Pipecat的真实连接仍未完成。本轮基本执行/读取通道已恢复，固定Vulkan启动器源码已写入并复制到Pocket4，但随后GPU服务部署与凭据转移的工具调用被平台安全检查拦截。没有换路绕过，也没有将启动器文件存在算成运行成功。现有Vulkan+FA/F16/4K基准结论不变；没有新的完整首音或电话对端首音成绩。

代码新增8个主机侧阶段时间戳：输入结束标记到达、ASR开始、最终转写、LLM请求开始、首token、回复校验完成、首段合成完成、首PCM帧发送。Pocket4客户端另外保存源端最后有效音频帧发送与第一帧接收的同机单调时钟值。阶段间耗时仅在同一时钟域计算，缺失阶段不补零，逆序记录不算通过。

当前输入结束标记用于合成测试：最后一个RMS>500的20ms PCM帧，不是人工声学结束点。两台机器的单调时钟禁止直接相减。69项单元测试通过；这些埋点尚未经过新的GPU完整链路验收，旧CPU/GPU性能不能填入本轮首音字段。

## Pocket4 NPU真正跑通的部分

硬件为Ryzen AI 9 HX370、XDNA2/AIE2P 6×8，设备`/dev/accel/accel0`，固件1.1.2.64，内核7.0.0-38-generic，XRT2.25.37。

初始`xrt-smi examine`报64MiB映射失败、errno=-11。当前SSH会话memlock软/硬限制只有8MiB。仅为诊断子进程临时提高memlock，再降到alex用户、设置no-new-privileges，XRT即可枚举NPU。没有改`/etc/security/limits.conf`、驱动、固件或全局权限；原会话限制仍为8MiB。

XRT真实INT8 GEMM验证：`PASSED`，工具报告51.0 TOPS，测试处于default功耗模式。这不是ASR吞吐量、LLM token/s或首音性能。

FastFlowLM1.0.7的Ubuntu26.04官方包经发布摘要校验后，只解包到独立用户目录；缺失的Boost库也只下载/解包到该实验目录，没有执行系统安装脚本。`flm validate --json`为ready=true。之后确实运行了Whisper候选：进程持有accel0，映射libwhisper_npu.so，实际完成18次音频转写。

## 固定模型身份

- FLM包SHA256：`0b4913f089046b31cabb565541f769250710bf70470dbfe891a02437a5ed9c71`
- FLM可执行文件SHA256：`ae6ac97c1520fd1ab5f2194c57b9bdf3dd32f527a0794315cb99ae2d62a1c48c`
- Whisper模型仓库：FastFlowLM/Whisper-V3-Turbo-NPU2
- 固定修订：`594eecd2d80b20cbb04ef0099162335d1dd1899a`
- 权重SHA256：`8fb97604bf5762ee26efa696cfc9eb70724110358c7b4ca628a7973bf8a16291`

## NPU ASR候选结果：不替换现有识别

6句预先固定的Melo合成音频，8kHz单声道16位，每句重复3次；每段长1.242–2.531秒。

|项目|实测|
|---|---:|
|NPU ASR HTTP响应次数|18|
|NPU ASR响应最小/中位/最大|2.081 / 2.204 / 2.521秒|
|忽略标点、统一单个数字字符后完整匹配|6/18（仅两句在三轮均匹配）|
|字符编辑数/参考字符数|42/165|
|现有SenseVoice在同6段音频上的函数耗时中位数|0.195秒|
|SenseVoice对应完整匹配|3/6|

例如，“三加五等于八”被NPU候选识别为“大家有得愈吧”；“不是六点，是七点”被识别为“56点17年”。后一句现有SenseVoice也识别错误，故不能把全部问题归咎于NPU：合成可懂度、重采样和模型本身都需要区分。

NPU数字为Pocket4上的HTTP转写时间，包含音频文件处理；SenseVoice数字为qian-qi CPU上的解码函数时间，调用边界、模型和硬件都不同。因此不能将二者倍率宣传为NPU与CPU的纯硬件对比。18次只有6种独立输入，也不是P95、真人听感或生产准确率。

该候选的短句延迟和质量没有达到替换门槛，保持独立实验，不接入Pipecat主链路。完整语音首音、取消语义及GPU并行负载没有继续验收，不能记为通过。NPU进程已结束，设备FD已释放；没有保留服务监听，没有替换SenseVoice、没有启用自动接听。

## 本机证据

Pocket4：`~/.local/state/hepta-npu-probe-20261009/`，包含XRT/FLM校验、模型清单、逐请求结果和运行日志。实验资产在`~/.local/share/hepta-npu-lab/`。

qian-qi：`~/.local/state/hepta-link-20261009/`。源码中的`benchmarks/npu-asr-20261009.json`为脱敏摘要，`timing.py`与客户端改动为尚待真实接线验证的埋点。
