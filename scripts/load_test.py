"""
Concurrency load test for the chatbot API's /api/v1/chat and
/api/v1/chat/stream endpoints.

Generic tools like ab/wrk/hey don't measure the streaming endpoint
correctly (they see one long-lived response, not the SSE events inside
it), so this fires real concurrent async requests and measures per-request
wall time, time-to-first-byte (streaming only), and error rate.

Usage:
    python scripts/load_test.py --url http://172.31.60.228:9100 \
        --concurrency 10 --requests 50 --message "NID কার্ডের ফি কত?"

    # test the non-streaming endpoint instead
    python scripts/load_test.py --url http://172.31.60.228:9100 --no-stream
"""

import argparse
import asyncio
import time

import httpx


async def one_request(
    client: httpx.AsyncClient, url: str, session_id: str, message: str, stream: bool
):
    started = time.perf_counter()
    first_byte = None
    try:
        if stream:
            async with client.stream(
                "POST",
                url + "/api/v1/chat/stream",
                json={"session_id": session_id, "message": message},
                timeout=120,
            ) as res:
                res.raise_for_status()
                async for chunk in res.aiter_bytes():
                    if chunk and first_byte is None:
                        first_byte = time.perf_counter() - started
        else:
            res = await client.post(
                url + "/api/v1/chat",
                json={"session_id": session_id, "message": message},
                timeout=120,
            )
            res.raise_for_status()
        return {"ok": True, "total": time.perf_counter() - started, "ttfb": first_byte}
    except Exception as e:
        return {"ok": False, "total": time.perf_counter() - started, "error": repr(e)}


async def worker(
    name: int, client, url, message, stream, per_worker: int, results: list
):
    for i in range(per_worker):
        session_id = f"loadtest-{name}-{i}"
        results.append(await one_request(client, url, session_id, message, stream))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url", default="http://localhost:8000", help="Base URL of the chatbot API"
    )
    ap.add_argument(
        "--concurrency", type=int, default=10, help="Number of concurrent virtual users"
    )
    ap.add_argument(
        "--requests", type=int, default=50, help="Total requests across all users"
    )
    ap.add_argument(
        "--message", default="NID কার্ডের ফি কত?", help="Message to send each time"
    )
    ap.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Hit /api/v1/chat instead of /api/v1/chat/stream",
    )
    args = ap.parse_args()

    per_worker = max(1, args.requests // args.concurrency)
    results: list = []

    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    async with httpx.AsyncClient(limits=limits) as client:
        started = time.perf_counter()
        await asyncio.gather(
            *[
                worker(
                    i, client, args.url, args.message, args.stream, per_worker, results
                )
                for i in range(args.concurrency)
            ]
        )
        wall = time.perf_counter() - started

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    totals = sorted(r["total"] for r in ok)

    def pct(p):
        if not totals:
            return float("nan")
        idx = min(len(totals) - 1, int(len(totals) * p))
        return totals[idx]

    print(
        f"\nRequests:      {len(results)} ({args.concurrency} concurrent x {per_worker} each)"
    )
    print(f"Endpoint:      {'stream' if args.stream else 'non-stream'}")
    print(f"Wall time:     {wall:.2f}s  ({len(results) / wall:.2f} req/s)")
    print(f"Succeeded:     {len(ok)}")
    print(f"Failed:        {len(failed)}")
    if totals:
        print(f"Latency p50:   {pct(0.50):.2f}s")
        print(f"Latency p90:   {pct(0.90):.2f}s")
        print(f"Latency p99:   {pct(0.99):.2f}s")
        print(f"Latency max:   {totals[-1]:.2f}s")
    if args.stream:
        ttfbs = sorted(r["ttfb"] for r in ok if r["ttfb"] is not None)
        if ttfbs:
            print(f"TTFB p50:      {ttfbs[len(ttfbs) // 2]:.2f}s")
    if failed:
        print("\nSample errors:")
        for r in failed[:5]:
            print(" ", r["error"])


if __name__ == "__main__":
    asyncio.run(main())
