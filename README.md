# MQTT connection state

This custom integration creates a diagnostic sensor for MQTT devices that shows the **MQTT connection state** of the device based on its MQTT availability or state topic.

> [!CAUTION]
> This integration is still in beta.

It automatically:

* Discovers MQTT devices
* Finds their availability topic
* Updates when device names or topics change
* Raises a Repair issue when the device becomes orphaned

## Features

### 🔍 Automatic Discovery

* Periodically scans the device registry for MQTT devices with an availability or status topic
* If multiple topics are found, the last found topic is used

### 🚨 Orphan Detection & Repairs

* If the connection sensor loses its parent (e.g. device drop off), a **Home Assistant Repair issue** is raised.
* When the parent is rediscovered, the issue is closed.
* Or easily delete the connection sensor from the issue.

### 🧩 Entity Behavior

The device gets one entity: `binary_sensor.<device_name>_connection_state`

* Displayed names can be translated, currently EN and NL are available.

## Installation

### HACS

* Go to the HACS dashboard (/hacs/dashboard) and select the three dots in the top right corner. Select *Custom repositories*.
* In repository fill:

```
https://github.com/studioIngrid/mqtt_connection_state
```

Type: `integration`

* Click *Add*, and close the popup.
* Then search for:

```
MQTT connection state
```

* Click `Download` in the bottom right.
* Restart Home Assistant.
* Go to *Settings* > *Devices & Services* > *Integrations*
* You have to manually add the first device. Click *Add integration* > Search for *MQTT connection state* > *Select a device*.
* Within the first 10 minutes you should see the discovered devices on your network, for easy configuration.

### Manual

* Download the contents of this repository.
* Add the respective folder to your config in `config/custom_components/mqtt_connection_state`.
* Restart Home Assistant.
* You have to manually add the first device. Click *Add integration* > Search for *MQTT connection state* > *Select a device*.
* Within the first 10 minutes you should see the discovered devices on your network, for easy configuration.
