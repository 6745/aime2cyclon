import serial
import time
import math
import json
import pyautogui
import configparser  # Import configparser module

# Load configuration from the .ini file
config = configparser.ConfigParser()
config.read('settings.ini')

# Read com_port and baudrate from the config file
com_port = config['SerialSettings'].get('COMPort', 'COM4')  # Default to COM4 if not set
baudrate = config['SerialSettings'].getint('BaudRate', 38400)  # Default to 38400 if not set

print("Waiting 10 seconds before trying to talk to the reader to ensure the serial is closed")
time.sleep(10)

AIME_ESCAPE = 0xd0
RESET_CMD = 0x62
LED_CMD = 0x81
FELICA_CMD = 0x42
UNK_CARD_CMD_1 = 0x40
UNK_CARD_CMD_2 = 0x42
UNK_1 = 0x00
UNK_2 = 0x08


class AimeTest:
    def __init__(self, chusan=False):
        self.seq = 0
        self.curr_col = 0
        self.rainbow_dir = True
        self.last_poll = None
        self.active = True
        self._chusan = chusan
        self.com_port = com_port  # Use the config value for com_port
        self.baudrate = baudrate  # Use the config value for baudrate
        self.serial_port = None

    @property
    def seqnum(self):
        seq = self.seq
        if seq > 0xff:
            self.seq = 0
        else:
            self.seq += 1
        return seq

    def checksum(self, command):
        chksm = command['length'] + command['unk'] + command['seqnum'] + command['command']
        chksm += sum(command['data'])
        return chksm % 256

    def send_command(self, unk, command_byte, data):
        print(f"Sending command: unk={unk}, command_byte={command_byte}, data={data}")
        command = {
            'sync': 0xE0,
            'length': len(data) + 4,
            'unk': unk,
            'seqnum': self.seqnum,
            'command': command_byte,
            'data': data
        }
        command['checksum'] = self.checksum(command)

        self.serial_port.write(bytes([command['sync']]))
        self.write_escaped_byte(command['length'])
        self.write_escaped_byte(command['unk'])
        self.write_escaped_byte(command['seqnum'])
        self.write_escaped_byte(command['command'])
        for byte in command['data']:
            self.write_escaped_byte(byte)
        self.write_escaped_byte(command['checksum'])
        print("Command sent.")

    def read_serial(self):
        sync = 0x00
        while sync != 0xe0:
            sync = self.read_byte()
        length = self.read_byte()
        unk = self.read_byte()
        seqnum = self.read_byte()
        self.seq = seqnum
        command = self.read_byte()
        data = self.read_total_length(length - 4)
        checksum = self.read_byte()

        return {
            'sync': sync,
            'length': length,
            'unk': unk,
            'seqnum': seqnum,
            'command': command,
            'data': data,
            'checksum': checksum
        }

    def read_total_length(self, bytes_to_read):
        data = []
        for _ in range(bytes_to_read):
            data.append(self.read_byte())
        return data

    def read_byte(self):
        byte = self.serial_port.read(1)[0]
        if byte == AIME_ESCAPE:
            byte = self.serial_port.read(1)[0] + 1
        return byte

    def write_escaped_byte(self, b):
        if b > 255:
            print(f"Warning: Byte {b} out of range. Modulo applied.")
            b = b % 256  # Ensure byte is in range
        if b == AIME_ESCAPE or b == 0xe0:
            self.serial_port.write(bytes([AIME_ESCAPE, b - 1]))
        else:
            self.serial_port.write(bytes([b]))

    def send_led(self, red, green, blue):
        print(f"Sending LED command: red={red}, green={green}, blue={blue}")
        data = [0x03, red, green, blue]
        self.send_command(UNK_2, LED_CMD, data)

    def led_rainbow(self):
        frequency = 0.3
        red = int((math.sin(frequency * self.curr_col + 0) * 127 + 128))
        green = int((math.sin(frequency * self.curr_col + 4) * 127 + 128))
        blue = int((math.sin(frequency * self.curr_col + 2) * 127 + 128))
        self.send_led(red, green, blue)
        self.curr_col += 1 if self.rainbow_dir else -1
        if self.curr_col == 31 or self.curr_col == 0:
            self.rainbow_dir = not self.rainbow_dir
        time.sleep(0.15)

    def reader_init(self):
        self.send_command(UNK_1, RESET_CMD, [0x00])
        response = self.read_serial()
        print(f"Reset Response: {response}")

        if response['command'] == RESET_CMD and (response['data'] == [0x03, 0x00] or response['data'] == [0x00, 0x00]):
            print("Reset OK")
            return True
        else:
            print("Reset not OK")
            return False

    def aime_poll(self):
        if self.last_poll and (time.time() - self.last_poll) < 0.5:
            return False

        self.last_poll = time.time()

        self.send_command(UNK_1, FELICA_CMD, [0x00])
        resp = self.read_serial()
        print(f"FELICA Response: {resp}")
        if resp['command'] == FELICA_CMD and len(resp['data']) > 4:
            card_id = resp['data'][5:13]  # Original card ID bytes
            
            # Convert the card ID to a hex string
            card_id_str = ''.join(f'{b:02x}' for b in card_id)

            # Ensure the total length is exactly 20 characters
            if len(card_id_str) < 20:
                card_id_str = card_id_str + '0' * (20 - len(card_id_str))  # Pad with zeros as characters
            elif len(card_id_str) > 20:
                card_id_str = card_id_str[:20]  # Truncate to 20 characters

            # Save card ID to config
            self.save_card_to_config(card_id_str)

            print(f"Card Found! Card ID: {card_id_str}")
            self.send_led(0, 0, 0xff)
            time.sleep(5)
            return True

        self.send_command(UNK_1, UNK_CARD_CMD_2, [0x00])
        resp = self.read_serial()
        print(f"UNK_CARD_CMD_2 Response: {resp}")
        if resp['command'] == UNK_CARD_CMD_2 and len(resp['data']) > 4:
            print("Card Found!")
            self.send_led(0, 0, 0xff)
            time.sleep(1)
            return True

        self.send_command(UNK_1, UNK_CARD_CMD_1, [0x01, 0x03])
        resp = self.read_serial()
        print(f"UNK_CARD_CMD_1 Response: {resp}")
        if resp['command'] == UNK_CARD_CMD_1 and len(resp['data']) > 4:
            print("Card Found!")
            self.send_led(0, 0, 0xff)
            time.sleep(1)
            return True
        return False

    def save_card_to_config(self, card_id):
        try:
            # Open the JSON file to load settings
            with open("Data/System/JSON/config.json", "r") as file:
                settings = json.load(file)

            # Save the padded card ID into the config file
            settings["network"]["local_card"] = card_id

            # Write the updated settings back to the JSON file
            with open("Data/System/JSON/config.json", "w") as file:
                json.dump(settings, file, indent=4)
            print(f"Card ID saved: {card_id}")
            self.send_led(0, 0, 0xff)
            pyautogui.press('enter')
            time.sleep(5)
            pyautogui.press('enter')

        except Exception as e:
            print(f"Error saving card ID: {e}")

    def read_card(self):
        if not self.aime_poll():
            print("Card not found.")
            self.led_rainbow()
        else:
            self.read_card()

    def aime_task(self):
        self.serial_port = serial.Serial(self.com_port, baudrate=self.baudrate, timeout=3)
        if self.reader_init():
            self.led_test()
            while self.active:
                self.read_card()
        self.serial_port.close()

    def led_test(self):
        print("Red LEDs")
        self.send_led(0xff, 0, 0)
        time.sleep(1)
        print("Blue LEDs")
        self.send_led(0, 0xff, 0)
        time.sleep(1)
        print("Green LEDs")
        self.send_led(0, 0, 0xff)
        time.sleep(1)
        print("White LEDs")
        self.send_led(0xff, 0xff, 0xff)
        time.sleep(1)
        print("LEDs off")
        self.send_led(0, 0, 0)
        print("RAINBOW MODE!!!")

    def run(self):
        self.aime_task()


if __name__ == "__main__":
    aime_test = AimeTest(chusan=True)
    aime_test.run()
