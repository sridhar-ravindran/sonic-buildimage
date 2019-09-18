#!/usr/bin/env python

#############################################################################
# DELLEMC Z9100
#
# Module contains an implementation of SONiC Platform Base API and
# provides the platform information
#
#############################################################################

try:
    import os
    import subprocess
    import re
    from sonic_platform_base.chassis_base import ChassisBase
    from sonic_platform.sfp import Sfp
    from sonic_platform.fan import Fan
    from eeprom import Eeprom
except ImportError as e:
    raise ImportError(str(e) + "- required module not found")


MAX_Z9100_FANTRAY = 5
MAX_Z9100_FAN = 2
MAX_Z9100_PSU = 2

BIOS_QUERY_VERSION_COMMAND = "dmidecode -s system-version"
#components definitions
COMPONENT_BIOS = "BIOS"
SWITCH_CPLD1 = "CPLD1"
SWITCH_CPLD2 = "CPLD2"
SWITCH_CPLD3 = "CPLD3"
SWITCH_CPLD4 = "CPLD4"
SMF_FPGA = "FPGA1"


class Chassis(ChassisBase):
    """
    DELLEMC Platform-specific Chassis class
    """

    HWMON_DIR = "/sys/devices/platform/SMF.512/hwmon/"
    HWMON_NODE = os.listdir(HWMON_DIR)[0]
    MAILBOX_DIR = HWMON_DIR + HWMON_NODE
    EEPROM_I2C_MAPPING = {
        0: [9, 18], 1: [9, 19], 2: [9, 20], 3: [9, 21],
        4: [9, 22], 5: [9, 23], 6: [9, 24], 7: [9, 25],
        8: [8, 26], 9: [8, 27], 10: [8, 28], 11: [8, 29],
        12: [8, 31], 13: [8, 30], 14: [8, 33], 15: [8, 32],  # Remapped 4 entries
        16: [7, 34], 17: [7, 35], 18: [7, 36], 19: [7, 37],
        20: [7, 38], 21: [7, 39], 22: [7, 40], 23: [7, 41],
        24: [6, 42], 25: [6, 43], 26: [6, 44], 27: [6, 45],
        28: [6, 46], 29: [6, 47], 30: [6, 48], 31: [6, 49]
    }
    PORT_I2C_MAPPING = {
        # 0th Index = i2cLine, 1st Index = portIdx in i2cLine
        0: [14, 0], 1: [14, 1], 2: [14, 2], 3: [14, 3],
        4: [14, 4], 5: [14, 5], 6: [14, 6], 7: [14, 7],
        8: [14, 8], 9: [14, 9], 10: [14, 10], 11: [14, 11],
        12: [15, 0], 13: [15, 1], 14: [15, 2], 15: [15, 3],
        16: [15, 4], 17: [15, 5], 18: [15, 6], 19: [15, 7],
        20: [15, 8], 21: [15, 9], 22: [16, 0], 23: [16, 1],
        24: [16, 2], 25: [16, 3], 26: [16, 4], 27: [16, 5],
        28: [16, 6], 29: [16, 7], 30: [16, 8], 31: [16, 9]
    }

    reset_reason_dict = {}
    reset_reason_dict[11] = ChassisBase.REBOOT_CAUSE_POWER_LOSS
    reset_reason_dict[33] = ChassisBase.REBOOT_CAUSE_WATCHDOG
    reset_reason_dict[44] = ChassisBase.REBOOT_CAUSE_NON_HARDWARE
    reset_reason_dict[55] = ChassisBase.REBOOT_CAUSE_NON_HARDWARE

    power_reason_dict = {}
    power_reason_dict[11] = ChassisBase.REBOOT_CAUSE_POWER_LOSS
    power_reason_dict[22] = ChassisBase.REBOOT_CAUSE_THERMAL_OVERLOAD_CPU
    power_reason_dict[33] = ChassisBase.REBOOT_CAUSE_THERMAL_OVERLOAD_ASIC
    power_reason_dict[44] = ChassisBase.REBOOT_CAUSE_INSUFFICIENT_FAN_SPEED

    def __init__(self):
        PORT_START = 0
        PORT_END = 31
        PORTS_IN_BLOCK = (PORT_END + 1)

        # sfp.py will read eeprom contents and retrive the eeprom data.
        # It will also provide support sfp controls like reset and setting
        # low power mode.
        # We pass the eeprom path and sfp control path from chassis.py
        # So that sfp.py implementation can be generic to all platforms
        eeprom_base = "/sys/class/i2c-adapter/i2c-{0}/i2c-{1}/{1}-0050/eeprom"
        sfp_ctrl_base = "/sys/class/i2c-adapter/i2c-{0}/{0}-003e/"
        for index in range(0, PORTS_IN_BLOCK):
            eeprom_path = eeprom_base.format(self.EEPROM_I2C_MAPPING[index][0],
                                             self.EEPROM_I2C_MAPPING[index][1])
            sfp_control = sfp_ctrl_base.format(self.PORT_I2C_MAPPING[index][0])
            sfp_node = Sfp(index, 'QSFP', eeprom_path, sfp_control,
                           self.PORT_I2C_MAPPING[index][1])
            self._sfp_list.append(sfp_node)

        ChassisBase.__init__(self)
        # Initialize EEPROM
        self.sys_eeprom = Eeprom()
        for i in range(MAX_Z9100_FANTRAY):
            for j in range(MAX_Z9100_FAN):
                fan = Fan(i, j)
                self._fan_list.append(fan)

        # Initialize component list
        self._component_name_list.append(COMPONENT_BIOS)
        self._component_name_list.append(SWITCH_CPLD1)
        self._component_name_list.append(SWITCH_CPLD2)
        self._component_name_list.append(SWITCH_CPLD3)
        self._component_name_list.append(SWITCH_CPLD4)
        self._component_name_list.append(SMF_FPGA)

    def _get_pmc_register(self, reg_name):
        # On successful read, returns the value read from given
        # reg_name and on failure returns 'ERR'
        rv = 'ERR'
        mb_reg_file = self.MAILBOX_DIR + '/' + reg_name

        if (not os.path.isfile(mb_reg_file)):
            return rv

        try:
            with open(mb_reg_file, 'r') as fd:
                rv = fd.read()
        except Exception as error:
            rv = 'ERR'

        rv = rv.rstrip('\r\n')
        rv = rv.lstrip(" ")
        return rv

    def get_name(self):
        """
        Retrieves the name of the chassis
        Returns:
            string: The name of the chassis
        """
        return self.sys_eeprom.modelstr()

    def get_presence(self):
        """
        Retrieves the presence of the chassis
        Returns:
            bool: True if chassis is present, False if not
        """
        return True

    def get_model(self):
        """
        Retrieves the model number (or part number) of the chassis
        Returns:
            string: Model/part number of chassis
        """
        return self.sys_eeprom.part_number_str()

    def get_serial(self):
        """
        Retrieves the serial number of the chassis (Service tag)
        Returns:
            string: Serial number of chassis
        """
        return self.sys_eeprom.serial_str()

    def get_status(self):
        """
        Retrieves the operational status of the chassis
        Returns:
            bool: A boolean value, True if chassis is operating properly
            False if not
        """
        return True

    def get_base_mac(self):
        """
        Retrieves the base MAC address for the chassis

        Returns:
            A string containing the MAC address in the format
            'XX:XX:XX:XX:XX:XX'
        """
        return self.sys_eeprom.base_mac_addr()

    def get_serial_number(self):
        """
        Retrieves the hardware serial number for the chassis

        Returns:
            A string containing the hardware serial number for this chassis.
        """
        return self.sys_eeprom.serial_number_str()

    def get_reboot_cause(self):
        """
        Retrieves the cause of the previous reboot
        Returns:
            A tuple (string, string) where the first element is a string
            containing the cause of the previous reboot. This string must be
            one of the predefined strings in this class. If the first string
            is "REBOOT_CAUSE_HARDWARE_OTHER", the second string can be used
            to pass a description of the reboot cause.
        """
        reset_reason = int(self._get_pmc_register('smf_reset_reason'))
        power_reason = int(self._get_pmc_register('smf_poweron_reason'))

        # Reset_Reason = 11 ==> PowerLoss
        # So return the reboot reason from Last Power_Reason Dictionary
        # If Reset_Reason is not 11 return from Reset_Reason dictionary
        # Also check if power_reason, reset_reason are valid values by
        # checking key presence in dictionary else return
        # REBOOT_CAUSE_HARDWARE_OTHER as the Power_Reason and Reset_Reason
        # registers returned invalid data
        if (reset_reason == 11):
            if (power_reason in self.power_reason_dict):
                return (self.power_reason_dict[power_reason], None)
        else:
            if (reset_reason in self.reset_reason_dict):
                return (self.reset_reason_dict[reset_reason], None)

        return (ChassisBase.REBOOT_CAUSE_HARDWARE_OTHER, "Invalid Reason")

    def _get_command_result(self, cmdline):
        try:
            proc = subprocess.Popen(cmdline, stdout=subprocess.PIPE,
                                    shell=True, stderr=subprocess.STDOUT)
            stdout = proc.communicate()[0]
            proc.wait()
            result = stdout.rstrip('\n')
        except OSError:
            result = ''

        return result

    def _get_cpld_version(self,cpld_number):
        io_resource = "/dev/port"
        CPLD1_VERSION_ADDR = 0x100

        if (cpld_number == 1):
            fd = os.open(io_resource, os.O_RDONLY)
            if (fd < 0):
                return 'NA'
            if (os.lseek(fd, CPLD1_VERSION_ADDR, os.SEEK_SET)
                != CPLD1_VERSION_ADDR):
                return 'NA'

            buf = os.read(fd, 1)
            cpld_version = ord(buf)
            os.close(fd)

            return "%d.%d" % (((cpld_version & 0xF0) >> 4), cpld_version & 0xF)
        else:
            cpld_version_file = ("/sys/class/i2c-adapter/i2c-{0}/{0}-003e"
                                 "/iom_cpld_vers").format(12 + cpld_number)

            if (not os.path.isfile(cpld_version_file)):
                return 'NA'

            try:
                with open(cpld_version_file, 'r') as fd:
                    ver_str = fd.read()
            except Exception as error:
                return 'NA'

            if ver_str == "read error":
                return 'NA'
            else:
               ver_str = ver_str.rstrip("\r\n")
               cpld_version = int(ver_str.split(":")[1], 16)

            return "%d.%d" % (((cpld_version & 0xF0) >> 4), cpld_version & 0xF)

    def _get_fpga_version(self):
        fpga_ver = float(self._get_pmc_register('smf_firmware_ver'))
        return fpga_ver

    def get_firmware_version(self, component_name):
        """
        Retrieves platform-specific hardware/firmware versions for chassis
        componenets such as BIOS, CPLD, FPGA, etc.
        Args:
            component_name: A string, the component name.
        Returns:
            A string containing platform-specific component versions
        """
        if component_name in self._component_name_list :
            if component_name == COMPONENT_BIOS:
                return self._get_command_result(BIOS_QUERY_VERSION_COMMAND)
            elif component_name == SWITCH_CPLD1:
                return self._get_cpld_version(1)
            elif component_name == SWITCH_CPLD2:
                return self._get_cpld_version(2)
            elif component_name == SWITCH_CPLD3:
                return self._get_cpld_version(3)
            elif component_name == SWITCH_CPLD4:
                return self._get_cpld_version(4)
            elif component_name == SMF_FPGA:
                return self._get_fpga_version()

        return None
