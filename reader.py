import serial
import time
import json
import pyautogui
from datetime import datetime
from threading import Thread
import configparser


class AimeTestWindow:
    AIME_ESCAPE = 0xd0
    RESET_CMD = 0x62
    LED_CMD = 0x81
    FELICA_CMD = 0x42
    UNK_CARD_CMD_1 = 0x40
    UNK_CARD_CMD_2 = 0x42
    UNK_1 = 0x00
    UNK_2 = 0x08

    def __init__(self, chusan, config_file="settings.ini"):
        self.serial_port = None
        self.active = True
        self._seq = 0
        self.curr_col = 0
        self.rainbow_dir = True
        self._chusan = chusan
        self.last_poll = datetime.now()

        
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.com_port = self.config.get("SerialSettings", "COMPort", fallback="COM4")
        self.baud_rate = self.config.getint("SerialSettings", "BaudRate", fallback=38400)

    @property
    def seqnum(self):
        return self._seq

    @seqnum.setter
    def seqnum(self, value):
        self._seq = value % 0x100

    def checksum(self, command):
        chksm = command['length'] + command['unk'] + command['seqnum'] + command['command']
        chksm += sum(command['data'])
        return chksm & 0xFF

    def read_serial(self):
        while True:
            sync = self.read_byte()
            if sync == 0xE0:
                break
        command = {
            'sync': sync,
            'length': self.read_byte(),
            'unk': self.read_byte(),
            'seqnum': self.read_byte(),
            'command': self.read_byte(),
            'data': [],
            'checksum': 0
        }
        command['data'] = [self.read_byte() for _ in range(command['length'] - 4)]
        command['checksum'] = self.read_byte()
        self.seqnum = command['seqnum']
        return command

    def read_byte(self):
        try:
            byte = self.serial_port.read(1)
            if not byte:  
                raise TimeoutError("Serial read timed out.")
            byte = byte[0]
            if byte == self.AIME_ESCAPE:
                byte = self.serial_port.read(1)[0] + 1
            return byte
        except IndexError:
            print("IndexError: Received no data.")
            raise 

    def write_escaped_byte(self, byte):
        if byte in [self.AIME_ESCAPE, 0xE0]:
            self.serial_port.write(bytes([self.AIME_ESCAPE, byte - 1]))
        else:
            self.serial_port.write(bytes([byte]))

    def send_command(self, unk, command_byte, data):
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



    def send_led(self, red, green, blue):
        data = [0x03, red, blue, green]
        self.send_command(self.UNK_2, self.LED_CMD, data)

    def aime_task(self):
        while self.active:
            try:
                self.serial_port = serial.Serial()
                self.serial_port.port = self.com_port
                self.serial_port.baudrate = self.baud_rate
                self.serial_port.timeout = 3
                self.serial_port.open()

                if self.reader_init():
                    self.last_poll = datetime.now()
                    while self.active:
                        self.read_card()
            except (TimeoutError, IndexError) as e:
                print(f"Error occurred: {e}. Resetting the reader...")
                time.sleep(1)  
                continue 
            except serial.SerialException as e:
                print(f"Serial port error: {e}. Check connection.")
                break  
            finally:
                if self.serial_port.is_open:
                    self.serial_port.close()

    def reader_init(self):
        self.send_command(self.UNK_1, self.RESET_CMD, [0x00])
        response = self.read_serial()

        if response['command'] == self.RESET_CMD and (
                response['data'] == [0x03, 0x00] or response['data'] == [0x00, 0x00]):
            print("Reset OK")
            return True
        else:
            print("Reset not OK")
            return False
   


    def read_card(self):
        if (datetime.now() - self.last_poll).total_seconds() * 1000 < 500:
            return

        self.last_poll = datetime.now()
        self.send_command(self.UNK_1, self.FELICA_CMD, [0x00])
        response = self.read_serial()

        if response['command'] == self.FELICA_CMD and len(response['data']) > 4:
            card_id = response['data'][5:13]
            card_str = ''.join(f"{byte:02X}" for byte in card_id)
            print(f"Card Found! Card ID: {card_str}")
            
           
            if len(card_str) < 20:
                card_str = card_str + '0' * (20 - len(card_str))
            
           
            self.save_card_to_config(card_str)
            
           
            self.send_led(0, 0, 0xFF)
            time.sleep(0.4)
            self.send_led(0xff, 0, 0)
            time.sleep(0.4)
            pyautogui.press('enter')
        else:
            self.send_led(0,0xFF , 0)

            


    def save_card_to_config(self, card_id):
        try:
          
            with open("Data/System/JSON/config.json", "r") as file:
                settings = json.load(file)

            
            settings["network"]["local_card"] = card_id

           
            with open("Data/System/JSON/config.json", "w") as file:
                json.dump(settings, file, indent=4)
            print(f"Card ID saved: {card_id}")

        except Exception as e:
            print(f"Error saving card ID: {e}")

if __name__ == "__main__":
    window = AimeTestWindow(chusan=True)
    thread = Thread(target=window.aime_task)
    thread.start()
