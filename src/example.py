# -*- coding: utf-8 -*-

#################Network Settings#################
SIM_DETECTION_MODE = 1  # (0-2)0-"SIM Not Inserted", 1-"SIM Inserted", 2- Automatic sim detection
SIM_PIN = ''
GPRS_APN = 'm2m.LL.com'
GPRS_USERID = ''
GPRS_PASSW = ''
#################Firewall Settings#################
# By default fire wall blocks all incomming connections. Add unblock rules here.
# To enable address 197.158.1.1 to 197.158.255.255 use ["197.158.1.1","255.255.0.0"]
# To enable  address "197.158.1.1" use "197.158.1.1","255.255.255.255"
FIRE_WALL_ADDRESS = []
# FIRE_WALL_ADDRESS.append(['197.158.1.1','255.255.255.255'])
# FIRE_WALL_ADDRESS.append(['197.158.1.1','255.255.0.0'])
#################NTP settings for ioeye######################
NTP_SERVER = 'ntp.ioeye.com'  # leave '' for disabling NTP
NTP_PORT = 123  # default port 123

tries = 3  # Try three times to start then disable python script.
while(tries > 0):
    try:
        tries = tries - 1
        import sys
        import MDM
        import SER
        import MOD
        import config
        import instamsg
    except:
        try:
            if(tries == 0):
                # Create __error log for trouble shooting.
                error = ('ioEYE:: Fatal __error.%s %s\r\n' % (str(sys.exc_info()[0]), str(sys.exc_info()[1])))       
                f = open('__error.log', 'wb')
                error = error + 'ioEYE:: Disabling python script...\r\n'
                f.write(error)
                MDM.send('AT#ESCRIPT=""' + '\r', 5)
        finally:
            if(tries == 0):
                f.close()
                sys.exit()

def start(args):
    instaMsg = None
    try:
        try:
            options = {'logLevel':instamsg.INSTAMSG_LOG_LEVEL_DEBUG}
            clientId = "d06f5d10-8091-11e4-bd82-543530e3bc65"
            authKey = "afdlkjghfdjglkjo-094-09k"
            modemSettings = {
                  'sim_detection_mode':SIM_DETECTION_MODE,
                  'sim_pin':SIM_PIN,
                  'gprs_apn':GPRS_APN,
                  'gprs_userid':GPRS_USERID,
                  'gprs_pswd':GPRS_PASSW,
                  'firewall_addresses': FIRE_WALL_ADDRESS,
                  'ntp_server': NTP_SERVER,
                  'ntp_port': NTP_PORT
                  }
            modem = instamsg.Modem(modemSettings, _handleModemDebugMessages)
            instaMsg = instamsg.InstaMsg(clientId, authKey, __onConnect, __onDisConnect, __oneToOneMessageHandler, options)
            while 1:
                instaMsg.process()
                instamsg.time.sleep(1)
        except:
            print("Unknown Error in start: %s %s" % (str(sys.exc_info()[0]), str(sys.exc_info()[1])))
    finally:
        if(instaMsg):
            instaMsg.close()
            instaMsg = None
    
def __onConnect(instaMsg):
#     topic = "62513710-86c0-11e4-9dcf-a41f726775dd"
    topic = "subTopic1"
    qos = 0
    __subscribe(instaMsg, topic, qos)
#     __publishMessage(instaMsg, "32680660-8098-11e4-94ac-543530e3bc65", "cccccccccccc",2, 0)
    __sendMessage(instaMsg)
#     __publishMessage(instaMsg, "32680660-8098-11e4-94ac-543530e3bc65", "bbbbbbbbbbbb",0, 0)
    
def __onDisConnect():
    print "Client disconnected."
    
def _handleModemDebugMessages(level, msg):
    print "[%s]%s" % (instamsg.INSTAMSG_LOG_LEVEL[level], msg)
    
def __subscribe(instaMsg, topic, qos):
    try:
        def _resultHandler(result):
            print "Subscribed to topic %s with qos %d" % (topic, qos)
    #         print "Unsubscribing from topic %s..." %topic
    #         __unsubscribe(instaMsg, topic)
        instaMsg.subscribe(topic, qos, __messageHandler, _resultHandler)
    except Exception, e:
        print str(e)
    
def __publishMessage(instaMsg, topic, msg, qos, dup):
    try:
        def _resultHandler(result):
            print "Published message %s to topic %s with qos %d" % (msg, topic, qos)
        instaMsg.publish(topic, msg, qos, dup, _resultHandler)
    except Exception, e:
        print str(e)
    
def __unsubscribe(instaMsg, topic):
    try:
        def _resultHandler(result):
            print "UnSubscribed from topic %s" % topic
        instaMsg.unsubscribe(topic, _resultHandler)
    except Exception, e:
        print str(e)
        
def __messageHandler(mqttMessage):
        if(mqttMessage):
            print "Received message %s" % str(mqttMessage.toString())
        
def __oneToOneMessageHandler(msg):
    if(msg):
        print "One to One Message received %s" % msg.toString()
        msg.reply("This is a reply to a one to one message.")
        
def __sendMessage(instaMsg):
    try:
        clienId = "32680660-8098-11e4-94ac-543530e3bc65"
        msg = "This is a test send message."
        qos = 1
        dup = 0
        def _replyHandler(result):
            if(result.succeeded()):
                replyMessage = result.result()
                if(replyMessage):
                    print "Message received %s" % replyMessage.toString()
                    replyMessage.reply("This is a reply to a reply.")
#                     replyMessage.fail(1, "The message failed")
            else:
                print "Unable to send message errorCode= %d errorMsg=%s" % (result.code[0], result.code[1])
        instaMsg.send(clienId, msg, qos, dup, _replyHandler, 120)    
    except Exception, e:
        print str(e)
    
if  __name__ == "__main__":
    rc = start(sys.argv)
    sys.exit(rc)
