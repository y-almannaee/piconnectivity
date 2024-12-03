import library, asyncio

async def main_loop():
	while True:
		other_temp = await library.get(8,"T")
		print(f"Device with id 8 temp: {other_temp}")
		if other_temp < 42.0:
			print("Setting device with id 8 switch to on")
			await library.put(8, "switch", library.DTYPES.bool, True)
		await asyncio.sleep(5)

library.schedule(main_loop)
library.start_network()