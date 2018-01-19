""" 8 Channel Network Relay Plugin for Indigo.
    First Release Date: Jan 16, 2018
    Author: David Newhall II
    License: GPLv2
"""

from datetime import datetime
from telnetlib import Telnet
import socket
import indigo


class Plugin(indigo.PluginBase):
    """ Indigo Plugin """

    def __init__(self, pid, name, version, prefs):
        """ Initialize Plugin. """
        indigo.PluginBase.__init__(self, pid, name, version, prefs)
        self.debug = False

    def validatePrefsConfigUi(self, values):
        """ Callback method to validate global plugin configuration. """
        errors = indigo.Dict()
        try:
            timeout = int(values["timeout"])
            if timeout < 1 or timeout > 15:
                errors["timeout"] = u"Timeout must be between 1 and 15 seconds."
                timeout = 4
        except ValueError:
            errors["timeout"] = u"Timeout must be a number between 1 and 15 seconds."
            timeout = 4
        try:
            interval = int(values["interval"])
            if interval < 2 or interval > 120:
                errors["interval"] = u"Update Interval must be between 2 seconds and 2 minutes."
                interval = 15
        except ValueError:
            errors["interval"] = u"Update Interval must be a number between 2 seconds and 2 minutes."
            interval = 15
        return (False if errors else True, values, errors)

    def validateDeviceConfigUi(self, values, type_id, did):
        """ Validate the config for each sub device is ok. Set address prop. """
        errors = indigo.Dict()
        try:
            channel = int(values["channel"])
            if channel < 1 or channel > 8:
                errors["channel"] = u"Channel must be between 1 and 8."
        except ValueError:
            errors["channel"] = u"Channel must be a number between 1 and 8."
        else:
            prefix = "r" if type_id == "Relay" else "i"
            values["channel"] = channel
            dev = indigo.devices[did]
            props = dev.pluginProps
            values["address"] = u"{}{}:{}:{}".format(prefix, channel, props["hostname"], props["port"])
            props["address"] = values["address"]
            dev.replacePluginPropsOnServer(props)
        return (False if errors else True, values, errors)

    def getDeviceFactoryUiValues(self, dev_id_list):
        """ Called when the device factory config UI is first opened.
        Used to populate the dialog with values from device 0. """
        values = indigo.Dict()
        errors = indigo.Dict()
        # Retrieve parameters stored in device 0"s props.
        if dev_id_list:
            dev = indigo.devices[dev_id_list[0]]
            values["address"] = dev.pluginProps.get("hostname", u"192.168.1.166")
            values["port"] = dev.pluginProps.get("port", 1234)
        return (values, errors)

    def validateDeviceFactoryUi(self, values, dev_id_list):
        """ Check Connection to Relay Board and sanitize user input. """
        errors = indigo.Dict()
        try:
            port = int(values["port"])
            if port < 1 or port > 65534:
                errors["port"] = u"Port must be between 1 and 65534."
                port = 1234
        except ValueError:
            errors["port"] = u"Port must be a number between 1 and 65534."
            port = 1234
        values["port"] = port
        return (False if errors else True, values, errors)

    def closedDeviceFactoryUi(self, values, cancelled, dev_id_list):
        """ Save the DeviceFactory properties to each sub device. """
        for did in dev_id_list:
            dev = indigo.devices[did]
            props = dev.pluginProps
            prefix = "r" if dev.deviceTypeId == "Relay" else "i"
            props["hostname"] = values["address"]
            props["port"] = values["port"]
            props["address"] = u"{}{}:{}:{}".format(prefix, props.get("channel", "undef"),
                                                    props["hostname"], props["port"])
            dev.replacePluginPropsOnServer(props)
        self.set_device_states()
        return values

    def runConcurrentThread(self):
        """ Method called by Indigo to poll the relay board(s).
        This is required because the board has no way to send an update to Indigo.
        If the input sensors are tripped we have to poll to get that state change.
        """
        try:
            while True:
                self.set_device_states()
                self.sleep(indigo.activePlugin.pluginPrefs.get("interval", 15))
        except self.StopThread:
            pass

    def actionControlUniversal(self, action, dev):
        """ Contral Misc. Actions here, like requesting a status update. """
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.set_device_states()

    def actionControlDevice(self, action, dev):
        """ Callback Method to Control a Relay Device. """
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            try:
                self.send_cmd(dev.pluginProps, u"L")
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer(u"Error turning on relay device: {}".format(err))
            except KeyError:
                dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
            else:
                dev.updateStateOnServer("onOffState", True)
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            try:
                self.send_cmd(dev.pluginProps, u"D")
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer(u"Error turning off relay device: {}".format(err))
            except KeyError:
                dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
            else:
                dev.updateStateOnServer("onOffState", False)
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            try:
                self.send_cmd(dev.pluginProps, u"L" if dev.states["onOffState"] else u"D")
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer("Error toggling relay device: {}".format(err))
            except KeyError:
                dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
            else:
                dev.updateStateOnServer("onOffState", False if dev.states["onOffState"] else True)

    def _get_device_list(self, filter, values, dev_id_list):
        """ Devices.xml Callback Method to return all sub devices. """
        devices = list()
        for did in dev_id_list:
            name = u"- device missing -"
            if did in indigo.devices:
                name = indigo.devices[did].name
            devices.append((did, name))
        return devices

    def _add_sensor(self, values, dev_id_list):
        """ Devices.xml Callback Method to add a new Relay sub-device. """
        if len(dev_id_list) >= 8:
            return values
        dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Sensor")
        dev.model = u"8 Channel Network Relay Board"
        dev.subModel = u"Input"
        dev.replaceOnServer()
        return values

    def _add_relay(self, values, dev_id_list):
        """ Devices.xml Callback Method to add a new Relay sub-device. """
        if len(dev_id_list) >= 8:
            return values
        dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Relay")
        dev.model = u"8 Channel Network Relay Board"
        dev.subModel = u"Relay"
        dev.replaceOnServer()
        return values

    def _remove_input_sensors(self, values, dev_id_list):
        """ Devices.xml Callback Method to remove all input sensors. """
        for did in dev_id_list:
            try:
                dev = indigo.devices[did]
                if dev.deviceTypeId == "Sensor":
                    indigo.device.delete(dev)
            except:
                pass
        return values

    def _remove_relay_devices(self, values, dev_id_list):
        """ Devices.xml Callback Method to remove all sub devices. """
        for did in dev_id_list:
            try:
                dev = indigo.devices[did]
                if dev.deviceTypeId == "Relay":
                    indigo.device.delete(dev)
            except:
                pass
        return values

    def _remove_all_devices(self, values, dev_id_list):
        """ Devices.xml Callback Method to remove all sub devices. """
        for did in dev_id_list:
            try:
                indigo.device.delete(did)
            except:
                pass
        return values

    def _pulse_relay(self, action, dev):
        """ Actions.xml Callback Method to pulse a relay. """
        try:
            self.send_cmd(dev.pluginProps, u"P")
        except (socket.error, EOFError) as err:
            dev.setErrorStateOnServer("Error Pulsing Relay: {}".format(err))
        except KeyError:
            dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
        else:
            dev.updateStateOnServer("pulseCount", dev.states.get("pulseCount", 0) + 1)
            dev.updateStateOnServer("pulseTimestamp", datetime.now().strftime("%s"))
            dev.updateStateOnServer("onOffState", False)  # Pulse always turns off.

    def _reset_pulse_count(self, action, dev):
        """ Set the pulse count for a device back to zero. """
        dev.updateStateOnServer("pulseCount", 0)

    def _reset_device_pulse_count(self, values, type_id, did):
        """ Set the pulse count for a device back to zero. """
        indigo.devices[did].updateStateOnServer("pulseCount", 0)

    @staticmethod
    def set_device_states():
        """ Updates Indigo with current devices" states. """
        devs = list()
        addrs = list()
        for dev in indigo.devices.iter("self"):
            if (dev.enabled and dev.configured and "hostname" in dev.pluginProps
                    and "port" in dev.pluginProps):
                # Make a list of the plugin"s devices and a set of their hostnames.
                addrs.append((dev.pluginProps["hostname"], dev.pluginProps["port"]))
                devs.append(dev)
        for addr, port in addrs:
            timeout = int(indigo.activePlugin.pluginPrefs.get("timeout", 4))
            try:
                relay = Telnet(addr, int(port), timeout)
                relay.write("DUMP\r\n")
                statuses = relay.read_until("OK", timeout)
                relay.close()
            except (socket.error, EOFError) as err:
                for dev in devs:
                    # Update all the sub devices that failed to get queried.
                    if dev.pluginProps["hostname"] == addr and dev.pluginProps["port"] == port:
                        dev.setErrorStateOnServer(u"Error polling relay device: {}".format(err))
                return
            for dev in devs:
                chan = dev.pluginProps.get("channel", -1)
                if dev.pluginProps["hostname"] != addr or dev.pluginProps["port"] != port:
                    continue
                # Update all the devices that belong to this hostname.
                elif dev.deviceTypeId == "Relay":
                    state = True if statuses.find("Relayon {}".format(chan)) != -1 else False
                    dev.updateStateOnServer("onOffState", state)
                elif dev.deviceTypeId == "Sensor":
                    state = True if statuses.find("IH {}".format(chan)) != -1 else False
                    dev.updateStateOnServer("onOffState", state)

    @staticmethod
    def send_cmd(values, cmd):
        """ Sends a simple command to the relay board. """
        timeout = indigo.activePlugin.pluginPrefs.get("timeout", 4)
        try:
            relay = Telnet(values["hostname"], int(values["port"]), int(timeout))
            relay.write("{}{}\r\n".format(cmd, values["channel"]))
            relay.close()
        except (socket.error, EOFError) as err:
            indigo.server.log(u"Relay Communication Error: {} ({}:{}/{})"
                              .format(err, values["hostname"], values["port"], timeout))
            raise
