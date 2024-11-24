import library, asyncio

@library.available_as("T")
async def get_temperature() -> float:
	async with open('/sys/class/thermal/thermal_zone0/temp','r') as temp:
		temperature = int(temp.read()) / 1000.0
	print(f"Temperature requested: {temperature}°C")
	return temperature

async def main_loop():
	while True:
		if switch._value:
			print("Switch on!")
		else:
			print("Switch off!")
		await asyncio.sleep(5)

switch = library.define_store("switch", library.DTYPES.bool)
library.schedule(main_loop())
library.start_network(device_id=1)