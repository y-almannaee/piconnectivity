import asyncio
import numpy as np
from .utils import DTYPES,ENDIANNESS
from serial import EIGHTBITS, PARITY_ODD, STOPBITS_TWO
import serial_asyncio_fast as serial_asyncio
from .utils import State

# Raspberry Pi 4B reference pinout from https://pinout.xyz/

# disable the Serial Console in raspi-config before using UART
PI_SERIAL_TX: int = 14 # UART Serial TX on BCM pin 14
PI_SERIAL_RX: int = 15 # UART Serial RX on BCM pin 15

# https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial
SERIAL_BAUDRATE: int = 9600
SERIAL_BYTESIZE = EIGHTBITS
SERIAL_PARITY = PARITY_ODD
SERIAL_STOPBITS = STOPBITS_TWO
SERIAL_TIMEOUT: int = 15 # in seconds

class UART_Handler_Protocol(asyncio.Protocol):
	def connection_made(self, transport):
		"""
		Called when the connection is established.
		"""
		self.transport = transport
		print("Connection established.")
		# Start the task queue checking process for this protocol
		asyncio.create_task(self.check_queue())
	
	async def check_queue(self):
		while True:
			try:
				item = await State().tasks["uart"].get()
				print("Processing queue item:", item)
				# Optionally, send the item through the transport
				self.transport.write(item.encode())
			except asyncio.CancelledError:
				print("Queue processing stopped")
				break 

	def data_received(self, data):
		"""
		Called when data is received. Parses the frame and handles the command.
		"""
		print("Data received:", repr(data))

		# Ensure the frame is valid
		if not data or len(data) < 7:
			print("Invalid frame: too short.")
			return

		# Parse the frame structure
		msg_len = int.from_bytes(data[0:1], byteorder=ENDIANNESS)
		nonce = data[1:2]
		ack = data[2:3]
		start_byte = data[3:4]
		if start_byte[0] != 255:
			print("Invalid frame: missing start byte.")
			return

		command_type = int.from_bytes(data[4:5], byteorder=ENDIANNESS)
		payload = data[5:-4]  # Extract payload (excluding checksum and stop byte)
		checksum, stop_byte = data[-3:-1], data[-1:]

		# Validate stop byte
		if stop_byte[0] != 255:
			print("Invalid frame: missing stop byte.")
			return

		# Process commands based on command type
		if command_type == 1:  # Add Device
			self.handle_add_device(payload)
		elif command_type == 2:  # Remove Device
			self.handle_remove_device(payload)
		elif command_type == 6:  # Put Command
			self.handle_put_command(payload)
		else:
			print(f"Unknown command type: {command_type}")

	def handle_add_device(self, payload):
		"""
		Handle the "add device" command.
		Adds the device ID from the payload to the devices list.
		"""
		if len(payload) < 1:
			print("Invalid payload for add device.")
			return

		device_id = int.from_bytes(payload[0:1], byteorder=ENDIANNESS)
		if device_id not in self.devices:
			self.devices.append(device_id)
			print(f"Device {device_id} added.")
		else:
			print(f"Device {device_id} already exists.")

	def handle_remove_device(self, payload):
		"""
		Handle the "remove device" command.
		Removes the device ID from the devices list.
		"""
		if len(payload) < 1:
			print("Invalid payload for remove device.")
			return

		device_id = int.from_bytes(payload[0:1], byteorder=ENDIANNESS)
		if device_id in self.devices:
			self.devices.remove(device_id)
			print(f"Device {device_id} removed.")
		else:
			print(f"Device {device_id} not found.")

	def handle_put_command(self, payload):
		"""
		Handle the "put" command.
		Updates a variable with the specified name, datatype, and value.
		"""
		if len(payload) < 3:
			print("Invalid payload for put command.")
			return

		# Extract variable name length and name
		name_length = int.from_bytes(payload[0:1], byteorder=ENDIANNESS)
		name = payload[1:1 + name_length].decode()

		# Extract datatype and value
		datatype = DTYPES(int.from_bytes(payload[1 + name_length:2 + name_length], byteorder=ENDIANNESS))
		value_data = payload[2 + name_length:]

		# Convert value based on datatype
		if datatype.python_type is int:
			value = int.from_bytes(value_data, byteorder=ENDIANNESS, signed=datatype.is_signed)
		elif datatype.python_type is bool:
			value = bool(int.from_bytes(value_data, byteorder=ENDIANNESS))
		elif datatype.python_type is str:
			value = value_data.decode()
		elif datatype.python_type is float:
			value = np.frombuffer(value_data, dtype=datatype.numpy_dtype)[0]
		else:
			print(f"Unsupported datatype: {datatype}")
			return

		# Update the variable in state
		if name in State().readables:
			State().readables[name] = value
			print(f"Updated variable '{name}' with value {value}.")
		else:
			print(f"Variable '{name}' not found in state.")

async def start_UART(pins: str):
	loop = asyncio.get_event_loop()
	transport, protocol = await serial_asyncio.create_serial_connection(
		loop, 
		UART_Handler_Protocol, 
		pins, 
		baudrate=SERIAL_BAUDRATE, 
		bytesize=SERIAL_BYTESIZE, 
		#parity=SERIAL_PARITY, 
		stopbits=SERIAL_STOPBITS, 
		timeout=SERIAL_TIMEOUT
	)
	return transport, protocol