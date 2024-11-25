import asyncio
import numpy as np
from typing import Optional
from .utils import DTYPES,ENDIANNESS,Frame_Header,Device,add_metadata
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

	def __init__(self):
		super().__init__()
		self.buffer = bytearray()
		self.transport = None
		self.header: Optional[Frame_Header] = None

	def connection_made(self, transport):
		"""
		Called when the connection is established.
		"""
		self.transport = transport
		print("Connection established.")
		print(f"Write buffer size: {self.transport.get_write_buffer_size()}")
		# Start the task queue checking process for this protocol
		asyncio.create_task(self.check_queue())
	
	async def check_queue(self):
		while True:
			try:
				item = await State().tasks["uart"].get()
				print("Processing queue item:", item)
				# Send the item through the transport
				self.transport.write(item.encode())
			except asyncio.CancelledError:
				print("Queue processing stopped")
				break 

	def data_received(self, data):
		self.buffer.extend(data)
		
		# Keep processing frames as long as we have enough data
		# I will use guard clauses, otherwise this messy code
		# will become even messier
		while True:
			# If we don't have a header yet, try to parse one
			if not self.header:
				# Minimum bytes needed for header + start byte
				if len(self.buffer) < 5:  
					break
					
				# Validate start byte
				if self.buffer[5] != 255:  # Start byte should be 255
					# No start byte found, clear buffer
					print("No start byte found!")
					self.buffer.clear()
					break
				
				try:
					self.header = Frame_Header.from_bytes(self.buffer)
				except Exception as e:
					print(f"Error parsing header: {e}")
					# Skip one byte in case something old stayed and try again
					self.buffer = self.buffer[1:]
					continue
			
			# Check if we have a complete frame
			if len(self.buffer) < self.header.total_frame_length:
				break
				
			# We have a complete frame, process it
			frame = self.buffer[:self.header.total_frame_length]
			
			# Validate stop byte
			if frame[-1] != 255:
				print("Invalid stop byte")
				# Skip one byte and try again
				self.buffer = self.buffer[1:]
				self.header = None
				continue
				
			# Validate checksum
			# Exclude checksum and stop byte
			calculated_checksum = sum(frame[:-3])  
			# Reversal of what we did when constructing
			# Remember we wrote (msg_checksum//256, msg_checksum%256) in int
			# This is an 8-bit left shift (255 in int), and the remainder (%)
			# is in frame[-2] which gets added back after left-shifting
			received_checksum = (frame[-3] << 8) + frame[-2]
			
			if calculated_checksum != received_checksum:
				print(f"Checksum mismatch: expected {received_checksum}, got {calculated_checksum}")
				self.buffer = self.buffer[1:]  # Skip one byte and try again
				self.header = None
				continue
			
			# Process the validated frame
			try:
				self._process_frame(frame)
			except Exception as e:
				print(f"Error processing frame: {e}")
			finally:
				# Remove processed frame from buffer
				self.buffer = self.buffer[self.header.total_frame_length:]
				self.header = None

	def _process_frame(self, frame: bytes):
		"""Process a complete, validated frame"""
		payload = frame[6:-3]  # Skip header and checksum/stop byte
		command_type = payload[0]
		
		try:
			if command_type == 1:  # Add Device
				self.handle_add_device(payload)
			elif command_type == 2:  # Remove Device
				self.handle_remove_device(payload)
			elif command_type == 6:  # Put Command
				self.handle_put_command(payload)
			elif command_type == 7:  # Get Command
				self.handle_get_command(payload)
			else:
				print(f"Unknown command type: {command_type}")
			
			# Send acknowledgment if requested
			if self.header.ack:
				self._send_ack(self.header.nonce)
				
		except Exception as e:
			print(f"Error in command handler: {e}")
			if self.header.ack:
				self._send_ack(self.header.nonce, success=False)

	def _send_ack(self, nonce, success=True):
		pass

	def handle_add_device(self, payload: bytes):
		"""
		Handle the "add device" command.
		Adds the device ID from the payload to the devices list.
		"""
		if len(payload) < 2:
			raise ValueError("Invalid payload for add device")

		device_id = payload[1]
		chain = [dev for dev in payload[2:]]
		if device_id not in State().other_devices and (device_id != State().device_id):
			State().other_devices[device_id] = Device(device_id, chain, "uart")
			print(f"Device {device_id} added. Rebroadcasting...")
			new_payload = bytearray(payload).extend(State().device_id) # append our own id
			new_frame = add_metadata(0,new_payload)
			for protocol in State().tasks:
				# Distribute the new frame to all protocols
				State().tasks[protocol].put_nowait(new_frame)
		else:
			print(f"Device {device_id} already exists.")

		if len(chain) == 0:
			# If this device is adjacent to our node (it means it initiated the addition
			# for itself), we should send all of our registered devices to it
			pass

	def handle_remove_device(self, payload):
		"""
		Handle the "remove device" command.
		Removes the device ID from the devices list.
		"""
		if len(payload) < 2:
			raise ValueError("Invalid payload for add device")

		device_id = payload[1]
		if device_id in State().other_devices:
			State().other_devices.pop(device_id)
			print(f"Device {device_id} removed.")
			new_frame = add_metadata(0,payload)
			for protocol in State().tasks:
				# Distribute the new frame to all protocols
				State().tasks[protocol].put_nowait(new_frame)
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