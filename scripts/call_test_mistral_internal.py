import asyncio
from classificationg2s.api.routers.admin import test_mistral_ocr_connection
from classificationg2s.services.azure_clients import Clients

async def main():
    clients = Clients()
    await clients.init()
    try:
        res = await test_mistral_ocr_connection(clients)
        print(res)
        with open('tmp_mistral_test_output.txt', 'w', encoding='utf-8') as f:
            f.write(str(res))
    finally:
        await clients.close()

if __name__ == '__main__':
    asyncio.run(main())
