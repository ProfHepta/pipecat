"""Local llama.cpp over an authenticated SSH Unix-socket relay; no cloud fallback."""
import httpx2
from openai import AsyncOpenAI
from pipecat.services.openai.llm import OpenAILLMService
from .config import STATE,MODEL,LLAMA_URL

def verify_engine_properties(props):
    if props.get('model_alias')!=MODEL:raise RuntimeError('engine_model_alias_mismatch')
    if props.get('model_ftype')!='Q4_K - Medium':raise RuntimeError('engine_quantization_mismatch')
    if props.get('total_slots')!=1:raise RuntimeError('engine_parallelism_mismatch')
    if props.get('default_generation_settings',{}).get('n_ctx')!=4096:raise RuntimeError('engine_context_mismatch')
    return True

class LocalLlamaService(OpenAILLMService):
    supports_developer_role=False
    def __init__(self,**kwargs):
        key=(STATE/'llama.key').read_text().strip()
        if len(key)<32:raise RuntimeError('invalid_local_engine_key')
        super().__init__(api_key=key,base_url=LLAMA_URL,**kwargs)
    def create_client(self,api_key=None,base_url=None,**kwargs):
        if base_url!=LLAMA_URL:raise ValueError('only_fixed_local_engine_endpoint_allowed')
        transport=httpx2.AsyncHTTPTransport(uds=str(STATE/'llama.sock'),trust_env=False,retries=0)
        return AsyncOpenAI(api_key=api_key,base_url=base_url,max_retries=0,
            http_client=httpx2.AsyncClient(transport=transport,trust_env=False,timeout=httpx2.Timeout(90,connect=3)))
