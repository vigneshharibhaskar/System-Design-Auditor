import asyncio
import threading
import time

import app.main as main_module


def test_retrieval_concurrency_is_bounded(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def _fake_retrieve_context(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return [{"source_file": "x.pdf", "page": 0, "quote": "q"}], "ctx"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(main_module, "retrieve_context", _fake_retrieve_context)
    monkeypatch.setattr(main_module, "RETRIEVAL_SEMAPHORE", asyncio.Semaphore(2))

    async def _run_many():
        tasks = [
            asyncio.create_task(
                main_module._retrieve_context_with_limit(
                    collection="default",
                    query="q",
                    top_k=1,
                    file_filter=None,
                    timeout_seconds=2.0,
                )
            )
            for _ in range(10)
        ]
        await asyncio.gather(*tasks)

    asyncio.run(_run_many())
    assert max_active <= 2
