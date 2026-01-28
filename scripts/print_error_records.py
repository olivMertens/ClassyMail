import asyncio
import json

from classificationg2s.cli import ensure_cosmos_container, cosmos_container, close_cosmos


async def main(limit: int = 5, include_processing_log: bool = True):
    await ensure_cosmos_container()
    query = "SELECT * FROM c WHERE c.status = 'ERROR' ORDER BY c.updated_at DESC"
    items = []
    it = cosmos_container.query_items(query)
    async for item in it:
        items.append(item)
        if len(items) >= limit:
            break

    for idx, item in enumerate(items, 1):
        print(f"[{idx}] id={item.get('id')} status={item.get('status')} error_stage={item.get('error_stage')}")
        print(f"error: {item.get('error')}")
        if include_processing_log:
            plog = item.get('processing_log')
            if plog:
                print("processing_log:")
                for entry in plog:
                    print(json.dumps(entry, ensure_ascii=False, indent=2))
            else:
                print("processing_log: <none>")
        print("-" * 80)

    await close_cosmos()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Print recent ERROR records from Cosmos DB")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-log", action="store_true", help="Do not show processing_log")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, include_processing_log=not args.no_log))
