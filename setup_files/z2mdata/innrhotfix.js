const fz = require('zigbee-herdsman-converters/converters/fromZigbee');
const tz = require('zigbee-herdsman-converters/converters/toZigbee');
const exposes = require('zigbee-herdsman-converters/lib/exposes');
const reporting = require('zigbee-herdsman-converters/lib/reporting');
const legacy = require('zigbee-herdsman-converters/lib/legacy');
const extend = require('zigbee-herdsman-converters/lib/extend');
const ota = require('zigbee-herdsman-converters/lib/ota');
const tuya = require('zigbee-herdsman-converters/lib/tuya');
const utils = require('zigbee-herdsman-converters/lib/utils');
const globalStore = require('zigbee-herdsman-converters/lib/store');
const e = exposes.presets;
const ea = exposes.access;

const definition = {
    zigbeeModel: ['RB 266'],
    model: 'RB 266',
    vendor: 'Innr',
    description: 'steaming hot pile of crap',
    extend: extend.light_onoff_brightness(),
    meta: {turnsOffAtBrightness1: true},
    ota: ota.zigbeeOTA,
    endpoint: (device) => {
        return {default: 1};
    },
};

module.exports = definition;
