from lib.I_intent_receiver import Receiver, Reply

class Zigbee(Receiver):

    def receive_intent(self, intent, settings):

        if intent.intent == "ChangeLightState":
            sources = [intent.slots["source"]]
            reply_topic = []
            reply_payload = []
            mode = intent.slots.get("mode","default")
            if intent.slots["source"] in settings["ReceiverGroups"]:
                sources = settings["ReceiverGroups"][intent.slots["source"]]
            for source in sources:
                reply_topic.append('z2mq/' + source + '/set')
                reply_payload.append('{"state":"' + intent.slots["state"] + '",' + settings["ReceiverProperties"][source][mode] + '}')
        
        override_state = True
        if intent.intent == "VRMode":
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set','z2mq/socketvive/set','z2mq/socketlh1/set','z2mq/socketlh2/set']
            reply_payload = ['{"state":"off"}','{"state":"on","brightness":100,"color_mode":"xy","color":{"x":0.1459,"y":0.2382}}','{"state":"on"}','{"state":"on"}','{"state":"on"}']
            override_state = False
        if intent.intent == "CineMode":
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set']
            reply_payload = ['{"state":"on",' + settings["ReceiverProperties"]["couchlamp"]["min"] + '}','{"state":"off"}']
            override_state = False
        if intent.intent == "RLMode":
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set','z2mq/socketvive/set','z2mq/socketlh1/set','z2mq/socketlh2/set']
            reply_payload = ['<restore>','<restore>','{"state":"off"}','{"state":"off"}','{"state":"off"}']
            
        return Reply(glados_path='command_success', mqtt_topic= reply_topic, mqtt_payload= reply_payload, override_state= override_state)
