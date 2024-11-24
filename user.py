import library

@library.available_as("T")
async def get_temperature() -> float:
	async with open('/sys/class/thermal/thermal_zone0/temp','r') as temp:
		temperature = int(temp.read()) / 1000.0
	print(f"Temperature requested: {temperature}°C")
	return temperature

async def main_loop():
	if await library.get("switch", library.PROTOCOL_DATATYPES.bool):
		print("Switch on!")
	else:
		print("Switch off!")

library.start_network(device_id=1)