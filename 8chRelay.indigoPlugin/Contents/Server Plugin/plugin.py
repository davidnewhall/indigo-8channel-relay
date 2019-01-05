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

    def validateDeviceConfigUi(self, values, type_id, did):
        """ Validate the config for each sub device is ok. Set address prop. """
        errors = indigo.Dict()
        dev = indigo.devices[did]
        props = dev.pluginProps
        if type_id != "Sprinkler":
            try:
                channel = int(values["channel"])
            except:
                channel = 0
            prefix = "r" if type_id == "Relay" else "i"
        elif type_id == "Sprinkler":
            prefix = "s"
            channel = ""  # Add all channels here.
            zone_names = ""
            for zone in range(1, int(props["NumZones"])+1):
                if channel != "":
                    channel += ","
                channel += values["zoneRelay"+str(zone)]
                if values["zoneName"+str(zone)] == "":
                    errors["zoneName"+str(zone)] = u"Zone name must not be empty!"
                    return (False, values, errors)
                elif "," in values["zoneName"+str(zone)]:
                    errors["zoneName"+str(zone)] = u"Zone name must not contain a comma!"
                    return (False, values, errors)
                if zone_names != "":
                    zone_names += ","
                zone_names += values["zoneName"+str(zone)]
            values["ZoneNames"] = zone_names
        values["address"] = u"{} {}{}".format(props.get("hostname", values["address"]), prefix, channel)
        dev.replacePluginPropsOnServer(props)
        return (True, values)


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
            values["NumZones"] = dev.pluginProps.get("NumZones", 1)
            values["PumpControlOn"] = dev.pluginProps.get("PumpControlOn", False)
        if len(dev_id_list) == 1 and indigo.devices[dev_id_list[0]].deviceTypeId == "Sprinkler":
            values["irrigationController"] = True
        return (values, errors)

    def closedDeviceFactoryUi(self, values, cancelled, dev_id_list):
        """ Save the DeviceFactory properties to each sub device. """
        if cancelled is True:
            if "createdDevices" in values and values["createdDevices"] != "":
                for did in values["createdDevices"].split(","):
                    indigo.device.delete(indigo.devices[int(did)])
                    dev_id_list.remove(int(did))
        else:
            ic = values.get("irrigationController", False)
            # Do not delete the only sprinkler device.
            try:
                first_device = indigo.devices[dev_id_list[0]].deviceTypeId
            except:
                first_device = "none"
            if ((ic is False or (ic is True and (len(dev_id_list) > 1 or first_device != "Sprinkler"))) and
                    "removedDevices" in values and values["removedDevices"] != ""):
                for did in values["removedDevices"].split(","):
                    dev = indigo.devices[int(did)]
                    indigo.device.delete(dev)
                    if did not in values["createdDevices"].split(","):
                        # do not log if the device was added/removed in one shot.
                        indigo.server.log(u"Deleted Device: {}".format(dev.name))
                    dev_id_list.remove(int(did))
        if values.get("irrigationController", False) is True and len(dev_id_list) < 1:
            dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Sprinkler")
            dev.model = u"8 Channel Network Relay Board"
            dev.subModel = u"Irrigation"
            dev.replaceOnServer()
            dev_id_list.append(dev.id)
        for did in dev_id_list:
            dev = indigo.devices[did]
            props = dev.pluginProps
            channel = props.get("channel", 0)
            prefix = "r" if dev.deviceTypeId == "Relay" else "i"
            if dev.deviceTypeId == "Sprinkler":
                prefix = "s"
                channel = ""
                for zone in range(1, int(props["NumZones"])+1):
                    if channel != "":
                        channel += ","
                    channel += props.get("zoneRelay"+str(zone), 0)
                props["irrigationController"] = True
            props["hostname"] = values.get("address", props.get("hostname", ""))
            props["port"] = values.get("port", props.get("port", "1234"))
            props["NumZones"] = values.get("NumZones", props.get("NumZones", "1"))
            props["PumpControlOn"] = values.get("PumpControlOn", props.get("PumpControlOn", False))
            props["address"] = u"{} {}{}".format(props["hostname"], prefix, channel)
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
                self.sleep(int(indigo.activePlugin.pluginPrefs.get("interval", 15)))
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
                if dev.pluginProps.get("logActions", True):
                    indigo.server.log(u"Sent \"{}\" on".format(dev.name))
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            try:
                self.send_cmd(dev.pluginProps, u"D")
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer(u"Error turning off relay device: {}".format(err))
            except KeyError:
                dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
            else:
                dev.updateStateOnServer("onOffState", False)
                if dev.pluginProps.get("logActions", True):
                    indigo.server.log(u"Sent \"{}\" off".format(dev.name))
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            command, reply, state = (u"L", "on", True)
            if dev.states["onOffState"]:
                command, reply, state = (u"D", "off", False)
            try:
                self.send_cmd(dev.pluginProps, command)
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer("Error toggling relay device: {}".format(err))
            except KeyError:
                dev.setErrorStateOnServer(u"Relay Channel Missing! Configure Device Settings.")
            else:
                dev.updateStateOnServer("onOffState", state)
                if dev.pluginProps.get("logActions", True):
                    indigo.server.log(u"Sent \"{}\" {}".format(dev.name, reply))

    def actionControlSprinkler(self, action, dev):
        """ Control sprinklers! """
        az = 0
        for zone in range(1, int(dev.pluginProps["NumZones"])+1):
            try:
                zone_info = {
                    "hostname": dev.pluginProps["hostname"],
                    "channel": dev.pluginProps["zoneRelay"+str(zone)],
                    "port": dev.pluginProps["port"],
                }
                cmd, reply, name = u"D", "off", dev.zoneNames[zone - 1]
                if action.sprinklerAction == indigo.kSprinklerAction.ZoneOn:
                    if zone == action.zoneIndex:
                        cmd, reply, az = u"L", "on", zone
                    if zone == int(dev.pluginProps["NumZones"]) and dev.pluginProps["PumpControlOn"] is True:
                        # Turn on the pump too.
                        cmd, reply = u"L", "on"
                self.send_cmd(zone_info, cmd)
            except (socket.error, EOFError) as err:
                dev.setErrorStateOnServer(u"Error turning {} sprinkler relay zone {} {}: {}"
                                          .format(reply, zone, name, err))
                return
            except KeyError:
                dev.setErrorStateOnServer(u"Sprinkler relay channel missing for zone {} {}! Configure device settings."
                                          .format(zone, name))
                continue
            if dev.pluginProps.get("logActions", True):
                indigo.server.log(u"Sent \"{} - {}\" {}".format(dev.name, name, reply))
        dev.updateStateOnServer("activeZone", az)

    def _change_factory_device_type(self, values, dev_id_list):
        """ Devices.xml Callback Method to make sure changing the factory device type is safe. """
        rem_devs = values["removedDevices"].split(",")
        if rem_devs[0] == "":
            rem_devs = []
        if values["irrigationController"] is True and len(dev_id_list)-len(rem_devs) > 0:
            # All devices must be removed first.
            values["irrigationController"] = False
        elif values["irrigationController"] is False:
            for did in dev_id_list:
                dev = indigo.devices[did]
                if dev.deviceTypeId == "Sprinkler":
                    if values["removedDevices"] != "":
                        values["removedDevices"] += ","
                    values["removedDevices"] += str(did)
        values["deviceGroupList"] = [v for v in dev_id_list if v not in values["removedDevices"].split(",")]
        return values

    def _get_device_list(self, filter, values, dev_id_list):
        """ Devices.xml Callback Method to return all sub devices. """
        return_list = list()
        for did in dev_id_list:
            name = indigo.devices[did].name if did in indigo.devices else u"- device missing -"
            if str(did) not in values.get("removedDevices", "").split(","):
                return_list.append((did, name))
        return return_list

    def _add_sensor(self, values, dev_id_list):
        """ Devices.xml Callback Method to add a new Relay sub-device. """
        if len(dev_id_list)-len(values["removedDevices"].split(",")) >= 8:
            return values
        dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Sensor")
        dev.model = u"8 Channel Network Relay Board"
        dev.subModel = u"Input"
        dev.replaceOnServer()
        values["createdDevices"] += ","+str(dev.id) if values["createdDevices"] != "" else str(dev.id)
        return values

    def _add_relay(self, values, dev_id_list):
        """ Devices.xml Callback Method to add a new Relay sub-device. """
        if len(dev_id_list)-len(values["removedDevices"].split(",")) >= 8:
            return values
        dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Relay")
        dev.model = u"8 Channel Network Relay Board"
        dev.subModel = u"Relay"
        dev.replaceOnServer()
        values["createdDevices"] += ","+str(dev.id) if values["createdDevices"] != "" else str(dev.id)
        return values

    def _add_sprinkler(self, values, dev_id_list):
        """ Devices.xml Callback Method to add a new Sprinkler sub-device. """
        dev = indigo.device.create(indigo.kProtocol.Plugin, deviceTypeId="Sprinkler")
        dev.model = u"8 Channel Network Relay Board"
        dev.subModel = u"Irrigation"
        dev.replaceOnServer()
        values["createdDevices"] += ","+str(dev.id) if values["createdDevices"] != "" else str(dev.id)
        return values

    def _remove_devices(self, values, dev_id_list):
        """ Devices.xml Callback Method to remove devices. """
        for did in dev_id_list:
            if str(did) in values["deviceGroupList"]:
                dev = indigo.devices[did]
                values["removedDevices"] += ","+str(dev.id) if values["removedDevices"] else str(dev.id)
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
            if dev.pluginProps.get("logActions", True):
                indigo.server.log(u"Sent \"{}\" relay pulse".format(dev.name))
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
        hosts = list()
        # Build two lists: host/port combos, and (sub)devices.
        for dev in indigo.devices.iter("self"):
            if (dev.enabled and dev.configured and "hostname" in dev.pluginProps
                    and "port" in dev.pluginProps):
                # Make a list of the plugin"s devices and a set of their hostnames.
                hosts.append((dev.pluginProps["hostname"], dev.pluginProps["port"]))
                devs.append(dev)

        # Loop each unique host/port combo and poll it for status, then update its devices.
        for host, port in set(hosts):
            timeout = int(indigo.activePlugin.pluginPrefs.get("timeout", 4))
            try:
                relay = Telnet(host, int(port), timeout)
                relay.write("DUMP\r\n")
                statuses = relay.read_until("OK", timeout).upper()
                relay.close()
            except (socket.error, EOFError, UnicodeError) as err:
                for dev in devs:
                    # Update all the sub devices that failed to get queried.
                    if (dev.pluginProps["hostname"], dev.pluginProps["port"]) == (host, port):
                        dev.setErrorStateOnServer(u"Relay Communication Error: {} ({}:{}/{})"
                                                  .format(err, host, port, timeout))
                return

            # Update all the devices that belong to this hostname/port.
            for dev in devs:
                chan = dev.pluginProps.get("channel", -1)
                if (dev.pluginProps["hostname"], dev.pluginProps["port"]) != (host, port):
                    # Device does not match, carry on.
                    continue
                if dev.deviceTypeId == "Relay":
                    state = True if statuses.find("RELAYON {}".format(chan)) != -1 else False
                elif dev.deviceTypeId == "Sensor":
                    state = True if statuses.find("IH {}".format(chan)) != -1 else False
                if dev.deviceTypeId != "Sprinkler":
                    if dev.pluginProps.get("logChanges", True):
                        if dev.states["onOffState"] != state:
                            reply = "on" if state else "off"
                            indigo.server.log(u"Device \"{}\" turned {}"
                                              .format(dev.name, reply))
                    dev.updateStateOnServer("onOffState", state)
                    continue

                # Check if a sprinkler zone turned on or off unexpectedly!
                active_zone, now_active = int(dev.states["activeZone"]), 0
                for zone in range(1, int(dev.pluginProps["NumZones"])+1):
                    try:
                        chan = dev.pluginProps["zoneRelay"+str(zone)]
                        name = dev.zoneNames[zone - 1]
                    except KeyError:
                        continue
                    # match the relay to a zone and update state & log
                    state = True if statuses.find("RELAYON {}".format(chan)) != -1 else False
                    if (int(active_zone) != zone and state is True and
                            (dev.pluginProps["PumpControlOn"] is False
                             or zone != int(dev.pluginProps["NumZones"]))):
                        indigo.server.log(u"Zone \"{} - {}\" unexpectedly turned on"
                                          .format(dev.name, name))
                        now_active = zone
                    if (int(active_zone) == zone and state is False or
                            (dev.pluginProps["PumpControlOn"] is True
                             and zone == int(dev.pluginProps["NumZones"])
                             and active_zone != 0)):
                        indigo.server.log(u"Zone \"{} - {}\" unexpectedly turned off"
                                          .format(dev.name, name))
                dev.updateStateOnServer("activeZone", now_active)


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
