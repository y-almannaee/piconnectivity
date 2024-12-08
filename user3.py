import library, asyncio


async def main_loop():
    while True:
        await library.wait_for_connect(8)
        other_greeting = await library.get(8, "HWorld")
        print(f"Device with id 8: {other_greeting}")
        await asyncio.sleep(5)


library.schedule(main_loop)
library.start_network()
