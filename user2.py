import library, asyncio


async def main_loop():
    while True:
        await library.wait_for_connect(8)
        try:
            other_temp = await library.get(8, "T")
            print(f"Device with id 8 temp: {other_temp}")
            if other_temp < 42.0:
                print("Setting device with id 8 switch to on")
                await library.put(8, "switch", library.DTYPES.bool, True)
            await asyncio.sleep(5)
        except asyncio.TimeoutError:
            print("Apparently the device has disconnected, let's wait.")


library.schedule(main_loop)
library.start_network()
