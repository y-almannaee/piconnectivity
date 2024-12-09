import asyncio
import numpy as np
from random import randint
from datetime import datetime, timedelta
from typing import Optional
from .utils import DTYPES, ENDIANNESS, Frame_Header, Device, add_metadata, put, get
from .utils import rep_bytearray
from serial import EIGHTBITS, PARITY_ODD, STOPBITS_TWO
import serial_asyncio_fast as serial_asyncio
from .utils import State

# Raspberry Pi 4B reference pinout from https://pinout.xyz/

# disable the Serial Console in raspi-config before using UART
PI_SERIAL_TX: int = 14  # UART Serial TX on BCM pin 14
PI_SERIAL_RX: int = 15  # UART Serial RX on BCM pin 15

# https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial
SERIAL_BAUDRATE: int = 9600
SERIAL_BYTESIZE = EIGHTBITS
SERIAL_PARITY = PARITY_ODD
SERIAL_STOPBITS = STOPBITS_TWO
SERIAL_TIMEOUT: int = 15  # in seconds


class UART_Handler_Protocol(asyncio.Protocol):
    timeout = 15

    def __init__(self):
        super().__init__()
        self.buffer = bytearray()
        self.transport = None
        self.header: Optional[Frame_Header] = None
        self.device_found = 0
        self.pending_acks = {}
        self.ack_lock = asyncio.Lock()

    def connection_made(self, transport):
        """
        Called when the connection is established.
        """
        self.transport = transport
        print("Connection established.")
        print(f"Write buffer size: {self.transport.get_write_buffer_size()}")
        # Start the task queue checking process for this protocol
        asyncio.create_task(self.check_queue())
        # Start the discovery task
        asyncio.create_task(self.issue_discovery())
        # Start the trash-collector task (ack not received)
        asyncio.create_task(self.ack_garbageman())

    async def disconnect_device(self):
        async with self.ack_lock:
            new_payload = bytearray()
            new_payload.extend((2, self.device_found))
            new_frame = add_metadata(0, new_payload)
            for protocol in State().tasks:
                # Distribute the new frame to all protocols
                State().tasks[protocol].put_nowait(new_frame)
            State().awaiting_connection[self.device_found].clear()
            print(f"Device with ID {self.device_found} disconnected")
            self.device_found = 0
            self.pending_acks.clear()

    async def ack_garbageman(self):
        while True:
            try:
                if self.device_found == 0:
                    # No device, just sleep
                    await asyncio.sleep(5)
                    continue
                async with self.ack_lock:
                    for seq, item in self.pending_acks.items():
                        if item[0] + timedelta(seconds=self.timeout) < datetime.now():
                            # if the item's datetime is older than the timeout
                            if item[2] == 0:
                                # First timeout, send the item through the transport again
                                print("An item just timed out once")
                                self.pending_acks[seq] = (datetime.now(), item[1], 1)
                                self.transport.write(item[1])
                            else:
                                # consider the device timed out
                                await self.disconnect_device()
                await asyncio.sleep(self.timeout / 2)
            except asyncio.CancelledError:
                print("UART garbageman told to go home")
                break

    async def issue_discovery(self):
        while True:
            try:
                if self.device_found != 0:
                    # If we have a device connected, just sleep
                    await asyncio.sleep(5)
                    continue
                # Otherwise we broadcast ourselves as a new device to be added
                discovery_payload = bytearray()
                # 1 (add device) and our device ID
                discovery_payload.extend((1, State().device_id))
                discovery_frame = add_metadata(0, discovery_payload)
                State().tasks["uart"].put_nowait(discovery_frame)
                await asyncio.sleep(randint(3, 8))
            except asyncio.CancelledError:
                print("UART discovery cancelled")
                break

    async def check_queue(self):
        while True:
            try:
                item = await State().tasks["uart"].get()
                print("Sending queue item:", rep_bytearray(item))
                # Send the item through the transport
                seq = bytes(item[3:5])
                ack_req = item[5]
                if item[0] == State().device_id and ack_req == 255:
                    # If it's our own item and we want an ack
                    async with self.ack_lock:
                        self.pending_acks[seq] = (datetime.now(), item, 0)
                self.transport.write(item)
            except asyncio.CancelledError:
                print("UART queue processing stopped")
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
                if len(self.buffer) < Frame_Header.min_for_header():
                    break

                # Validate start byte
                if (
                    self.buffer[Frame_Header.start_byte()] != 255
                ):  # Start byte should be 255
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
            frame = self.buffer[: self.header.total_frame_length]

            # Validate stop byte
            if frame[-1] != 255:
                print("Invalid stop byte")
                # Skip one byte and try again
                self.buffer = self.buffer[1:]
                self.header = None
                continue

            # Exclude checksum and stop byte
            calculated_checksum = sum(frame[:-3])
            # Reversal of what we did when constructing
            # Remember we wrote (msg_checksum//256, msg_checksum%256) in int
            # This is an 8-bit left shift (255 in int), and the remainder (%)
            # is in frame[-2] which gets added back after left-shifting
            received_checksum = (frame[-3] << 8) + frame[-2]

            if calculated_checksum != received_checksum:
                print(
                    f"Checksum mismatch: expected {received_checksum}, got {calculated_checksum}"
                )
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
                self.buffer = self.buffer[self.header.total_frame_length :]
                self.header = None

    def _process_frame(self, frame: bytes):
        """Process a complete, validated frame"""
        recipient = self.header.recipient_id
        if recipient != 0 and recipient != State().device_id:
            # Pass the frame to the next device
            iface = State().other_devices[recipient].iface
            State().tasks[iface].put_nowait(frame)
            return
        payload = frame[
            self.header.start_byte() + 1 : -3
        ]  # Skip header and checksum/stop byte
        command_type = payload[0]

        try:
            if command_type == 1:  # Add Device
                self.handle_add_device(payload)
            elif command_type == 2:  # Remove Device
                self.handle_remove_device(payload)
            elif command_type == 6:  # Put Command
                self.handle_put_command(payload)
            elif command_type == 7:  # Get Command
                asyncio.create_task(
                    self.handle_get_command(
                        payload, self.header.sender_id, self.header.sequence
                    )
                )
            elif command_type == 0:  # ack
                self.handle_ack(payload)
            else:
                print(f"Unknown command type: {command_type}")

            # Send acknowledgment if requested
            # Get command is excluded because it sends the value
            # using the ack framework already
            if command_type != 7 and self.header.ack:
                self._send_ack()
        except Exception as e:
            print(f"Error in command handler: {e}")
            if self.header.ack:
                self._send_ack(success=False)

    def _send_ack(self, success=True):
        if self.header.ack is False:
            return
        payload = bytearray()
        ack = 255 if success else 127
        payload.extend((0, ack))
        payload += self.header.sequence
        new_frame = add_metadata(self.header.sender_id, payload, ack=False)
        State().tasks["uart"].put_nowait(new_frame)

    def handle_ack(self, payload: bytes):
        seq = bytes(payload[2:4])
        async def pop_ack():
            # Because we can't have async code in the data_received method (only
            # blocking code, unforch), we create a function that will pop our
            # ack safely with the lock
            async with self.ack_lock:
                try:
                    self.pending_acks.pop(seq)
                except KeyError as e:
                    raise Exception(f"No such ack sequence {seq}") from None
                print(f"Ack received for {int.from_bytes(seq,'little')}")
                if len(payload) > 4:
                    # if there are more than 4 bytes
                    # (indicating there is a get response)
                    dtype = DTYPES.from_protocol_number(payload[4])
                    data = DTYPES.revert(payload[5:], dtype)
                    print(f"Returning future")
                    State().futures[seq].set_result(data)
        asyncio.create_task(pop_ack())

    def handle_add_device(self, payload: bytes):
        """
        Handle the "add device" command.
        Adds the device ID from the payload to the devices list.
        """
        if len(payload) < 2:
            raise ValueError("Invalid payload for add device")

        device_id = payload[1]
        chain = [dev for dev in payload[2:]]
        print(f"Received add command for ID {device_id} and chain {chain}")
        if device_id == State().device_id:
            return
        if device_id not in State().other_devices:
            State().other_devices[device_id] = Device(device_id, chain, "uart")
            print(f"Device {device_id} added. Rebroadcasting...")
            new_payload = bytearray(payload)
            new_payload.extend((State().device_id,))  # append our own id
            new_frame = add_metadata(0, new_payload)
            for protocol in State().tasks:
                # Distribute the new frame to all protocols
                State().tasks[protocol].put_nowait(new_frame)
        else:
            print(f"Device {device_id} already exists.")
            State().other_devices[device_id].update(chain, "uart")

        if len(chain) == 0:
            # If this device is adjacent to our node (it means it initiated the addition
            # for itself), we should send all of our registered devices to it
            if self.device_found == 0:
                self.device_found = device_id
                new_payload = bytearray()
                new_payload.extend((1, State().device_id))
                new_frame = add_metadata(device_id, new_payload)
                State().tasks["uart"].put_nowait(new_frame)
            for other_device_id, dev in State().other_devices.items():
                if other_device_id == device_id:
                    continue
                # for each device
                for chains in dev.chain:
                    new_payload = bytearray()
                    new_payload.extend((1, other_device_id))
                    new_payload.extend([d.id for d in chains])
                    new_frame = add_metadata(device_id, new_payload)
                    State().tasks[protocol].put_nowait(new_frame)

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
            new_frame = add_metadata(0, payload)
            if device_id == self.device_found:
                asyncio.create_task(self.disconnect_device())
            else:
                for protocol in State().tasks:
                    # Distribute the new frame to all protocols
                    State().tasks[protocol].put_nowait(new_frame)
        else:
            print(f"Device {device_id} not found.")

    def handle_put_command(self, payload):
        put(payload)

    async def handle_get_command(self, payload: bytes, sender_id: int, sequence: bytes):
        datatype, value = await get(payload)
        if value is None:
            self._send_ack(success=False)
        new_payload = bytearray()
        new_payload.extend((0, 255))
        new_payload += sequence
        new_payload.extend((datatype.convert(),))
        new_payload += datatype.to_bytes(value)
        new_frame = add_metadata(sender_id, new_payload)
        State().tasks["uart"].put_nowait(new_frame)


async def start_UART(pins: str):
    loop = asyncio.get_event_loop()
    transport, protocol = await serial_asyncio.create_serial_connection(
        loop,
        UART_Handler_Protocol,
        pins,
        baudrate=SERIAL_BAUDRATE,
        bytesize=SERIAL_BYTESIZE,
        # parity=SERIAL_PARITY,
        stopbits=SERIAL_STOPBITS,
        timeout=SERIAL_TIMEOUT,
    )
    return transport, protocol
