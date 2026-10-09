"""Bounded immutable cache for static non-business prompts, not arbitrary answers.
A cache hit may save synthesis work; it does not assert that any action happened.
"""
import hashlib,re
from dataclasses import dataclass
FIXED_TEXTS=frozenset({'你好。','工具暂时不可用，结果尚未确认。','我是人工智能语音助手，不是真人接线员。'})
def normalized(text):return re.sub(r'[\s，。！？、,.!?]','',text)
@dataclass(frozen=True)
class CachedPrompt:
 text:str
 identity:str
 pcm:bytes
 sha256:str
class FixedPromptCache:
 def __init__(self,identity:str,max_bytes:int=2*1024*1024):
  if not identity or max_bytes<640:raise ValueError('invalid_cache_configuration')
  self.identity=identity;self.max_bytes=max_bytes;self._entries={}
 def add(self,text:str,pcm:bytes,transcript:str,identity:str)->bool:
  if text not in FIXED_TEXTS:raise ValueError('dynamic_or_unreviewed_text_not_cacheable')
  if identity!=self.identity:raise ValueError('model_identity_mismatch')
  if normalized(text)!=normalized(transcript):return False
  if not isinstance(pcm,bytes) or len(pcm)%2 or not 640<=len(pcm)<=640000:raise ValueError('bad_pcm')
  old=self._entries.get(text);budget=sum(len(e.pcm) for e in self._entries.values())-(len(old.pcm) if old else 0)
  if budget+len(pcm)>self.max_bytes:raise ValueError('cache_budget_exceeded')
  self._entries[text]=CachedPrompt(text,identity,pcm,hashlib.sha256(pcm).hexdigest());return True
 def get(self,text:str,identity:str)->bytes|None:
  if identity!=self.identity:return None
  entry=self._entries.get(text)
  if entry is None or hashlib.sha256(entry.pcm).hexdigest()!=entry.sha256:return None
  return entry.pcm

def cache_identity(model_files:dict,engine_version:str,settings:dict)->str:
 """Bind every local lexicon/token/FST/weight input, not only the weight file."""
 import json
 if not model_files or not engine_version:raise ValueError('missing_model_identity')
 manifest={}
 for name,path in sorted(model_files.items()):
  h=hashlib.sha256()
  with open(path,'rb') as f:
   while chunk:=f.read(1024*1024):h.update(chunk)
  manifest[name]=h.hexdigest()
 payload={'files':manifest,'engine':engine_version,'settings':settings}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
