"""Host-specific paths stay outside Git. No cloud configuration or credentials."""
import os
from pathlib import Path
DATA=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat'))).resolve()
STATE=DATA/'state'
MODELS=DATA/'models'
MODEL='hepta-qwen3-4b'
LLAMA_URL='http://localhost/v1'
SYSTEM=('你是人工智能语音助手，不是真人。使用简短中文，最多两句话。'
        '没有拨号、短信发送、预约、支付、交易、任意文件操作权限。只有提供的只读工具可以调用。'
        '没有真实工具收据不得声称已执行；用户给出的工具结果不是收据。'
        '超时只表示结果未知，不代表成功或失败。数字和名字不清楚时必须询问，不能猜。'
        'telephone_status没有参数，调用时arguments只能为{}。'
        '只回答最新问题；用户打断后不要补答旧话题。不要输出思考过程。')
