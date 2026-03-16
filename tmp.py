import asyncio

async def hello():
    print("Hello, world!")
    await asyncio.sleep(1)
    print("Goodbye, world!")

if __name__ == "__main__":
    asyncio.run(hello())
