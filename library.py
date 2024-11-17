import asyncpio, asyncio
import serial_asyncio_fast as serial_asyncio

# Raspberry Pi 4B reference pinout from https://pinout.xyz/

# disable the Serial Console in raspi-config before using UART
PI_SERIAL_TX: int = 14 # UART Serial TX on BCM pin 14
PI_SERIAL_RX: int = 15 # UART Serial RX on BCM pin 15

class InputChunkProtocol(asyncio.Protocol):
	def connection_made(self, transport):
		self.transport = transport

	def data_received(self, data):
		print('data received', repr(data))

async def available_as(user_function: function, variable_name: str) -> 'None':
	pass

def start_network() -> 'None':
	pi = asyncpio.pi()
	loop = asyncio.get_event_loop()
	loop.run_until_complete(main(pi))

async def main(pi: asyncpio.pi) -> 'None':
	try:
		await pi.connect()
	except:
		print("Failure to connect")
		exit(1)
	hardware_rev = await pi.get_hardware_revision()
	print(f"Running on RPi hdw. rev. {format(hardware_rev,'#0x')}")
	
	# Register the handlers for various protocols
	# Serial UART
	loop = asyncio.get_running_loop()
	serial_pins = '/dev/serial0'
	# serial_usb = '/dev/ttyUSB0'
	uart_pin_coro = serial_asyncio.create_serial_connection(loop, InputChunkProtocol, serial_pins, baudrate=9600)
	loop.create_task(uart_pin_coro)
	while(True):
		await asyncio.sleep(3)
	# TODO: Serial when RX is high

if __name__ == "__main__":
	pi = asyncpio.pi()
	loop = asyncio.get_event_loop()
	loop.run_until_complete(main(pi))