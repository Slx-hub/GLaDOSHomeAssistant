from lib.I_intent_receiver import Receiver, Reply

class Zigbee(Receiver):

    def receive_intent(self, intent, settings):
        request_delay = 0.0
        is_user_override = False

        if intent.intent == "ChangeSocketState":
            reply_topic = ['z2mq/' + intent.slots["source"] + '/set']
            reply_payload = ['{"state":"' + intent.slots["state"] + '"}']

        if intent.intent == "ResetSocket":
            request_delay = 5.0
            reply_topic = ['z2mq/' + intent.slots["source"] + '/set', 'z2mq/' + intent.slots["source"] + '/set']
            reply_payload = ['{"state":"off"}', '{"state":"on"}']

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
        
        if intent.intent == "VRMode":
            is_user_override = True
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set','z2mq/socketvive/set','z2mq/socketlh1/set','z2mq/socketlh2/set']
            reply_payload = ['{"state":"off"}','{"state":"on","brightness":2,"color_mode":"xy","color":{"x":0.1459,"y":0.2382}}','{"state":"on"}','{"state":"on"}','{"state":"on"}']
        if intent.intent == "CineMode":
            is_user_override = True
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set']
            reply_payload = ['{"state":"on",' + settings["ReceiverProperties"]["couchlamp"]["min"] + '}','{"state":"off"}']
        if intent.intent == "StealthMode":
            is_user_override = True
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set']
            reply_payload = ['{"state":"off"}','{"state":"off"}']
        if intent.intent == "RLMode":
            reply_topic = ['z2mq/couchlamp/set','z2mq/showcase/set','z2mq/socketvive/set','z2mq/socketlh1/set','z2mq/socketlh2/set']
            reply_payload = ['<release-override>','<release-override>','{"state":"off"}','{"state":"off"}','{"state":"off"}']
            
        return Reply(glados_path=Receiver.get_reply_from_settings(intent, settings), mqtt_topic= reply_topic, mqtt_payload= reply_payload, is_user_override= is_user_override, mqtt_request_delay= request_delay)
