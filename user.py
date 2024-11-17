import library

@library.available_as("T")
async def get_temperature() -> float:
	async with open('/sys/class/thermal/thermal_zone0/temp','r') as temp:
		temperature = int(temp.read()) / 1000.0
	print(f"Temperature requested: {temperature}°C")
	return temperature

library.start_network()