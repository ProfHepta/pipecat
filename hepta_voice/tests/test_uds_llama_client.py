"""Synthetic Unix socket model fixture; never uses the Pocket4 secret or GPU.

Proves that the Pipecat LLM adapter and OpenAI SDK can reach an authenticated
AF_UNIX HTTP endpoint. Not a real cross-host or first-audio acceptance test.
"""
import json
import pytest
from aiohttp import web
from hepta_voice.config import MODEL,LLAMA_URL
from hepta_voice import llama_client

@pytest.mark.asyncio
async def test_authenticated_uds_openai_chat_stream(tmp_path, monkeypatch):
    fake_key = 'synthetic-local-test-token-' + 'ab' * 24
    (tmp_path / 'llama.key').write_text(fake_key)
    monkeypatch.setattr(llama_client, 'STATE', tmp_path)
    requests = []

    async def chat(request):
        assert request.headers.get('Authorization') == 'Bearer ' + fake_key
        body = await request.json()
        requests.append(body)
        assert body['model'] == MODEL
        response = web.StreamResponse(status=200, headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        for delta, finish in [('三加五等于八。', None), ('', 'stop')]:
            chunk = {
                'id': 'synthetic-test-chunk', 'object': 'chat.completion.chunk',
                'created': 0, 'model': MODEL,
                'choices': [{'index': 0, 'delta': {'content': delta}, 'finish_reason': finish}],
            }
            await response.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
        await response.write(b'data: [DONE]\n\n')
        return response

    app = web.Application()
    app.router.add_post('/v1/chat/completions', chat)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.UnixSite(runner, str(tmp_path / 'llama.sock')).start()
    try:
        service = llama_client.LocalLlamaService(
            settings=llama_client.LocalLlamaService.Settings(model=MODEL)
        )
        client = service._client
        completion = await client.chat.completions.create(
            model=MODEL, messages=[{'role': 'user', 'content': '三加五等于几？'}], stream=True,
        )
        received = []
        async for chunk in completion:
            received.append(chunk.choices[0].delta.content or '')
        assert ''.join(received) == '三加五等于八。'
        assert len(requests) == 1
        await client.close()
    finally:
        await runner.cleanup()


def test_no_credential_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(llama_client, 'STATE', tmp_path)
    with pytest.raises(FileNotFoundError):
        llama_client.LocalLlamaService(settings=llama_client.LocalLlamaService.Settings(model=MODEL))


def test_nonlocal_url_refused_even_with_test_key(tmp_path, monkeypatch):
    (tmp_path / 'llama.key').write_text('synthetic-' + '12' * 24)
    monkeypatch.setattr(llama_client, 'STATE', tmp_path)
    service = llama_client.LocalLlamaService(settings=llama_client.LocalLlamaService.Settings(model=MODEL))
    with pytest.raises(ValueError):
        service.create_client(api_key='irrelevant', base_url='https://example.com/v1')
