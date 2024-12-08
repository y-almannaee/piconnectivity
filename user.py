import library, asyncio, numpy


@library.available_as("T", library.DTYPES.double)
async def get_temperature() -> float:
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp:
        temperature = numpy.double(int(temp.read()) / 1000.0)
    print(f"Temperature requested: {temperature:.2f}°C")
    return temperature


@library.available_as("HWorld", library.DTYPES.char)
async def hello_world() -> str:
    return "Hello, world!"


async def main_loop():
    while True:
        if switch.value:
            print("Switch on!")
        else:
            print("Switch off!")
        await asyncio.sleep(5)


switch = library.define_store("switch", library.DTYPES.bool)
library.schedule(main_loop)
library.start_network(device_id=8)
