# -*- coding: utf-8 -*-
import MOD
import MDM
import MDM2
import sys 
import time
import instamsg
import posix
    

####InstaMsg ###############################################################################
# Logging Levels
INSTAMSG_LOG_LEVEL_DISABLED = 0
INSTAMSG_LOG_LEVEL_INFO = 1
INSTAMSG_LOG_LEVEL_ERROR = 2
INSTAMSG_LOG_LEVEL_DEBUG = 3
# Logging Level String
INSTAMSG_LOG_LEVEL = {0:"DISABLED", 1:"INFO", 2:"ERROR", 3:"DEBUG"}
# Error codes
INSTAMSG_ERROR_TIMEOUT = 0
INSTAMSG_ERROR_NO_HANDLERS = 1
INSTAMSG_ERROR_SOCKET = 2
INSTAMSG_ERROR_AUTHENTICATION = 3
# Message QOS
INSTAMSG_QOS0 = 0
INSTAMSG_QOS1 = 1
INSTAMSG_QOS2 = 2
#Provisioning States
PROVISIONIG_STARTED = 0
PROVISIONIG_SMS_READ = 1
PROVISIONIG_MSG_SENT = 2
PROVISIONING_COMPLETED = 3
NETWORK_INFO_PUBLISH_INTERVAL = 300

class InstaMsg:
    INSTAMSG_MAX_BYTES_IN_MSG = 10240
    INSTAMSG_KEEP_ALIVE_TIMER = 600
    INSTAMSG_RECONNECT_TIMER = 90
    INSTAMSG_HOST = "device.instamsg.io"
    INSTAMSG_PORT = 1883
    INSTAMSG_PORT_SSL = 8883
    INSTAMSG_HTTP_HOST = "platform.instamsg.io"
    INSTAMSG_HTTP_PORT = 80
    INSTAMSG_HTTPS_PORT = 443
    INSTAMSG_API_VERSION = "1.0"
    INSTAMSG_RESULT_HANDLER_TIMEOUT = 10    
    INSTAMSG_MSG_REPLY_HANDLER_TIMEOUT = 10
    # InstaMsg Versions // Update every time when some changes happened in this file.
    INSTAMSG_VERSION = "1.01.00"
    
    def __init__(self, clientId, authKey, connectHandler, disConnectHandler, oneToOneMessageHandler, options={}):
        if(not callable(connectHandler)): raise ValueError('connectHandler should be a callable object.')
        if(not callable(disConnectHandler)): raise ValueError('disConnectHandler should be a callable object.')
        if(not callable(oneToOneMessageHandler)): raise ValueError('oneToOneMessageHandler should be a callable object.')
        if(clientId): 
            if(len(clientId) != 36): raise ValueError('clientId: %s is not a valid uuid e.g. cbf7d550-7204-11e4-a2ad-543530e3bc65')% clientId
        self.__clientId = clientId
        self.__authKey = authKey 
        self.__smsConfigured = 0
        self.__provisioned = 0
        self.__modem = None
        self.__provisioningData = {}
        if(self.__clientId):
            self.__provisioningState = PROVISIONING_COMPLETED
            self.__provisioned = 1
        else:
            self.__provisioningState = PROVISIONIG_STARTED
        self.__options = options
        self.__onConnectCallBack = connectHandler   
        self.__onDisConnectCallBack = disConnectHandler  
        self.__oneToOneMessageHandler = oneToOneMessageHandler
        if( not options.has_key('configHandler')): options['configHandler'] = None
        if( not options.has_key('onProvisionCallback')): options['onProvisionCallback'] = None
        self.__configHandler = options['configHandler']
        self.__onProvisionCallBack = options['onProvisionCallback']
        self.__authHash = None
        self.__init(clientId, authKey)
        self.__logsListener = []
        self.__defaultReplyTimeout = self.INSTAMSG_RESULT_HANDLER_TIMEOUT
        self.__msgHandlers = {}
        self.__sendMsgReplyHandlers = {}  # {handlerId:{time:122334,handler:replyHandler, timeout:10, timeOutMsg:"Timed out"}}
        self.__sslEnabled = 0
        self.__initOptions(options)
        self.__mqttClient = None
        self.__networkInfoPublishTimer = time.time()
        if(self.__enableTcp):
            mqttoptions = self.__mqttClientOptions(clientId, authKey, self.__keepAliveTimer, self.__sslEnabled)
            self.__mqttClient = MqttClient(self.INSTAMSG_HOST, self.__port, mqttoptions)
            self.__mqttClient.onConnect(self.__onConnect)
            self.__mqttClient.onDisconnect(self.__onDisConnect)
            self.__mqttClient.onDebugMessage(self.__handleDebugMessage)
            self.__mqttClient.onMessage(self.__handleMessage)
            if(self.__provisioned):
                time.sleep(5)
                self.__mqttClient.connect()
                
    def __init(self, clientId, authKey):
        if (clientId and authKey):
            sha256 = Sha256(clientId + authKey)
            self.__authHash = sha256.hexdigest()
            self.__filesTopic = "instamsg/clients/%s/files" % clientId
            self.__fileUploadUrl = "/api/%s/clients/%s/files" % (self.INSTAMSG_API_VERSION, clientId)
            self.__enableServerLoggingTopic = "instamsg/clients/%s/enableServerLogging" % clientId
            self.__serverLogsTopic = "instamsg/clients/%s/logs" % clientId
            self.__rebootTopic = "instamsg/clients/%s/reboot" % clientId
            self.__infoTopic = "instamsg/clients/%s/info" % clientId
            self.__sessionTopic = "instamsg/clients/%s/session" % clientId
            self.__configServerToClientTopic = "instamsg/clients/%s/config/serverToClient" % clientId
            self.__configClientToServerTopic = "instamsg/clients/%s/config/clientToServer" % clientId
            self.__networkInfoTopic = "instamsg/clients/%s/network" % clientId

    def __initOptions(self, options):
        if(self.__options.has_key('enableSocket')):
            self.__enableTcp = options.get('enableSocket')
        else: self.__enableTcp = 1
        if(self.__options.has_key('enableLogToServer')):
            self.__enableLogToServer = options.get('enableLogToServer')
        else: self.__enableLogToServer = 0
        if(self.__options.has_key('logLevel')):
            self.__logLevel = options.get('logLevel')
            if(self.__logLevel < INSTAMSG_LOG_LEVEL_DISABLED or self.__logLevel > INSTAMSG_LOG_LEVEL_DEBUG):
                raise ValueError("logLevel option should be in between %d and %d" % (INSTAMSG_LOG_LEVEL_DISABLED, INSTAMSG_LOG_LEVEL_DEBUG))
        else: self.__logLevel = INSTAMSG_LOG_LEVEL_DISABLED
        if(options.has_key('keepAliveTimer')):
            self.__keepAliveTimer = options.get('keepAliveTimer')
        else:
            self.__keepAliveTimer = self.INSTAMSG_KEEP_ALIVE_TIMER
        if(options.has_key('enableSsl') and options.get('enableSsl')): 
            self.__sslEnabled = 1
            self.__port = self.INSTAMSG_PORT_SSL 
            self.__httpPort = self.INSTAMSG_HTTPS_PORT
        else: 
            self.__port = self.INSTAMSG_PORT
            self.__httpPort = self.INSTAMSG_HTTP_PORT
            
    def process(self):
        try:
            while(not self.__provisioned):
                self.__provision()
                time.sleep(30)
                if(self.__provisioned):
                    break
            if(self.__mqttClient):
                self.__mqttClient.process()
                self.__processHandlersTimeout()
                self.__publishNetworkStrengthInfo()
        except Exception, e:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = process]- %s" % (str(e)))
                    
    def close(self):
        if(not self.__provisioned):InstaMsgError("Cannot close connection as device not provisioned.")
        try:
            self.__mqttClient.disconnect()
            self.__mqttClient = None
            self.__sendMsgReplyHandlers = None
            self.__msgHandlers = None
            self.__subscribers = None
            return 1
        except:
            return - 1
    
    def publish(self, topic, msg, qos=INSTAMSG_QOS0, dup=0, resultHandler=None, timeout=INSTAMSG_RESULT_HANDLER_TIMEOUT):
        if(not self.__provisioned):InstaMsgPubError("Cannot publish as device not provisioned.")
        if(self.__mqttClient and topic):
            try:
                self.__mqttClient.publish(topic, msg, qos, dup, resultHandler, timeout)
            except Exception, e:
                raise InstaMsgPubError(str(e))
        else: raise ValueError("Topic cannot be null or empty string.")
    
    def subscribe(self, topic, qos, msgHandler, resultHandler, timeout=INSTAMSG_RESULT_HANDLER_TIMEOUT):
        if(not self.__provisioned):InstaMsgSubError("Cannot subscribe device not provisioned.")
        if(self.__mqttClient):
            try:
                if(not callable(msgHandler)): raise ValueError('msgHandler should be a callable object.')
                self.__msgHandlers[topic] = msgHandler
                if(topic == self.__clientId):
                    raise ValueError("Canot subscribe to clientId. Instead set oneToOneMessageHandler.")
                def _resultHandler(result):
                    if(result.failed()):
                        if(self.__msgHandlers.has_key(topic)):
                            del self.__msgHandlers[topic]
                    resultHandler(result)
                self.__mqttClient.subscribe(topic, qos, _resultHandler, timeout)
            except Exception, e:
                self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = subscribe][%s]:: %s" % (e.__class__.__name__ , str(e)))
                raise InstaMsgSubError(str(e))
        else:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = subscribe][%s]:: %s" % ("InstaMsgSubError" + str(e)))
            raise InstaMsgSubError("Cannot subscribe as TCP is not enabled. Two way messaging only possible on TCP and not HTTP")
            

    def unsubscribe(self, topics, resultHandler, timeout=INSTAMSG_RESULT_HANDLER_TIMEOUT):
        if(not self.__provisioned):InstaMsgUnSubError("Cannot unsubscribe as device not provisioned.")
        if(self.__mqttClient):
            try:
                def _resultHandler(result):
                    if(result.succeeded()):
                        for topic in topics:
                            if(self.__msgHandlers.has_key(topic)):
                                del self.__msgHandlers[topic]
                    resultHandler(result)
                self.__mqttClient.unsubscribe(topics, _resultHandler, timeout)
            except Exception, e:
                self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = unsubscribe][%s]:: %s" % (e.__class__.__name__ , str(e)))
                raise InstaMsgUnSubError(str(e))
        else:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = unsubscribe][%s]:: %s" % ("InstaMsgUnSubError" , str(e)))
            raise InstaMsgUnSubError("Cannot unsubscribe as TCP is not enabled. Two way messaging only possible on TCP and not HTTP")
    
    def send(self, clienId, msg, qos=INSTAMSG_QOS0, dup=0, replyHandler=None, timeout=INSTAMSG_MSG_REPLY_HANDLER_TIMEOUT):
        if(not self.__provisioned):InstaMsgSendError("Cannot send message as device not provisioned.")
        try:
            messageId = self._generateMessageId()
            msg = Message(messageId, clienId, msg, qos, dup, replyTopic=self.__clientId, instaMsg=self)._sendMsgJsonString()
            self._send(messageId, clienId, msg, qos, dup, replyHandler, timeout)
        except Exception, e:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = send][%s]:: %s" % (e.__class__.__name__ , str(e)))
            raise InstaMsgSendError(str(e))
        
    def log(self, level, message):
        if(self.__enableLogToServer and self.__provisioned):
            self.publish(self.__serverLogsTopic, message, 0)
        else:
            try:
                print "[%s]%s\r\n" % (INSTAMSG_LOG_LEVEL[level], message)
            except:
                pass
            
    def publishConfig(self, configs, resultHandler=None):
        if(not self.__provisioned):InstaMsgSendError("Cannot publish config as device not provisioned.")
        try:
            configs["instamsg_version"]="1.0"
            message = str(configs).replace("\'", '"').replace("'", '"')
            def _resultHandler(result):
                if(result.failed()):
                    if(callable(resultHandler)):resultHandler(Result(configs,0,result.cause()))  
                    self.log(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsg]::Error publishing Config to server: %s" %str(result.cause()))  
                else:
                    if(callable(resultHandler)):resultHandler(Result(configs,1))
                    self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Config published to server: %s" %str(configs))  
            self.publish(self.__configClientToServerTopic, message, qos=INSTAMSG_QOS1, dup=0, resultHandler=_resultHandler)
        except Exception, e:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientConfigError, method = send][%s]:: %s" % (e.__class__.__name__ , str(e)))
            
    def _send(self, messageId, clienId, msg, qos, dup, replyHandler, timeout):
        try:
            if(replyHandler):
                timeOutMsg = "Sending message[%s] %s to %s timed out." % (str(messageId), str(msg), str(clienId))
                self.__sendMsgReplyHandlers[messageId] = {'time':time.time(), 'timeout': timeout, 'handler':replyHandler, 'timeOutMsg':timeOutMsg}
                def _resultHandler(result):
                    if(result.failed()):
                        if(self.__sendMsgReplyHandlers.has_key(messageId)):
                            del self.__sendMsgReplyHandlers[messageId]
                    replyHandler(result)
            else:
                _resultHandler = None
            self.publish(clienId, msg, qos, dup, _resultHandler)
        except Exception, e:
            if(self.__sendMsgReplyHandlers.has_key(messageId)):
                del self.__sendMsgReplyHandlers[messageId]
            raise Exception(str(e))
            
    def _generateMessageId(self):
        messageId = self.__clientId + "-" + str(int(time.time() * 1000))
        while(self.__sendMsgReplyHandlers.has_key(messageId)):
            messageId = time.time()
        return messageId;
    
    def __provision(self):
        try:
            if(self.__provisioningState == PROVISIONIG_STARTED):
                self.__provisioningData = {}
                if(not self.__smsConfigured):
                    at.setSmsMode()
                    at.setSmsMsgFormat(1)
                    self.__smsConfigured = 1
                smses = at.getSmses(1,4)
                dataKeys = ['time', 'sg_pass', 'sg_pin', 'sg_apn', 'sg_user', 'prov_pin']
                for sms in smses:
                    provisioningData = {}
                    sms = "".join(sms.split())
                    for dataKey in dataKeys:
                        s='"%s":"' % dataKey
                        if(sms.find(s) >=0):
                            a=sms.find(s)+len(s)
                            b=sms.find('","',a)
                            if(b==-1): b = -2
                            value = sms[a:b]
                            if(dataKey == "time"):
                                value = long(value)
                            provisioningData[dataKey]=value
                        else:break
                    if(len(provisioningData) == len(dataKeys)):
                        if(not self.__provisioningData or (provisioningData["time"] > self.__provisioningData["time"])):
                            self.__provisioningData = provisioningData
                            self.__provisioningState = PROVISIONIG_SMS_READ
                        self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Provisioning sms read: %s" % sms)
                    elif(provisioningData):
                        self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Incomplete provisioning sms received: %s" %sms)
            if(not self.__provisioningData):
                self.log(INSTAMSG_LOG_LEVEL_INFO, "No provisioning sms read.")
            if(self.__provisioningData  and self.__provisioningState == PROVISIONIG_SMS_READ):
                self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Processing provisioning sms data: %s" % str(self.__provisioningData))
                self.__provisioningState = PROVISIONIG_MSG_SENT
                self.__sendProvisioningMsg(self.__provisioningData)
        except Exception, e:
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsgClientError, method = process]- %s" % (str(e)))
                    
    def __sendProvisioningMsg(self,provisioningData):
        if(not self.__modem or (self.__modem and self.__modem.getState() != Modem.MODEM_STATE_OK)):
            self.__modem = self.__initializeModem(provisioningData)
        provId = self.__modem.imei
        provPin = provisioningData['prov_pin']
        self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Sending provisioning message...")
        provResponse = self.__mqttClient.provision(provId, provPin)
        if(provResponse):
            provisioningData['client_id'] = provResponse[0]
            provisioningData['auth_token'] = provResponse[1]
            self.__onProvisionCallBack (provisioningData)
            self.__init(provResponse[0], provResponse[1])
            self.__provisioned, self.__provisioningState = 1 ,PROVISIONING_COMPLETED
            self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Provisioning completed.")
            self.__initMqttClient(provResponse[0],provResponse[1])
            at.deleteSms(1,4)
        else:
            self.__provisioningState = PROVISIONIG_STARTED
            self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Provisioning failed. Restarting provisioning...")
            
    def __initMqttClient(self, clientId, authKey):
            mqttoptions = self.__mqttClientOptions(clientId, authKey, self.__keepAliveTimer, self.__sslEnabled)
            self.__mqttClient.setOptions(mqttoptions)
        
    def __initializeModem(self,provisioningData):
        modemSettings = {
          'sim_pin':provisioningData["sg_pin"],
          'gprs_apn':provisioningData["sg_apn"],
          'gprs_userid':provisioningData["sg_user"],
          'gprs_pswd':provisioningData["sg_pass"],
          'logLevel':instamsg.INSTAMSG_LOG_LEVEL_DEBUG
          }
        def _handleModemDebugMessages(level, msg):
            print "[%s]%s\r\n" % (instamsg.INSTAMSG_LOG_LEVEL[level], msg)
        return Modem(modemSettings, _handleModemDebugMessages)
            
        
    def __enableServerLogging(self, msg):
        if (msg):
            msgJson = self.__parseJson(msg.payload);
            if (msgJson is not None and (msgJson.has_key('client_id') and (msgJson.has_key('logging')))):
                clientId = str(msgJson['client_id'])
                logging = msgJson['logging']
                if (logging):
                    if(not self.__logsListener.__contains__(clientId)):
                        self.__logsListener.append(clientId)
                        self.__enableLogToServer = 1;
                    else:
                        if(self.__logsListener.__contains__(clientId)):
                            self.__logsListener.remove(clientId);
                        if (len(self.__logsListener) == 0):
                            self.__enableLogToServer = 0;
    
    def __onConnect(self, mqttClient):
        self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]:: Client connected to InstaMsg IOT cloud service.")
        def _resultHandler(result):
            self.log(INSTAMSG_LOG_LEVEL_INFO,"Subscribed to topic %s " % (self.__enableServerLoggingTopic))
        self.__publishClientInfo()
        self.__publishClientSessionData()
        if(self.__onConnectCallBack): self.__onConnectCallBack(self)  
        
    def __publishClientSessionData(self):
        ipAddress = at.getGPRSAddress(1)
        session = {'network_interface':"GPRS", "instamsg_version" : self.INSTAMSG_VERSION}
        self.publish(self.__sessionTopic, str(session), INSTAMSG_QOS0, 0)
    
    def __publishClientInfo(self):
        info = {'imei': at.getIMEI(), 'serial_number': at.getIMEI(), 'model': at.getModel(),
                    'firmware_version': at.getFirmwareVersion(), 'manufacturer': at.getManufacturerIdentification(), "client_version" : self.INSTAMSG_VERSION, "instamsg_version" : self.INSTAMSG_VERSION}
        self.publish(self.__infoTopic, str(info), INSTAMSG_QOS0, 0)
        
    def __publishNetworkStrengthInfo(self):
        if(self.__networkInfoPublishTimer - time.time() <= 0):
            networkInfo = {'antenna_status': at.getAntennaStatus(), 'signal_strength': str(self.__getSignalStrength()), "instamsg_version" : self.INSTAMSG_VERSION}
            self.__networkInfoPublishTimer = self.__networkInfoPublishTimer + NETWORK_INFO_PUBLISH_INTERVAL
            self.publish(self.__networkInfoTopic, str(networkInfo), INSTAMSG_QOS0, 0)
            
    def __getSignalStrength(self):
        try:
            quality = self.__parseJson(str(at.getSignalQuality()))
            if (len(quality) > 0):
                return (-113 + int((2 * int(quality[0]))))
            else:
                return -1
        except:
            return -1
            
    def __onDisConnect(self):
        self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]:: Client disconnected from InstaMsg IOT cloud service.")
        if(self.__onDisConnectCallBack): self.__onDisConnectCallBack()  
        
    def __handleDebugMessage(self, level, msg):
        if(level <= self.__logLevel):
            if(self.__enableLogToServer):
                self.log(level, msg)
            else:
                try:
                    print "[%s]%s\r\n" % (INSTAMSG_LOG_LEVEL[level], msg)
                except:
                    pass
    
    def __handleMessage(self, mqttMsg):
        try:
            if(mqttMsg.topic == self.__clientId):
                self.__handlePointToPointMessage(mqttMsg)
            elif(mqttMsg.topic == self.__filesTopic):
                self.__handleFileTransferMessage(mqttMsg)
            elif(mqttMsg.topic == self.__rebootTopic):
                self.__handleSystemRebootMessage()
            elif(mqttMsg.topic == self.__configServerToClientTopic):
                self.__handleConfigMessage(mqttMsg)
            elif(mqttMsg.topic == self.__enableServerLoggingTopic):
                self.__enableServerLogging(mqttMsg)
            else:
                msg = Message(mqttMsg.messageId, mqttMsg.topic, mqttMsg.payload, mqttMsg.fixedHeader.qos, mqttMsg.fixedHeader.dup)
                msgHandler = self.__msgHandlers.get(mqttMsg.topic)
                if(msgHandler):
                    msgHandler(msg)
        except Exception, e:
            self.log(INSTAMSG_LOG_LEVEL_ERROR, "[InstaMsg]::Error in handling received message. Error message is : %s " % str(e))
                
    def __handleConfigMessage(self, mqttMsg):
        msgJson = self.__parseJson(mqttMsg.payload)
        if(callable(self.__configHandler)):
            self.__configHandler(Result((msgJson),1))
        
    def __handleFileTransferMessage(self, mqttMsg):
        msgJson = self.__parseJson(mqttMsg.payload)
        qos, dup = mqttMsg.fixedHeader.qos, mqttMsg.fixedHeader.dup
        messageId, replyTopic, method, url, filename = None, None, None, None, None
        if(msgJson.has_key('reply_to')):
            replyTopic = msgJson['reply_to']
        else:
            raise ValueError("File transfer message json should have reply_to address.")   
        if(msgJson.has_key('message_id')):
            messageId = msgJson['message_id']
        else: 
            raise ValueError("File transfer message json should have a message_id.") 
        try:
            if(msgJson.has_key('method')):
                method = msgJson['method']
            else: 
                raise ValueError("File transfer message json should have a method.") 
            if(msgJson.has_key('url')):
                url = msgJson['url']
            if(msgJson.has_key('filename')):
                filename = msgJson['filename']
            if(replyTopic):
                if(method == "GET" and not filename):
                    filelist = self.__getFileList()
                    msg = '{"response_id": "%s", "status": 1, "files": %s}' % (messageId, filelist)
                    self.publish(replyTopic, msg, qos, dup)
                elif (method == "GET" and filename):
                    httpClient = HTTPClient(self.INSTAMSG_HTTP_HOST, self.__httpPort)
                    httpResponse = httpClient.uploadFile(self.__fileUploadUrl, filename, headers={"Client-Authorization":self.__authHash, "ClientId":self.__clientId})
                    if(httpResponse and httpResponse.status == 200):
                        msg = '{"response_id": "%s", "status": 1, "url":"%s"}' % (messageId, httpResponse.body)
                    else:
                        msg = '{"response_id": "%s", "status": 0}' % (messageId)
                    self.publish(replyTopic, msg, qos, dup)
                elif ((method == "POST" or method == "PUT") and filename and url):
                    httpClient = HTTPClient(self.INSTAMSG_HTTP_HOST, self.__httpPort)
                    httpResponse = httpClient.downloadFile(url, filename)
                    if(httpResponse and httpResponse.status == 200):
                        msg = '{"response_id": "%s", "status": 1}' % (messageId)
                    else:
                        msg = '{"response_id": "%s", "status": 0}' % (messageId)
                    self.publish(replyTopic, msg, qos, dup)
                elif ((method == "DELETE") and filename):
                    try:
                        msg = '{"response_id": "%s", "status": 1}' % (messageId)
                        self.__deleteFile(filename)
                        self.publish(replyTopic, msg, qos, dup)
                    except Exception, e:
                        msg = '{"response_id": "%s", "status": 0, "error_msg":"%s"}' % (messageId, str(e))
                        self.publish(replyTopic, msg, qos, dup)
        except Exception, e:
            if(replyTopic and messageId and qos and dup):
                msg = '{"response_id": "%s", "status": 0, "error_msg":"%s"}' % (messageId, "File operation failed or timed out. Try again.")
                self.publish(replyTopic, msg, qos, dup)   
            self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_DEBUG, "[InstaMsg, method = __handleFileTransferMessage][%s]:: %s" % (e.__class__.__name__ , str(e)))        
            
    def __getFileList(self):
        fileList, retry = {}, 3
        while (retry > 0):
            retry = retry - 1
            try:
                fileList = at.getfilelist()
                activeScript = at.getActiveScript()
                if(fileList): 
                    if(activeScript):
                        fileList['main_script'] = activeScript
                    break
            except Exception, e :
                if(retry == 0):
                    if(e.__class__.__name__ == 'ATTimeoutError'):
                        raise at.timeout(str(e))
                    elif(e.__class__.__name__ == 'ATError'):
                        raise at.error(str(e))
                    else:
                        raise Exception(str(e))
                continue
        return str(fileList).replace("'", '"')   
    
    def __deleteFile(self, filename):
        posix.unlink(filename)
        
    def __parseJson(self, jsonString):
        return eval(jsonString)  # Hack as not implemented Json Library 
          
    def __handleSystemRebootMessage(self):
        self.log(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]::Rebooting device.") 
        at.reboot()
        
    def __handlePointToPointMessage(self, mqttMsg):
        msgJson = self.__parseJson(mqttMsg.payload)
        messageId, responseId, replyTopic, status = None, None, None, 1
        if(msgJson.has_key('reply_to')):
            replyTopic = msgJson['reply_to']
        else:
            raise ValueError("Send message json should have reply_to address.")   
        if(msgJson.has_key('message_id')):
            messageId = msgJson['message_id']
        else: 
            raise ValueError("Send message json should have a message_id.") 
        if(msgJson.has_key('response_id')):
            responseId = msgJson['response_id']
        if(msgJson.has_key('body')):
            body = msgJson['body']
        if(msgJson.has_key('status')):
            status = int(msgJson['status'])
        qos, dup = mqttMsg.fixedHeader.qos, mqttMsg.fixedHeader.dup
        if(responseId):
            # This is a response to existing message
            if(status == 0):
                errorCode, errorMsg = None, None
                if(isinstance(body, dict)):
                    if(body.has_key("error_code")):
                        errorCode = body.get("error_code")
                    if(body.has_key("error_msg")):
                        errorMsg = body.get("error_msg")
                result = Result(None, 0, (errorCode, errorMsg))
            else:
                msg = Message(messageId, self.__clientId, body, qos, dup, replyTopic=replyTopic, instaMsg=self)
                result = Result(msg, 1)
            
            if(self.__sendMsgReplyHandlers.has_key(responseId)):
                msgHandler = self.__sendMsgReplyHandlers.get(responseId).get('handler')
            else:
                msgHandler = None
                self.__handleDebugMessage(INSTAMSG_LOG_LEVEL_INFO, "[InstaMsg]:: No handler for message [messageId=%s responseId=%s]" % (str(messageId), str(responseId)))
            if(msgHandler):
                msgHandler(result)
                del self.__sendMsgReplyHandlers[responseId]
        else:
            if(self.__oneToOneMessageHandler):
                msg = Message(messageId, self.__clientId, body, qos, dup, replyTopic=replyTopic, instaMsg=self)
                self.__oneToOneMessageHandler(msg)
        
    def __mqttClientOptions(self, username, password, keepAliveTimer, sslEnabled):
        if(password and len(password) > self.INSTAMSG_MAX_BYTES_IN_MSG): raise ValueError("Password length cannot be more than %d bytes." % self.INSTAMSG_MAX_BYTES_IN_MSG)
        if(keepAliveTimer > 32768 or keepAliveTimer < self.INSTAMSG_KEEP_ALIVE_TIMER): raise ValueError("keepAliveTimer should be between %d and 32768" % self.INSTAMSG_KEEP_ALIVE_TIMER)
        options = {}
        options['clientId'] = str(at.getIMEI())
        options['hasUserName'] = 1
        options['hasPassword'] = 1
        options['username'] = username
        options['password'] = password
        options['isCleanSession'] = 1
        options['keepAliveTimer'] = keepAliveTimer
        options['isWillFlag'] = 0
        options['willQos'] = 0
        options['isWillRetain'] = 0
        options['willTopic'] = ""
        options['willMessage'] = ""
        options['logLevel'] = self.__logLevel
        options['reconnectTimer'] = self.INSTAMSG_RECONNECT_TIMER
        options['sslEnabled'] = sslEnabled
        return options
    
    def __processHandlersTimeout(self): 
        for key, value in self.__sendMsgReplyHandlers.items():
            if((time.time() - value['time']) >= value['timeout']):
                resultHandler = value['handler']
                if(resultHandler):
                    timeOutMsg = value['timeOutMsg']
                    resultHandler(Result(None, 0, (INSTAMSG_ERROR_TIMEOUT, timeOutMsg)))
                    value['handler'] = None
                del self.__sendMsgReplyHandlers[key]
                
class Message:
    def __init__(self, messageId, topic, body, qos=INSTAMSG_QOS0, dup=0, replyTopic=None, instaMsg=None):
        self.__instaMsg = instaMsg
        self.__id = messageId
        self.__topic = topic
        self.__body = body
        self.__replyTopic = replyTopic
        self.__responseId = None
        self.__dup = dup
        self.__qos = qos
        
    def id(self):
        return self.__id
    
    def topic(self):
        return self.__topic
    
    def qos(self):
        return self.__qos
    
    def isDublicate(self):
        return self.__dup
    
    def body(self):
        return self.__body
    
    def replyTopic(self):
        return self.__replyTopic
        
    def reply(self, msg, dup=0, replyHandler=None, timeout=InstaMsg.INSTAMSG_RESULT_HANDLER_TIMEOUT):
        if(self.__instaMsg and self.__replyTopic):
            msgId = self.__instaMsg._generateMessageId()
            replyMsgJsonString = ('{"message_id": "%s", "response_id": "%s", "reply_to": "%s", "body": "%s", "status": 1}') % (msgId, self.__id, self.__topic, msg)
            self.__instaMsg._send(msgId, self.__replyTopic, replyMsgJsonString, self.__qos, dup, replyHandler, timeout)
    
    def fail(self, errorCode, errorMsg):
        if(self.__instaMsg and self.__replyTopic):
            msgId = self.__instaMsg._generateMessageId()
            failReplyMsgJsonString = ('{"message_id": "%s", "response_id": "%s", "reply_to": "%s", "body": {"error_code":%d, "error_msg":%s}, "status": 0}') % (msgId, self.__id, self.__topic, errorCode, errorMsg)
            self.__instaMsg._send(msgId, self.__replyTopic, failReplyMsgJsonString, self.__qos, 0, None, 0)
    
    def sendFile(self, fileName, resultHandler, timeout):
        pass
    
    def _sendMsgJsonString(self):
        return ('{"message_id": "%s", "reply_to": "%s", "body": "%s"}') % (self.__id, self.__replyTopic, self.__body)
    
    def toString(self):
        return ('[ id=%s, topic=%s, body=%s, qos=%s, dup=%s, replyTopic=%s]') % (str(self.__id), str(self.__topic), str(self.__body), str(self.__qos), str(self.__dup), str(self.__replyTopic))
    
    def __sendReply(self, msg, replyHandler):
        pass
    
class Result:
    def __init__(self, result, succeeded=1, cause=None):
        self.__result = result
        self.__succeeded = 1
        self.__cause = cause
        
    def result(self):
        return self.__result
    
    def failed(self):
        return not self.__succeeded
    
    def succeeded(self):
        return self.__succeeded
    
    def cause(self):
        return self.__cause
    
####MqttClient ###############################################################################

class MqttClient:
    MQTT_PROTOCOL_VERSION = 3
    MQTT_PROTOCOL_NAME = "MQIsdp"
    MQTT_MAX_INT = 65535
    MQTT_RESULT_HANDLER_TIMEOUT = 10
    MQTT_MAX_RESULT_HANDLER_TIMEOUT = 500
    MAX_BYTES_MDM_READ = 511  # Telit MDM read limit
    MQTT_MAX_TOPIC_LEN = 32767
    MQTT_MAX_PAYLOAD_SIZE = 10000
    MQTT_SOCKET_TIMEOUT = 10
    # Mqtt Message Types
    CONNECT = 0x10
    CONNACK = 0x20
    PUBLISH = 0x30
    PUBACK = 0x40
    PUBREC = 0x50
    PUBREL = 0x60
    PUBCOMP = 0x70
    SUBSCRIBE = 0x80
    SUBACK = 0x90
    UNSUBSCRIBE = 0xA0
    UNSUBACK = 0xB0
    PINGREQ = 0xC0
    PINGRESP = 0xD0
    DISCONNECT = 0xE0
    PROVACK = 0xF0
    # CONNACK codes
    CONNECTION_ACCEPTED = 0x00
    CONNECTION_REFUSED_UNACCEPTABLE_PROTOCOL_VERSION = 0X01
    CONNECTION_REFUSED_IDENTIFIER_REJECTED = 0x02
    CONNECTION_REFUSED_SERVER_UNAVAILABLE = 0x03
    CONNECTION_REFUSED_BAD_USERNAME_OR_PASSWORD = 0x04
    CONNECTION_REFUSED_NOT_AUTHORIZED = 0x05;
    # QOS codes
    MQTT_QOS0 = 0
    MQTT_QOS1 = 1
    MQTT_QOS2 = 2
    # Extra var
    CONNECT_ACK_TIMEOUT = 300
    SOCKET_ERROR_COUNT_FOR_REBOOT = 5
    SOCKET_RECV_ERROR_COUNT_FOR_REBOOT =3
    CONACK_TIMEOUT_COUNT_FOR_REBOOT = 1
    TCP_KEEP_ALIVE = 240

    def __init__(self, host, port, options={}):
        if(not host):
            raise ValueError('host cannot be null.')
        if(not port):
            raise ValueError('port cannot be null.')
        self.host = host
        self.port = port
        self.options = options
        self.keepAliveTimer = self.options['keepAliveTimer']
        self.reconnectTimer = options['reconnectTimer']
        self.sslEnabled = self.options['sslEnabled']
        self.__logLevel = options.get('logLevel')
        self.__cleanSession = 1
        self.__provisioned = 1
        self.__sock = None
        self.__sockInit = 0
        self.__connected = 0
        self.__connecting = 0
        self.__disconnecting = 0
        self.__waitingReconnect = 0
        self.__nextConnTry = time.time()
        self.__lastPingReqTime = time.time()
        self.__lastPingRespTime = self.__lastPingReqTime
        self.__mqttMsgFactory = MqttMsgFactory()
        self.__mqttEncoder = MqttEncoder()
        self.__mqttDecoder = MqttDecoder()
        self.__messageId = 0
        self.__onDisconnectCallBack = None
        self.__onConnectCallBack = None
        self.__onMessageCallBack = None
        self.__onDebugMessageCallBack = None
        self.__onProvisionResultHandler = None
        self.__msgIdInbox = []
        self.__resultHandlers = {}  # {handlerId:{time:122334,handler:replyHandler, timeout:10, timeOutMsg:"Timed out"}}
        self.__lastConnectTime = time.time()
        self.__socketErrorCount = 0
        self.__socketRecvErrorCount = 0
        self.__connectAckTimeoutCount = 0
    
    def setOptions(self,options): 
        self.options = options
        
    def process(self):
        try:
            if(not self.__disconnecting):
                self.connect()
                if(self.__sockInit):
                    self.__receive()
                    if (self.__connected):
                        if ((self.__lastPingReqTime + 1.5 * self.keepAliveTimer) < time.time()):
                            if (self.__lastPingRespTime is None):
                                self.disconnect()
                            else: 
                                self.__sendPingReq()
                                self.__lastPingReqTime = time.time()
                                self.__lastPingRespTime = None
            self.__processHandlersTimeout()
            if (self.__connecting and ((self.__lastConnectTime + self.CONNECT_ACK_TIMEOUT) < time.time())):
                self.__log(INSTAMSG_LOG_LEVEL_INFO, "[MqttClientError, method = process]::Connect Ack timed out. Reseting connection.")
                self.__connectAckTimeoutCount = self.__connectAckTimeoutCount + 1 
                self.__resetSock()
            self.__processErrorCount("process")
            if (self.__connectAckTimeoutCount > self.CONACK_TIMEOUT_COUNT_FOR_REBOOT):
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClient, method = process]:: Rebooting as ConAck timeout error count exceeded %d" % self.CONACK_TIMEOUT_COUNT_FOR_REBOOT)
                at.reboot()
        except SocketError, msg:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = process][SocketError]:: %s" % (str(msg)))
            self.__resetSock()
        except:
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[MqttClientError, method = process][Exception]:: %s %s" % (str(sys.exc_info()[0]), str(sys.exc_info()[1])))
    
    def provision(self, provId, provPin, timeout = 300):
        auth = None
        try:
            try:
                self.__processErrorCount("provision")
                self.__provisioned = 0
                self.__initSock()
                if(self.__sockInit):
                    options = self.options.copy()
                    options['clientId'] = 'PROVISIONING'
                    options['hasUserName'] = 1
                    if (provPin):
                        options['hasPassword'] = 1
                    else:
                        options['hasPassword'] = 0
                    options['username'] = provId
                    options['password'] = provPin
                    fixedHeader = MqttFixedHeader(self.CONNECT, qos=0, dup=0, retain=0)
                    provisionMsg = self.__mqttMsgFactory.message(fixedHeader, options, options)
                    encodedMsg = self.__mqttEncoder.encode(provisionMsg)
                    self.__sendall(encodedMsg)
                    timeout = time.time() + timeout
                    while(timeout > time.time() and not self.__provisioned):
                        time.sleep(10)
                        mqttMsg = self.__receive()
                        if(mqttMsg and mqttMsg.fixedHeader.messageType == self.PROVACK):
                            auth = self.__getAuthInfoFromProvAckMsg(mqttMsg)
                            self.__socketErrorCount = 0
                            break
            except SocketConfigError, msg:
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = provision][SocketConfigError]:: %s. Rebooting..." % (str(msg)))
                at.reboot()
            except (SocketError, SocketTimeoutError), msg:
                self.__socketErrorCount = self.__socketErrorCount + 1
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = provision][SocketError]:: %s" % (str(msg)))
            except Exception, e:
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = provision]:: %s" % (str(e)))
        finally:
            self.__closeSocket()
            self.__sockInit = 0
            if(auth):
                self.__provisioned = 1
            return auth
            
    def connect(self):
        if(not self.options['clientId']):raise ValueError('clientId cannot be null.')
        if(self.options['hasPassword'] and not self.options['password']): raise ValueError('Password cannot be null.')
        if(self.options['hasUserName'] and not self.options['username']): raise ValueError('Username cannot be null.')
        try:
            self.__initSock()
            if(self.__connecting is 0 and self.__sockInit):
                if(not self.__connected):
                    self.__connecting = 1
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Connecting to %s:%s' % (self.host, str(self.port)))   
                    fixedHeader = MqttFixedHeader(self.CONNECT, qos=0, dup=0, retain=0)
                    connectMsg = self.__mqttMsgFactory.message(fixedHeader, self.options, self.options)
                    encodedMsg = self.__mqttEncoder.encode(connectMsg)
                    self.__sendall(encodedMsg)
                    self.__lastConnectTime = time.time()
        except SocketTimeoutError:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = connect][SocketTimeoutError]:: Socket timed out")
            self.__resetSock()
        except SocketError, msg:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = connect][SocketError]:: %s" % (str(msg)))
            self.__resetSock()
        except SocketConfigError, msg:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = connect][SocketConfigError]:: %s. Rebooting..." % (str(msg)))
            at.reboot()
        except:
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[MqttClientError, method = connect][Exception]:: %s %s" % (str(sys.exc_info()[0]), str(sys.exc_info()[1])))
            self.__resetSock()
            
    def disconnect(self):
        try:
            try:
                self.__disconnecting = 1
                if(not self.__connecting  and not self.__waitingReconnect and self.__sockInit):
                    fixedHeader = MqttFixedHeader(self.DISCONNECT, qos=0, dup=0, retain=0)
                    disConnectMsg = self.__mqttMsgFactory.message(fixedHeader)
                    encodedMsg = self.__mqttEncoder.encode(disConnectMsg)
                    self.__sendall(encodedMsg)
            except Exception, msg:
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = __receive][%s]:: %s" % (msg.__class__.__name__ , str(msg)))
        finally:
            self.__resetSock()
    
    def publish(self, topic, payload, qos=MQTT_QOS0, dup=0, resultHandler=None, resultHandlerTimeout=MQTT_RESULT_HANDLER_TIMEOUT, retain=0):
        if(not self.__connected or self.__connecting  or self.__waitingReconnect):
            raise MqttClientError("Cannot publish message as not connected.")
        self.__validateTopic(topic)
        self.__validateQos(qos)
        self.__validateResultHandler(resultHandler)
        self.__validateTimeout(resultHandlerTimeout)
        fixedHeader = MqttFixedHeader(self.PUBLISH, qos, dup=0, retain=0)
        messageId = 0
        if(qos > self.MQTT_QOS0): messageId = self.__generateMessageId()
        variableHeader = {'messageId': messageId, 'topic': str(topic)}
        publishMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader, payload)
        encodedMsg = self.__mqttEncoder.encode(publishMsg)
        if (qos > self.MQTT_QOS0 and messageId and resultHandler): 
            timeOutMsg = 'Publishing message %s to topic %s with qos %d timed out.' % (payload, topic, qos)
            self.__resultHandlers[messageId] = {'time':time.time(), 'timeout': resultHandlerTimeout, 'handler':resultHandler, 'timeOutMsg':timeOutMsg}
        self.__sendall(encodedMsg)
        if(qos == self.MQTT_QOS0 and resultHandler): 
            resultHandler(Result(None, 1))  # immediately return messageId 0 in case of qos 0
        
    def subscribe(self, topic, qos, resultHandler=None, resultHandlerTimeout=MQTT_RESULT_HANDLER_TIMEOUT):
        if(not self.__connected or self.__connecting  or self.__waitingReconnect):
            raise MqttClientError("Cannot subscribe as not connected.")
        self.__validateTopic(topic)
        self.__validateQos(qos)
        self.__validateResultHandler(resultHandler)
        self.__validateTimeout(resultHandlerTimeout)
        fixedHeader = MqttFixedHeader(self.SUBSCRIBE, qos=1, dup=0, retain=0)
        messageId = self.__generateMessageId()
        variableHeader = {'messageId': messageId}
        subMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader, {'topic':topic, 'qos':qos})
        encodedMsg = self.__mqttEncoder.encode(subMsg)
        if(resultHandler):
            timeOutMsg = 'Subscribe to topic %s with qos %d timed out.' % (topic, qos)
            self.__resultHandlers[messageId] = {'time':time.time(), 'timeout': resultHandlerTimeout, 'handler':resultHandler, 'timeOutMsg':timeOutMsg}
        self.__sendall(encodedMsg)
                
    def unsubscribe(self, topics, resultHandler=None, resultHandlerTimeout=MQTT_RESULT_HANDLER_TIMEOUT):
        if(not self.__connected or self.__connecting  or self.__waitingReconnect):
            raise MqttClientError("Cannot unsubscribe as not connected.")
        self.__validateResultHandler(resultHandler)
        self.__validateTimeout(resultHandlerTimeout)
        fixedHeader = MqttFixedHeader(self.UNSUBSCRIBE, qos=1, dup=0, retain=0)
        messageId = self.__generateMessageId()
        variableHeader = {'messageId': messageId}
        if(isinstance(topics, str)):
            topics = [topics]
        if(isinstance(topics, list)):
            for topic in topics:
                self.__validateTopic(topic)
                unsubMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader, topics)
                encodedMsg = self.__mqttEncoder.encode(unsubMsg)
                if(resultHandler):
                    timeOutMsg = 'Unsubscribe to topics %s timed out.' % str(topics)
                    self.__resultHandlers[messageId] = {'time':time.time(), 'timeout': resultHandlerTimeout, 'handler':resultHandler, 'timeOutMsg':timeOutMsg}
                self.__sendall(encodedMsg)
                return messageId
        else:   raise TypeError('Topics should be an instance of string or list.') 
    
    def onConnect(self, callback):
        if(callable(callback)):
            self.__onConnectCallBack = callback
        else:
            raise ValueError('Callback should be a callable object.')
    
    def onDisconnect(self, callback):
        if(callable(callback)):
            self.__onDisconnectCallBack = callback
        else:
            raise ValueError('Callback should be a callable object.')
        
    def onDebugMessage(self, callback):
        if(callable(callback)):
            self.__onDebugMessageCallBack = callback
        else:
            raise ValueError('Callback should be a callable object.') 
    
    def onMessage(self, callback):
        if(callable(callback)):
            self.__onMessageCallBack = callback
        else:
            raise ValueError('Callback should be a callable object.')
    
    def __processErrorCount(self, methodName):
            if (self.__socketErrorCount > self.SOCKET_ERROR_COUNT_FOR_REBOOT):
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClient, method = %s]:: Rebooting as socket error count exceeded %d" % (methodName, self.SOCKET_ERROR_COUNT_FOR_REBOOT))
                at.reboot()
            if (self.__socketRecvErrorCount > self.SOCKET_RECV_ERROR_COUNT_FOR_REBOOT):
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClient, method = %s]:: Rebooting as socket error count exceeded %d" % (methodName, self.SOCKET_RECV_ERROR_COUNT_FOR_REBOOT))
                at.reboot()
                        
    def __validateTopic(self, topic):
        if(topic):
            pass
        else: raise ValueError('Topics cannot be Null or empty.')
        if (len(topic) < self.MQTT_MAX_TOPIC_LEN + 1):
            pass
        else:
            raise ValueError('Topic length cannot be more than %d' % self.MQTT_MAX_TOPIC_LEN)
        
    def __validateQos(self, qos):
        if(not isinstance(qos, int) or qos < self.MQTT_QOS0 or qos > self.MQTT_QOS2):
            raise ValueError('Qos should be a between %d and %d.' % (self.MQTT_QOS0, self.MQTT_QOS2)) 
        
    def __validateRetain(self, retain):
        if (not isinstance(retain, int) or retain != 0 or retain != 1):
            raise ValueError('Retain can only be integer 0 or 1')
        
    def __validateTimeout(self, timeout):
        if (not isinstance(timeout, int) or timeout < 0 or timeout > self.MQTT_MAX_RESULT_HANDLER_TIMEOUT):
            raise ValueError('Timeout can only be integer between 0 and %d.' % self.MQTT_MAX_RESULT_HANDLER_TIMEOUT)
        
    def __validateResultHandler(self, resultHandler):
        if(resultHandler is not None and not callable(resultHandler)):            
            raise ValueError('Result Handler should be a callable object.') 
            
    def __log(self, level, msg):
        if(level <= self.__logLevel):
            if(self.__onDebugMessageCallBack):
                self.__onDebugMessageCallBack(level, msg)

    def __sendall(self, data):
        try:
            if(data):
                self.__sock.sendall(data)
                self.__socketErrorCount = 0
        except SocketError, msg:
            self.__resetSock()
            raise SocketError(str("Socket error in send: %s. Connection reset." % (str(msg))))
            
            
    def __receive(self):
        try:
            data = self.__sock.recv(self.MAX_BYTES_MDM_READ)
            if data: 
                mqttMsg = self.__mqttDecoder.decode(data)
            else:
                mqttMsg = None
            while (mqttMsg):
                self.__socketRecvErrorCount = 0
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Received message:%s' % mqttMsg.toString())
                if(self.__provisioned):
                    self.__handleMqttMessage(mqttMsg)
                else:
                    if mqttMsg.fixedHeader.messageType == self.PROVACK: #Only handle PROVACK message till provisioning not completed, reject all other msg.
                        self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Provisioning ack received.' )
                        break
                mqttMsg = self.__mqttDecoder.decode()
            return mqttMsg
        except MqttDecoderError, msg:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = __receive][%s]:: %s" % (msg.__class__.__name__ , str(msg)))
            self.__socketRecvErrorCount = self.__socketRecvErrorCount + 1
        except SocketTimeoutError:
            pass
        except (MqttFrameError, SocketError), msg:
            self.__log(INSTAMSG_LOG_LEVEL_DEBUG, "[MqttClientError, method = __receive][%s]:: %s" % (msg.__class__.__name__ , str(msg)))
            self.__socketRecvErrorCount = self.__socketRecvErrorCount + 1
            
    def __handleMqttMessage(self, mqttMessage):
        self.__lastPingRespTime = time.time()
        msgType = mqttMessage.fixedHeader.messageType
        if msgType == self.CONNACK:
            self.__connectAckTimeoutCount = 0
            self.__handleConnAckMsg(mqttMessage)
        elif msgType == self.PUBLISH:
            self.__handlePublishMsg(mqttMessage)
        elif msgType == self.SUBACK:
            self.__handleSubAck(mqttMessage)
        elif msgType == self.UNSUBACK:
            self.__handleUnSubAck(mqttMessage)
        elif msgType == self.PUBACK:
            self.__handlePubAckMsg(mqttMessage)
        elif msgType == self.PUBREC:
            self.__handlePubRecMsg(mqttMessage)
        elif msgType == self.PUBCOMP:
            self.__onPublish(mqttMessage)
        elif msgType == self.PUBREL:
            self.__handlePubRelMsg(mqttMessage)
        elif msgType == self.PINGRESP:
            self.__lastPingRespTime = time.time()
        elif msgType == self.PROVACK:
            pass
        elif msgType in [self.CONNECT, self.SUBSCRIBE, self.UNSUBSCRIBE, self.PINGREQ, self.DISCONNECT]:
            pass  # Client will not receive these messages
        else:
            raise MqttEncoderError('MqttEncoder: Unknown message type.') 

    
    def __getResultHandler(self, mqttMessage):
        resultHandler = None
        resultHandlerDict = self.__resultHandlers.get(mqttMessage.messageId)
        if(resultHandlerDict):
            resultHandler = resultHandlerDict.get('handler')
        return resultHandler
    
    def __handleSubAck(self, mqttMessage):
        resultHandler = self.__getResultHandler(mqttMessage)
        if(resultHandler):
            resultHandler(Result(mqttMessage, 1))
            del self.__resultHandlers[mqttMessage.messageId]
    
    def __handleUnSubAck(self, mqttMessage):
        resultHandler = self.__getResultHandler(mqttMessage)
        if(resultHandler):
            resultHandler(Result(mqttMessage, 1))
            del self.__resultHandlers[mqttMessage.messageId]
    
    def __onPublish(self, mqttMessage):
        resultHandler = self.__getResultHandler(mqttMessage)
        if(resultHandler):
            resultHandler(Result(mqttMessage, 1))
            del self.__resultHandlers[mqttMessage.messageId]
    
    def __handleConnAckMsg(self, mqttMessage):
        self.__connecting = 0
        connectReturnCode = mqttMessage.connectReturnCode
        if(connectReturnCode == self.CONNECTION_ACCEPTED):
            self.__connected = 1
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Connected to %s:%s' % (self.host, str(self.port)))  
            if(self.__onConnectCallBack): self.__onConnectCallBack(self)  
        else:
            self.__handleProvisionAndConnectAckCode("Connection", connectReturnCode)

            
    def __getAuthInfoFromProvAckMsg(self, mqttMessage):
        provisionReturnCode = mqttMessage.provisionReturnCode
        if(provisionReturnCode == self.CONNECTION_ACCEPTED):
            payload = mqttMessage.payload
            clientId=payload[0:36]
            authToken = payload[37:]
            return (clientId, authToken)
        else:
            self.__handleProvisionAndConnectAckCode("Provisioning", provisionReturnCode)
            return None
            
            
    def __handleProvisionAndConnectAckCode(self, type, code):
        msg =''
        if(code == self.CONNECTION_REFUSED_UNACCEPTABLE_PROTOCOL_VERSION):
            msg = '[MqttClient]:: %s refused unacceptable mqtt protocol version.' % type
        elif(code == self.CONNECTION_REFUSED_IDENTIFIER_REJECTED):
            msg =  '[MqttClient]:: %s refused client identifier rejected.' % type
        elif(code == self.CONNECTION_REFUSED_SERVER_UNAVAILABLE): 
            msg =  '[MqttClient]:: %s refused server unavailable.' % type
        elif(code == self.CONNECTION_REFUSED_BAD_USERNAME_OR_PASSWORD):  
            msg = '[MqttClient]:: %s refused bad username or password.' % type
        elif(code == self.CONNECTION_REFUSED_NOT_AUTHORIZED):  
            msg = '[MqttClient]:: %s refused not authorized.' % type
        self.__log(INSTAMSG_LOG_LEVEL_DEBUG, msg)
        return msg
    
    def __handlePublishMsg(self, mqttMessage):
        if(mqttMessage.fixedHeader.qos > self.MQTT_QOS1): 
            if(mqttMessage.messageId not in self.__msgIdInbox):
                self.__msgIdInbox.append(mqttMessage.messageId)
         
        if(self.__onMessageCallBack):
            self.__onMessageCallBack(mqttMessage)
        if(self.MQTT_QOS1 == mqttMessage.fixedHeader.qos):
            self.__sendPubAckMsg(mqttMessage)
            
    def __sendPubAckMsg(self, mqttMessage):
        fixedHeader = MqttFixedHeader(self.PUBACK)
        variableHeader = {'messageId': mqttMessage.messageId}
        pubAckMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader)
        encodedMsg = self.__mqttEncoder.encode(pubAckMsg)
        self.__sendall(encodedMsg)
        
    def __handlePubAckMsg(self, mqttMessage):
        if(mqttMessage.messageId in self.__resultHandlers):
            resultHandler = self.__resultHandlers[mqttMessage.messageId]['handler']
            if(resultHandler):
                resultHandler(Result(mqttMessage.messageId, 1, None))
                resultHandler = None
                del self.__resultHandlers[mqttMessage.messageId]
            
    def __handlePubRelMsg(self, mqttMessage):
        fixedHeader = MqttFixedHeader(self.PUBCOMP)
        variableHeader = {'messageId': mqttMessage.messageId}
        pubComMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader)
        encodedMsg = self.__mqttEncoder.encode(pubComMsg)
        self.__sendall(encodedMsg)
        if(self.__msgIdInbox.__contains__(mqttMessage.messageId)):
            self.__msgIdInbox.remove(mqttMessage.messageId)
    
    def __handlePubRecMsg(self, mqttMessage):
        fixedHeader = MqttFixedHeader(self.PUBREL, 1)
        variableHeader = {'messageId': mqttMessage.messageId}
        pubRelMsg = self.__mqttMsgFactory.message(fixedHeader, variableHeader)
        encodedMsg = self.__mqttEncoder.encode(pubRelMsg)
        self.__sendall(encodedMsg)
    
    def __resetSock(self):
        self.__socketErrorCount = self.__socketErrorCount + 1
        if(self.__sockInit):
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Resetting connection socket...')
            self.__closeSocket()
            if(self.__onDisconnectCallBack): self.__onDisconnectCallBack()
        self.__sockInit = 0
        self.__connected = 0
        self.__connecting = 0
        self.__disconnecting = 0
        self.__lastPingReqTime = time.time()
        self.__lastPingRespTime = self.__lastPingReqTime
        
    
    def __initSock(self):
        t = time.time()
#         if (self.__sockInit is 0 and self.__nextConnTry - t > 0): raise SocketError('Last connection failed. Waiting before retry.')
        waitFor = self.__nextConnTry - t
        if (self.__sockInit is 0 and waitFor > 0): 
            if(not self.__waitingReconnect):
                self.__waitingReconnect = 1
                self.__log(INSTAMSG_LOG_LEVEL_DEBUG, '[MqttClient]:: Last connection failed. Waiting  for %d seconds before retry...' % int(waitFor))
        if (self.__sockInit is 0 and waitFor <= 0):
            self.__nextConnTry = t + self.reconnectTimer
            if(self.__sock is not None):
                self.__closeSocket()
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Opening socket to %s:%s' % (self.host, str(self.port)))
            self.__sock = Socket(self.MQTT_SOCKET_TIMEOUT, at, self.TCP_KEEP_ALIVE, self.sslEnabled, encoding=1)
            self.__sock.connect((self.host, self.port))
            self.__sockInit = 1
            self.__waitingReconnect = 0
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Socket opened to %s:%s' % (self.host, str(self.port)))   
    
    def __closeSocket(self):
        try:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Closing socket...')
            if(self.__sock):
                self.__sock.close()
                self.__sock = None
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[MqttClient]:: Socket closed.')
        except:
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, '[MqttClient]:: Unexpected Error while closing socket...') 
    
    def __generateMessageId(self): 
        if self.__messageId == self.MQTT_MAX_INT:
            self.__messageId = 0
        self.__messageId = self.__messageId + 1
        return self.__messageId
    
    def __processHandlersTimeout(self):
        for key, value in self.__resultHandlers.items():
            if((time.time() - value['time']) >= value['timeout']):
                resultHandler = value['handler']
                if(resultHandler):
                    timeOutMsg = value['timeOutMsg']
                    resultHandler(Result(None, 0, (INSTAMSG_ERROR_TIMEOUT, timeOutMsg)))
                    value['handler'] = None
                del self.__resultHandlers[key]
                
    def __sendPingReq(self):
        fixedHeader = MqttFixedHeader(self.PINGREQ)
        pingReqMsg = self.__mqttMsgFactory.message(fixedHeader)
        encodedMsg = self.__mqttEncoder.encode(pingReqMsg)
        self.__sendall(encodedMsg)
    
####Mqtt Codec ###############################################################################

class MqttDecoder:
    READING_FIXED_HEADER_FIRST = 0
    READING_FIXED_HEADER_REMAINING = 1
    READING_VARIABLE_HEADER = 2
    READING_PAYLOAD = 3
    DISCARDING_MESSAGE = 4
    MESSAGE_READY = 5
    BAD = 6
    
    def __init__(self):
        self.__data = ''
        self.__init()
        self.__msgFactory = MqttMsgFactory()
        
    def __state(self):
        return self.__state
    
    def decode(self, data=''):
        if(data):
            data = HexEcoderDecoder.unhexlify(data)
        if(data or self.__data ):
            self.__data = self.__data + data
            if(self.__state == self.READING_FIXED_HEADER_FIRST):
                self.__decodeFixedHeaderFirstByte(self.__getByteStr())
                self.__state = self.READING_FIXED_HEADER_REMAINING
            if(self.__state == self.READING_FIXED_HEADER_REMAINING):
                self.__decodeFixedHeaderRemainingLength()
                if (self.__fixedHeader.messageType == MqttClient.PUBLISH and not self.__variableHeader):
                    self.__initPubVariableHeader()
            if(self.__state == self.READING_VARIABLE_HEADER):
                self.__decodeVariableHeader()
            if(self.__state == self.READING_PAYLOAD):
                bytesRemaining = self.__remainingLength - (self.__bytesConsumedCounter - self.__remainingLengthCounter - 1)
                self.__decodePayload(bytesRemaining)
            if(self.__state == self.DISCARDING_MESSAGE):
                bytesLeftToDiscard = self.__remainingLength - self.__bytesDiscardedCounter
                if (bytesLeftToDiscard <= len(self.__data)):
                    bytesToDiscard = bytesLeftToDiscard
                else: bytesToDiscard = len(self.__data)
                self.__bytesDiscardedCounter = self.__bytesDiscardedCounter + bytesToDiscard
                self.__data = self.__data[0:(bytesToDiscard - 1)] 
                if(self.__bytesDiscardedCounter == self.__remainingLength):
                    e = self.__error
                    self.__init()
                    # Discard any data that is there.
                    self.__data = ''
                    raise MqttDecoderError(e) 
            if(self.__state == self.MESSAGE_READY):
                # returns a tuple of (mqttMessage, dataRemaining)
                mqttMsg = self.__msgFactory.message(self.__fixedHeader, self.__variableHeader, self.__payload)
                self.__init()
                return mqttMsg
            if(self.__state == self.BAD):
                # Discard any data that is there.
                self.__data = ''
                e = self.__error
                self.__init()
                raise MqttFrameError(e)  
        return None 
            
    def __decodeFixedHeaderFirstByte(self, byteStr):
        byte = ord(byteStr)
        msgType = (byte & 0xF0)
        self.__fixedHeader.messageType = msgType 
        self.__fixedHeader.dup = (byte & 0x08) >> 3
        self.__fixedHeader.qos = (byte & 0x06) >> 1
        self.__fixedHeader.retain = (byte & 0x01)
    
    def __decodeFixedHeaderRemainingLength(self):
            while (self.__data):
                byte = ord(self.__getByteStr())
                self.__remainingLength += (byte & 127) * self.__multiplier
                self.__multiplier *= 128
                self.__remainingLengthCounter = self.__remainingLengthCounter + 1
                if(self.__remainingLengthCounter > 4):
                    self.__state = self.BAD
                    self.__error = ('MqttDecoder: Error in decoding remaining length in message fixed header.') 
                    break
                if((byte & 128) == 0):
                    self.__state = self.READING_VARIABLE_HEADER
                    self.__fixedHeader.remainingLength = self.__remainingLength
                    break
                
    def __initPubVariableHeader(self):
        self.__variableHeader['topicLength'] = None
        self.__variableHeader['messageId'] = None
        self.__variableHeader['topic'] = None
        

    def __decodeVariableHeader(self):
        if self.__fixedHeader.messageType in [MqttClient.CONNECT, MqttClient.SUBSCRIBE, MqttClient.UNSUBSCRIBE, MqttClient.PINGREQ]:
            self.__state = self.DISCARDING_MESSAGE
            self.__error = ('MqttDecoder: Client cannot receive CONNECT, SUBSCRIBE, UNSUBSCRIBE, PINGREQ message type.') 
        elif self.__fixedHeader.messageType == MqttClient.CONNACK:
            if(self.__fixedHeader.remainingLength != 2):
                self.__state = self.BAD
                self.__error = ('MqttDecoder: Mqtt CONNACK message should have remaining length 2 received %s.' % self.__fixedHeader.remainingLength) 
            elif(len(self.__data) < 2):
                pass  # let for more bytes come
            else:
                self.__getByteStr()  # discard reserved byte
                self.__variableHeader['connectReturnCode'] = ord(self.__getByteStr())
                self.__state = self.MESSAGE_READY
        elif self.__fixedHeader.messageType == MqttClient.PROVACK:
            if(len(self.__data) < 2):
                pass  # let for more bytes come
            else:
                self.__getByteStr()  # discard reserved byte
                self.__variableHeader['provisionReturnCode'] = ord(self.__getByteStr())
                self.__state = self.READING_PAYLOAD        
        elif self.__fixedHeader.messageType == MqttClient.SUBACK:
            messageId = self.__decodeMsbLsb()
            if(messageId is not None):
                self.__variableHeader['messageId'] = messageId
                self.__state = self.READING_PAYLOAD
        elif self.__fixedHeader.messageType in [MqttClient.UNSUBACK, MqttClient.PUBACK, MqttClient.PUBREC, MqttClient.PUBCOMP, MqttClient.PUBREL]:
            messageId = self.__decodeMsbLsb()
            if(messageId is not None):
                self.__variableHeader['messageId'] = messageId
                self.__state = self.MESSAGE_READY
        elif self.__fixedHeader.messageType == MqttClient.PUBLISH:
            if(self.__variableHeader['topic'] is None):
                self.__decodeTopic()
            if (self.__fixedHeader.qos > MqttClient.MQTT_QOS0 and self.__variableHeader['topic'] is not None and self.__variableHeader['messageId'] is None):
                self.__variableHeader['messageId'] = self.__decodeMsbLsb()
            if (self.__variableHeader['topic'] is not None and (self.__fixedHeader.qos == MqttClient.MQTT_QOS0 or self.__variableHeader['messageId'] is not None)):
                self.__state = self.READING_PAYLOAD
        elif self.__fixedHeader.messageType in [MqttClient.PINGRESP, MqttClient.DISCONNECT]:
            self.__mqttMsg = self.__msgFactory.message(self.__fixedHeader)
            self.__state = self.MESSAGE_READY
        else:
            self.__state = self.DISCARDING_MESSAGE
            self.__error = ('MqttDecoder: Unrecognised message type.%s' %HexEcoderDecoder.hexlify(str(self.__fixedHeader.messageType))) 
            
    def __decodePayload(self, bytesRemaining):
        paloadBytes = self.__getNBytesStr(bytesRemaining)
        if(paloadBytes is not None):
            if self.__fixedHeader.messageType == MqttClient.SUBACK:
                grantedQos = []
                numberOfBytesConsumed = 0
                while (numberOfBytesConsumed < bytesRemaining):
                    qos = int(ord(paloadBytes[numberOfBytesConsumed]) & 0x03)
                    numberOfBytesConsumed = numberOfBytesConsumed + 1
                    grantedQos.append(qos)
                self.__payload = grantedQos
                self.__state = self.MESSAGE_READY
            elif self.__fixedHeader.messageType in (MqttClient.PUBLISH, MqttClient.PROVACK):
                self.__payload = paloadBytes
                self.__state = self.MESSAGE_READY
    
    def __decodeTopic(self):
        stringLength = self.__variableHeader['topicLength']
        if(stringLength is None):
            stringLength = self.__decodeMsbLsb()
            self.__variableHeader['topicLength'] = stringLength
        if (self.__data and stringLength and (len(self.__data) < stringLength)):
            return None  # wait for more bytes
        else:
            self.__variableHeader['topic'] = self.__getNBytesStr(stringLength)
    
    def __decodeMsbLsb(self):
        if(len(self.__data) < 2):
            return None  # wait for 2 bytes
        else:
            msb = self.__getByteStr()
            lsb = self.__getByteStr()
            intMsbLsb = ord(msb) << 8 | ord(lsb)
        if (intMsbLsb < 0 or intMsbLsb > MqttClient.MQTT_MAX_INT):
            return - 1
        else:
            return intMsbLsb
        
    
    def __getByteStr(self):
        return self.__getNBytesStr(1)
    
    def __getNBytesStr(self, n):
        # gets n or less bytes
        nBytes = self.__data[0:n]
        self.__data = self.__data[n:len(self.__data)]
        self.__bytesConsumedCounter = self.__bytesConsumedCounter + n
        return nBytes
    
    def __init(self):
        self.__state = self.READING_FIXED_HEADER_FIRST
        self.__remainingLength = 0
        self.__multiplier = 1
        self.__remainingLengthCounter = 0
        self.__bytesConsumedCounter = 0
        self.__payloadCounter = 0
        self.__fixedHeader = MqttFixedHeader()
        self.__variableHeader = {}
        self.__payload = None
        self.__mqttMsg = None
        self.__bytesDiscardedCounter = 0 
        self.__error = 'MqttDecoder: Unrecognized __error'

class MqttEncoder:
    def __init__(self):
        pass
    
    def encode(self, mqttMessage):
        msgType = mqttMessage.fixedHeader.messageType
        if msgType == MqttClient.CONNECT:
            return self.__encodeConnectMsg(mqttMessage) 
        elif msgType == MqttClient.CONNACK:
            return self.__encodeConnAckMsg(mqttMessage)
        elif msgType == MqttClient.PUBLISH:
            return self.__encodePublishMsg(mqttMessage)
        elif msgType == MqttClient.SUBSCRIBE:
            return self.__encodeSubscribeMsg(mqttMessage)
        elif msgType == MqttClient.UNSUBSCRIBE:
            return self.__encodeUnsubscribeMsg(mqttMessage)
        elif msgType == MqttClient.SUBACK:
            return self.__encodeSubAckMsg(mqttMessage)
        elif msgType in [MqttClient.UNSUBACK, MqttClient.PUBACK, MqttClient.PUBREC, MqttClient.PUBCOMP, MqttClient.PUBREL]:
            return self.__encodeFixedHeaderAndMessageIdOnlyMsg(mqttMessage)
        elif msgType in [MqttClient.PINGREQ, MqttClient.PINGRESP, MqttClient.DISCONNECT]:
            return self.__encodeFixedHeaderOnlyMsg(mqttMessage)
        else:
            raise MqttEncoderError('MqttEncoder: Unknown message type.%s' %HexEcoderDecoder.hexlify(msgType))
    
    def __encodeConnectMsg(self, mqttConnectMessage):
        if(isinstance(mqttConnectMessage, MqttConnectMsg)):
            variableHeaderSize = 12
            fixedHeader = mqttConnectMessage.fixedHeader
            # Encode Payload
            clientId = self.__encodeStringUtf8(mqttConnectMessage.clientId)
            if(not self.__isValidClientId(clientId)):
                raise ValueError("MqttEncoder: invalid clientId: %s should be less than 23 chars in length."% str(clientId))
            encodedPayload = self.__encodeIntShort(len(clientId)) + clientId
            if(mqttConnectMessage.isWillFlag):
                encodedPayload = encodedPayload + self.__encodeIntShort(len(mqttConnectMessage.willTopic)) + self.__encodeStringUtf8(mqttConnectMessage.willTopic)
                encodedPayload = encodedPayload + self.__encodeIntShort(len(mqttConnectMessage.willMessage)) + self.__encodeStringUtf8(mqttConnectMessage.willMessage)
            if(mqttConnectMessage.hasUserName):
                encodedPayload = encodedPayload + self.__encodeIntShort(len(mqttConnectMessage.username)) + self.__encodeStringUtf8(mqttConnectMessage.username)
            if(mqttConnectMessage.hasPassword):
                encodedPayload = encodedPayload + self.__encodeIntShort(len(mqttConnectMessage.password)) + self.__encodeStringUtf8(mqttConnectMessage.password)
            # Encode Variable Header
            connectFlagsByte = 0;
            if (mqttConnectMessage.hasUserName): 
                connectFlagsByte |= 0x80
            if (mqttConnectMessage.hasPassword):
                connectFlagsByte |= 0x40
            if (mqttConnectMessage.isWillRetain):
                connectFlagsByte |= 0x20
            connectFlagsByte |= (mqttConnectMessage.willQos & 0x03) << 3
            if (mqttConnectMessage.isWillFlag):
                connectFlagsByte |= 0x04
            if (mqttConnectMessage.isCleanSession):
                connectFlagsByte |= 0x02;
            encodedVariableHeader = self.__encodeIntShort(len(mqttConnectMessage.protocolName)) + mqttConnectMessage.protocolName + chr(mqttConnectMessage.version) + chr(connectFlagsByte) + self.__encodeIntShort(mqttConnectMessage.keepAliveTimer)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, encodedPayload) + encodedVariableHeader + encodedPayload
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttConnectMsg.__name__, mqttConnectMessage.__class__.__name__)) 
            
    def __encodeConnAckMsg(self, mqttConnAckMsg):
        if(isinstance(mqttConnAckMsg, MqttConnAckMsg)):
            fixedHeader = mqttConnAckMsg.fixedHeader
            encodedVariableHeader = mqttConnAckMsg.connectReturnCode
            return self.__encodeFixedHeader(fixedHeader, 2, None) + encodedVariableHeader
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttConnAckMsg.__name__, mqttConnAckMsg.__class__.__name__)) 

    def __encodePublishMsg(self, mqttPublishMsg):
        if(isinstance(mqttPublishMsg, MqttPublishMsg)):
            fixedHeader = mqttPublishMsg.fixedHeader
            topic = mqttPublishMsg.topic
            variableHeaderSize = 2 + len(topic) 
            if(fixedHeader.qos > 0):
                variableHeaderSize = variableHeaderSize + 2 
            encodedPayload = mqttPublishMsg.payload
            # Encode Variable Header
            encodedVariableHeader = self.__encodeIntShort(len(topic)) + self.__encodeStringUtf8(topic)
            if (fixedHeader.qos > 0): 
                encodedVariableHeader = encodedVariableHeader + self.__encodeIntShort(mqttPublishMsg.messageId)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, encodedPayload) + encodedVariableHeader + str(encodedPayload)
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPublishMsg.__name__, mqttPublishMsg.__class__.__name__)) 
    
    def __encodeSubscribeMsg(self, mqttSubscribeMsg):
        if(isinstance(mqttSubscribeMsg, MqttSubscribeMsg)):
            fixedHeader = mqttSubscribeMsg.fixedHeader
            variableHeaderSize = 2
            # Encode Payload
            encodedPayload = ''
            topic = mqttSubscribeMsg.payload.get('topic')
            qos = mqttSubscribeMsg.payload.get('qos')
            encodedPayload = encodedPayload + self.__encodeIntShort(len(topic)) + self.__encodeStringUtf8(topic) + str(qos)
            # Encode Variable Header
            encodedVariableHeader = self.__encodeIntShort(mqttSubscribeMsg.messageId)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, encodedPayload) + encodedVariableHeader + encodedPayload
                
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttSubscribeMsg.__name__, mqttSubscribeMsg.__class__.__name__))
    
    def __encodeUnsubscribeMsg(self, mqttUnsubscribeMsg):
        if(isinstance(mqttUnsubscribeMsg, MqttUnsubscribeMsg)):
            fixedHeader = mqttUnsubscribeMsg.fixedHeader
            variableHeaderSize = 2
            # Encode Payload
            encodedPayload = ''
            for topic in mqttUnsubscribeMsg.payload:
                encodedPayload = encodedPayload + self.__encodeIntShort(len(topic)) + self.__encodeStringUtf8(topic)
            # Encode Variable Header
            encodedVariableHeader = self.__encodeIntShort(mqttUnsubscribeMsg.messageId)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, encodedPayload) + encodedVariableHeader + encodedPayload
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttUnsubscribeMsg.__name__, mqttUnsubscribeMsg.__class__.__name__))
    
    def __encodeSubAckMsg(self, mqttSubAckMsg):
        if(isinstance(mqttSubAckMsg, MqttSubAckMsg)):
            fixedHeader = mqttSubAckMsg.fixedHeader
            variableHeaderSize = 2
            # Encode Payload
            encodedPayload = ''
            for qos in mqttSubAckMsg.payload:
                encodedPayload = encodedPayload + str(qos)
            # Encode Variable Header
            encodedVariableHeader = self.__encodeIntShort(mqttSubAckMsg.messageId)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, encodedPayload) + encodedVariableHeader + encodedPayload
            
        else:
            raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttSubAckMsg.__name__, mqttSubAckMsg.__class__.__name__))
    
    def __encodeFixedHeaderAndMessageIdOnlyMsg(self, mqttMessage):
        msgType = mqttMessage.fixedHeader.messageType
        if(isinstance(mqttMessage, MqttUnsubscribeMsg) or isinstance(mqttMessage, MqttPubAckMsg) or isinstance(mqttMessage, MqttPubRecMsg) or isinstance(mqttMessage, MqttPubCompMsg) or isinstance(mqttMessage, MqttPubRelMsg)):
            fixedHeader = mqttMessage.fixedHeader
            variableHeaderSize = 2
            # Encode Variable Header
            encodedVariableHeader = self.__encodeIntShort(mqttMessage.messageId)
            return self.__encodeFixedHeader(fixedHeader, variableHeaderSize, None) + encodedVariableHeader
        else:
            if msgType == MqttClient.UNSUBACK: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttUnsubAckMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.PUBACK: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPubAckMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.PUBREC: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPubRecMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.PUBCOMP: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPubCompMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.PUBREL: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPubRelMsg.__name__, mqttMessage.__class__.__name__))
    
    def __encodeFixedHeaderOnlyMsg(self, mqttMessage):
        msgType = mqttMessage.fixedHeader.messageType
        if(isinstance(mqttMessage, MqttPingReqMsg) or isinstance(mqttMessage, MqttPingRespMsg) or isinstance(mqttMessage, MqttDisconnetMsg)):
            return self.__encodeFixedHeader(mqttMessage.fixedHeader, 0, None)
        else:
            if msgType == MqttClient.PINGREQ: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPingReqMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.PINGRESP: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttPingRespMsg.__name__, mqttMessage.__class__.__name__))
            if msgType == MqttClient.DISCONNECT: raise TypeError('MqttEncoder: Expecting message object of type %s got %s' % (MqttDisconnetMsg.__name__, mqttMessage.__class__.__name__))
    
    def __encodeFixedHeader(self, fixedHeader, variableHeaderSize, encodedPayload):
        if encodedPayload is None:
            length = 0
        else: length = len(encodedPayload)
        encodedRemainingLength = self.__encodeRemainingLength(variableHeaderSize + length)
        return chr(self.__getFixedHeaderFirstByte(fixedHeader)) + encodedRemainingLength
    
    def __getFixedHeaderFirstByte(self, fixedHeader):
        firstByte = fixedHeader.messageType
        if (fixedHeader.dup):
            firstByte |= 0x08;
        firstByte |= fixedHeader.qos << 1;
        if (fixedHeader.retain):
            firstByte |= 0x01;
        return firstByte;
    
    def __encodeRemainingLength(self, num):
        remainingLength = ''
        while 1:
            digit = num % 128
            num /= 128
            if (num > 0):
                digit |= 0x80
            remainingLength += chr(digit) 
            if(num == 0):
                    break
        return  remainingLength   
    
    def __encodeIntShort(self, number): 
        return chr(number / 256) + chr(number % 256)
    
    def __encodeStringUtf8(self, s):
        return str(s)
    
    def __isValidClientId(self, clientId):   
        if (clientId is None):
            return 0
        length = len(clientId)
        return length >= 1 and length <= 23
    
class MqttFixedHeader:
    def __init__(self, messageType=None, qos=0, dup=0, retain=0, remainingLength=0):
        self.messageType = messageType or None
        self.dup = dup or 0
        self.qos = qos or 0
        self.retain = retain or 0
        self.remainingLength = remainingLength or 0
    
    def toString(self):
        return 'fixedHeader=[messageType=%s, dup=%d, qos=%d, retain=%d, remainingLength=%d]' % (str(self.messageType), self.dup, self.qos, self.retain, self.remainingLength)
        
class MqttMsg:
    def __init__(self, fixedHeader, variableHeader=None, payload=None):
        self.fixedHeader = fixedHeader
        self.variableHeader = variableHeader
        self.payload = payload
        
    def toString(self):
        return '%s[[%s] [variableHeader= %s] [payload= %s]]' % (self.__class__.__name__, self.fixedHeader.toString(), str(self.variableHeader), str(self.payload))
        

class MqttConnectMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload):
        MqttMsg.__init__(self, fixedHeader, variableHeader, payload)
        self.fixedHeader = fixedHeader
        self.protocolName = MqttClient.MQTT_PROTOCOL_NAME
        self.version = MqttClient.MQTT_PROTOCOL_VERSION
        self.hasUserName = variableHeader.get('hasUserName')
        self.hasPassword = variableHeader.get('hasPassword')
        self.clientId = payload.get('clientId')
        self.username = payload.get('username')
        self.password = payload.get('password')
        self.isWillRetain = variableHeader.get('isWillRetain')
        self.willQos = variableHeader.get('willQos')
        self.isWillFlag = variableHeader.get('isWillFlag')
        self.isCleanSession = variableHeader.get('isCleanSession')
        self.keepAliveTimer = variableHeader.get('keepAliveTimer')
        self.willTopic = payload.get('willTopic')
        self.willMessage = payload.get('willMessage')
        
class MqttConnAckMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.__variableHeader = variableHeader
        self.connectReturnCode = variableHeader.get('connectReturnCode')
        self.payload = None
        
class MqttProvAckMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.__variableHeader = variableHeader
        self.provisionReturnCode = variableHeader.get('provisionReturnCode')
        self.payload = payload
        
class MqttPingReqMsg(MqttMsg):
    def __init__(self, fixedHeader):
        MqttMsg.__init__(self, fixedHeader)
        self.fixedHeader = fixedHeader
        
class MqttPingRespMsg(MqttMsg):
    def __init__(self, fixedHeader):
        MqttMsg.__init__(self, fixedHeader)
        self.fixedHeader = fixedHeader
        
class MqttDisconnetMsg(MqttMsg):
    def __init__(self, fixedHeader):
        MqttMsg.__init__(self, fixedHeader)
        self.fixedHeader = fixedHeader
        
class MqttPubAckMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        
class MqttPubRecMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        
class MqttPubRelMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')

class MqttPubCompMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')

class MqttPublishMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload):
        MqttMsg.__init__(self, fixedHeader, variableHeader, payload)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        self.topic = variableHeader.get('topic')
        # __payload bytes
        self.payload = payload.strip()

class MqttSubscribeMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload=[]):
        MqttMsg.__init__(self, fixedHeader, variableHeader, payload)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        # __payload = [{"topic":"a/b","qos":1}]
        self.payload = payload

class MqttSubAckMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload=[]):
        MqttMsg.__init__(self, fixedHeader, variableHeader, payload)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        # __payload = [0,1,2]
        self.payload = payload

class MqttUnsubscribeMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader, payload=[]):
        MqttMsg.__init__(self, fixedHeader, variableHeader, payload)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')
        # __payload = [topic0,topic1,topic2]
        self.payload = payload
        
class MqttUnsubAckMsg(MqttMsg):
    def __init__(self, fixedHeader, variableHeader):
        MqttMsg.__init__(self, fixedHeader, variableHeader)
        self.fixedHeader = fixedHeader
        self.messageId = variableHeader.get('messageId')

class MqttMsgFactory:
  
    def message(self, fixedHeader, variableHeader=None, payload=None):
        if fixedHeader.messageType == MqttClient.PINGREQ: 
            return MqttPingReqMsg(fixedHeader)
        elif fixedHeader.messageType == MqttClient.PINGRESP: 
            return MqttPingRespMsg(fixedHeader)
        elif fixedHeader.messageType == MqttClient.DISCONNECT: 
            return MqttDisconnetMsg(fixedHeader)
        elif fixedHeader.messageType == MqttClient.CONNECT:
            return MqttConnectMsg(fixedHeader, variableHeader, payload)
        elif fixedHeader.messageType == MqttClient.CONNACK: 
            return MqttConnAckMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.PUBLISH: 
            return MqttPublishMsg(fixedHeader, variableHeader, payload)
        elif fixedHeader.messageType == MqttClient.PUBACK: 
            return MqttPubAckMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.PUBREC: 
            return MqttPubRecMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.PUBREL: 
            return MqttPubRelMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.PUBCOMP: 
            return MqttPubCompMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.SUBSCRIBE: 
            return MqttSubscribeMsg(fixedHeader, variableHeader, payload)
        elif fixedHeader.messageType == MqttClient.UNSUBSCRIBE: 
            return MqttUnsubscribeMsg(fixedHeader, variableHeader, payload)
        elif fixedHeader.messageType == MqttClient.SUBACK: 
            return MqttSubAckMsg(fixedHeader, variableHeader, payload)
        elif fixedHeader.messageType == MqttClient.UNSUBACK: 
            return MqttUnsubAckMsg(fixedHeader, variableHeader)
        elif fixedHeader.messageType == MqttClient.PROVACK: 
            return MqttProvAckMsg(fixedHeader, variableHeader, payload)
        else:
            return None
        
####HttpClient ###############################################################################    
    
class HTTPResponse:
    __blanklines = ('\r\n', '\n', '') 
    __crlf = '\r\n'
    __continuationChar = '\t'
    __whitespace = " " 
    __readingStatusline = 0
    __readingHeaders = 1
    __readingBody = 2
    __ok = 3
    __continue = 100
    
    def __init__(self, sock, f=None):
        self.__sock = sock
        self.f = f

        
    def response(self):  
        try:
            self.__init()
            data_block = self.__sock.recv(1500)
            while(data_block):
                self.__lines = self.__lines + data_block.split(self.__crlf)
                if(len(self.__lines) > 0):
                    if(self.state == self.__readingStatusline):
                        self.__readStatus()
                        # read till we get a non conitnue (100) response
                        if(self.__state == self.__continue): 
                            self.__state = self.__readingStatusline
                            break
#                             data_block = self.__sock.recv(1500)
                    if(self.__state == self.__readingHeaders):
                        self.__readHeaders()
                    if(self.__readingBody):
                        self.__readBody() 
                        break
                if(self.__sock is not None):
#                     data_block = self.__sock.recv()
                    data_block = self.__sock.recv(1500)
                if not data_block:
                    break
        except Exception, e:
            raise HTTPResponseError(str(e))
        return self

    def end(self):
        try:
            if(self.__sock):
                self.__sock.close()
                self.__sock = None
        except:
            pass
        
    def __init(self):
        self.protocol = None
        self.version = None
        self.status = None
        self.reason = None
        self.length = None
        self.close = None 
        self.headers = {}
        self.body = ""  
        self.state = self.__readingStatusline
        self.__lines = []
        self.__lastHeader = None
        
    def __readStatus(self):
        try:
            statusLine = self.__lines.pop(0)
            [version, status, reason] = statusLine.split(None, 2)
        except ValueError:
            try:
                [version, status] = statusLine.split(None, 1)
                reason = ""
            except ValueError:
                version = ""
        if not version.startswith('HTTP/'):
            raise HTTPResponseError("Invalid HTTP version in response")
        try:
            status = int(status)
            if status < 100 or status > 999:
                raise HTTPResponseError("HTTP status code out of range 100-999.")
        except ValueError:
            raise HTTPResponseError("Invalid HTTP status code.")
        self.status = status
        self.reason = reason.strip()
        try:
            [protocol, ver] = version.split("/", 2)
        except ValueError:
            raise HTTPResponseError("Invalid HTTP version.")
        self.protocol = protocol
        self.version = ver
        if(self.status == self.__continue): 
            self.__state = self.__continue
        else:
            self.__state = self.__readingHeaders
            
        
    def __readHeaders(self):
        n = len(self.__lines)
        i = 0
        while i < n:
            line = self.__lines.pop(0)
            if(self.__islastLine(line)):
                self.state = self.__readingBody
                break
            if(self.__isContinuationLine(line)):
                [a, b] = line.split(self.__continuationChar, 2)
                self.headers[self.__lastHeader].append(b.strip()) 
            else:
                headerTuple = self.__getHeader(line)
                if(headerTuple):
                    self.headers[headerTuple[0]] = headerTuple[1]
                    self.__lastHeader = headerTuple[0]
            i = i + 1
            
    def __islastLine(self, line):
        return line in self.__blanklines
    
    def __isContinuationLine(self, line):
        if(line.find(self.__continuationChar) > 0): return 1
        else: return 0
    
    def __getHeader(self, line):
        i = line.find(':')
        if i > 0:
            header = line[0:i].lower()
            if(i == len(line)):
                headerValue = []
            else:
                headerValue = line[(i + 1):len(line)].strip()
            if(header == 'content-length' and headerValue):
                try:
                    self.length = int(headerValue)
                except ValueError:
                    self.length = None
                else:
                    if self.length < 0:
                        self.length = None   
            return (header, headerValue)
        return None
    
    def __readBody(self):
        try:
            try:
                if(self.length and self.length != 0 and (self.__lines or self.__sock)):
        #             datablock = self.__sock.recv()
                    if(self.__lines):
                        datablock = self.__lines
                        self.__lines = None
                    else:
                        datablock = self.__sock.recv(1500)
                    length = 0
                    while(datablock and length < self.length):
                        if(isinstance(datablock, list)):
                            datablock = ''.join(datablock)
                        length = length + len(datablock)
                        # Only download body to file if status 200
                        if (self.status == 200 and self.f and hasattr(self.f, 'write')):  
                            self.f.write(datablock)
                        else:
                            self.body = self.body + datablock
    #                     datablock = self.__sock.recv()
                        if(length < self.length):
                            datablock = self.__sock.recv(1500)
                        else: break
                    self.end()
                else:
                    self.end()
            except Exception, e:
                raise Exception(str(e))
        finally:
            self.end()
    
class HTTPClient:
        
    def __init__(self, host, port, userAgent='InstaMsg'):
        self.version = '1.1'
        self.__userAgent = userAgent
        self.__addr = (host, port)
        self.__sock = None
        self.__checkAddress()
        self.__boundary = '-----------ThIs_Is_tHe_bouNdaRY_78564$!@'
        self.__tcpBufferSize = 1500
        
    def get(self, url, params={}, headers={}, body=None, timeout=10):
        return self.__request('GET', url, params, headers, body, timeout)
    
    def put(self, url, params={}, headers={}, body=None, timeout=10):
        return self.__request('PUT', url, params, headers, body, timeout)
    
    def post(self, url, params={}, headers={}, body=None, timeout=10):
        return self.__request('POST', url, params, headers, body, timeout)  
    
    def delete(self, url, params={}, headers={}, body=None, timeout=10):
        return self.__request('DELETE', url, params, headers, body, timeout) 
        
    def uploadFile(self, url, filename, params={}, headers={}, timeout=10):
        if(not isinstance(filename, str)): raise ValueError('HTTPClient:: upload filename should be of type str.')
        f = None
        try:
            try:
                headers['Content-Type'] = 'multipart/form-data; boundary=%s' % self.__boundary
                form = self.__encode_multipart_fileupload("file", filename)
                fileSize = self.__getFileSize(filename)
                headers['Content-Length'] = len(''.join(form)) + fileSize
                f = open(filename, 'rb')
                response = self.__request('POST', url, params, headers, f, timeout, form)  
                return response
            except Exception, e:
                if(e.__class__.__name__ == 'HTTPResponseError'):
                    raise HTTPResponseError(str(e))
                raise HTTPClientError("HTTPClient:: %s" % str(e))
        finally:
            if f:
                self.__closeFile(f)  
    
    def downloadFile(self, url, filename, params={}, headers={}, timeout=10):  
        if(not isinstance(filename, str)): raise ValueError('HTTPClient:: download filename should be of type str.')
        f = None
        response = None
        try:
            try:
                tempFileName = '~' + filename
                f = open(tempFileName, 'wb')
                response = self.__request('GET', url, params, headers, timeout=timeout, fileObject=f)
                f.close()
                if(response.status == 200):
                    posix.rename(tempFileName, filename)
                else:
                    posix.unlink(tempFileName)
            except Exception, e:
                if(e.__class__.__name__ == 'HTTPResponseError'):
                    raise HTTPResponseError(str(e))
                raise HTTPClientError("HTTPClient:: %s" % str(e))
        finally:
            if f:
                self.__closeFile(f)
        return response
            
    def __closeFile(self, f):   
        try:
            if(f and hasattr(f, 'close')):
                f.close() 
                f = None      
        except:
            pass 
          
    def __getFileSize(self, filename):
        fileSize = None
        f = None
        try:
            try:
                f = open(filename, 'ab')
                f.seek(0, 2)
                fileSize = f.tell()
            except Exception, e:
                raise Exception(str(e))
        finally:
            if(f and hasattr(f, 'close')):
                f.close()
                f = None
        if(fileSize): return fileSize
        else: raise Exception("HTTPClient:: Unable to determine file size.")
            
    
    def __request(self, method, url, params, headers, body=None, timeout=10, fileUploadForm=None, fileObject=None):
        if(not isinstance(url, str)): raise ValueError('HTTPClient:: url should be of type str.')
        if(not isinstance(params, dict)): raise ValueError('HTTPClient:: params should be of type dictionary.')
        if(not isinstance(headers, dict)): raise ValueError('HTTPClient:: headers should be of type dictionary.')
        if(not isinstance(timeout, int)): raise ValueError('HTTPClient:: timeout should be of type int.')
        if(not(isinstance(body, str) or isinstance(body, file) or body is None)):raise ValueError('HTTPClient:: body should be of type string or file object.')
        try:
            try:
                request = self.__createHttpRequest(method, url, params, headers)
                sizeHint = None
                if(headers.has_key('Content-Length') and isinstance(body, file)):
                    sizeHint = len(request) + headers.get('Content-Length')
                self._sock = Socket(timeout, at2, 0)
                self._sock.connect(self.__addr)
                expect = None
                if(headers.has_key('Expect')):
                    expect = headers['Expect']
                elif(headers.has_key('expect')):
                    expect = headers['expect']
                if(expect and (expect.lower() == '100-continue')):
                    self._sock.sendall(request)
                    httpResponse = HTTPResponse(self._sock, fileObject).response()
                    # Send the remaining body if status 100 received or server that send nothing
                    if(httpResponse.status == 100 or httpResponse.status is None):
                        request = ""
                        self.__send(request, body, fileUploadForm, fileObject, sizeHint)
                        return httpResponse.response()
                    else:
                        raise HTTPResponseError("Expecting status 100, recieved %s" % request.status)
                else:
                    self.__send(request, body, fileUploadForm, fileObject, sizeHint)
                    time.sleep(2)
                    return HTTPResponse(self._sock, fileObject).response()
            except Exception, e:
                if(e.__class__.__name__ == 'HTTPResponseError'):
                    raise HTTPResponseError(str(e))
                raise HTTPClientError("HTTPClient:: %s" % str(e))
        finally:
            try:
                if(self.__sock):
                    self.__sock.close()
                    self.__sock = None
            except:
                pass
    
    def __send(self, request, body=None, fileUploadForm=None, fileObject=None, sizeHint=None):
        if (isinstance(body, str) or body is None): 
            request = request + (body or "")
            if(request):
                self._sock.sendall(request)
        else:
            if(fileUploadForm and len(fileUploadForm) == 2):
                blocksize = 1500    
                if(sizeHint <= self.__tcpBufferSize):
                    if hasattr(body, 'read'): 
                        request = request + ''.join(fileUploadForm[0]) + ''.join(body.read(blocksize)) + ''.join(fileUploadForm[1])
                        self._sock.sendall(request)
                else:
                    request = request + ''.join(fileUploadForm[0])
                    self._sock.sendall(request)
                    partNumber = 1
                    if hasattr(body, 'read'): 
                        partData = body.read(blocksize)
                        while partData:
        #                             self._sock.sendMultiPart(partData, partNumber)
                            self._sock.sendall(partData)
                            partData = body.read(blocksize)
                    if(fileUploadForm and len(fileUploadForm) == 2):
        #                         self._sock.sendMultiPart(fileUploadForm[1], partNumber + 1)
                        self._sock.sendall(fileUploadForm[1])
        #                 self._sock.sendHTTP(self.__addr, request)
    
    def __createHttpRequest(self, method, url, params={}, headers={}):
        url = url + self.__createQueryString(params)
        headers = self.__createHeaderString(headers)
        request = "%s %s %s" % (method, url, headers)
        return request
        
    def __createQueryString(self, params={}):
        i = 0
        query = ''
        for key, value in params.items():
            if(i == 0): 
                query = query + '?%s=%s' % (str(key), str(value))
                i = 1
            else:
                query = query + "&%s=%s" % (str(key), str(value))
        return query
    
    def __createHeaderString(self, headers={}): 
            headerStr = "HTTP/%s\r\nHost: %s\r\n" % (self.version, self.__addr[0])
            headers['Connection'] = 'close'  # Only close is supported
            headers['User-Agent'] = self.__userAgent
            for header, values in headers.items():
                if(isinstance(values, list)):
                    headerStr = headerStr + "%s: %s\r\n" % (header, '\r\n\t'.join([str(v) for v in values]))
                else:
                    headerStr = headerStr + "%s: %s\r\n" % (str(header), str(values))
            return headerStr + "\r\n"
        
    def __encode_multipart_fileupload(self, fieldname, filename, contentType='application/octet-stream'):
        formPrefix = []
        crlf = '\r\n'
        formPrefix.append("--" + self.__boundary)
        formPrefix.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (fieldname, filename))
        formPrefix.append('Content-Type: %s' % contentType)
        formPrefix.append('')
        formPrefix.append('')
        return (crlf.join(formPrefix), (crlf + '--' + self.__boundary + '--' + crlf))
            
    def __checkAddress(self):
        if (not self.__addr[0] and not self.__addr[1] and not isinstance(self._addr[1], int)):
            raise ValueError("HTTPClient:: Not a valid HTTP host or port value: %s, %d" % (self.__addr[0], self.__addr[1]))
        
####Socket class ###############################################################################
class Socket:
    default_keep_alive = 0
    maxconn = 6
    connected = 0
    accepting = 0
    closing = 0
    addr = None
    socketStates = {}
    socketStates[0] = "Socket in Closed state."
    socketStates[1] = "Socket with an active data transfer connection."
    socketStates[2] = "Socket suspended."
    socketStates[3] = "Socket suspended with pending data."
    socketStates[4] = "Socket listening."
    socketStates[5] = "Socket with an incoming connection. Waiting for the accept or shutdown command."
    
    def __init__(self, timeout, at, keepAlive=default_keep_alive, ssl=0, encoding = 0):
        if(keepAlive < 0 or keepAlive > 240): raise ValueError("Keep alive should be between 0-240")
        self._timeout = timeout or 10  # sec
        self._keepAlive = keepAlive 
        self._listenAutoRsp = 0
        self._sockno = None
        self.connected = 0
        self.__at = at
        self.__ssl = ssl
        self.__encoding = encoding
        if(ssl):
            self.maxconn = 1
            self._sockno = 1
            self._cipherSuite = 0
            self._authMode = 0
            self.__enableSslSocket()
            self.__configureSslSocketSecurity()
        self.__configureSocket()
            
    def __get_socketno(self):
        sockStates = self.__at.socketStatus(ssl=self.__ssl)
        for sockState in sockStates:
            ss = sockState.split(',')
            if ss[1] == '0':
                return int(ss[0])
        return None
    
    def __enableSslSocket(self):
        try:
            self.__at.enableSslSocket(connId=self._sockno, enableSsl=1)
        except:
            raise SocketConfigError('Unable to enable ssl socket %d' % self._sockno)
        
    def __configureSslSocketSecurity(self):
        try:
            self.__at.configureSslSocketSecurity(connId=self._sockno, cipherSuite=self._cipherSuite, authMode=self._authMode)
        except:
            raise SocketConfigError('Unable to configure ssl socket security %d' % self._sockno)
    
    def __configureSocket(self):
        try:
            self._sockno = self.__get_socketno()
            if(self._sockno):
                self.__at.configureSocket(connId=self._sockno, ssl=self.__ssl, pktSz=512, connTo=self._timeout * 10, keepAlive=self._keepAlive, listenAutoRsp=self._listenAutoRsp, timeout=self._timeout+2, encoding=self.__encoding)
            else:
                raise SocketMaxCountError('All sockets in use. Total number of socket cannot exceed %d.' % self.maxconn)
        except Exception, e:
            raise SocketConfigError('Unable to configure socket - %s' % str(e))
        
    def __socketStatus(self):
        try:
            status = self.__at.socketStatus(self.__ssl, self._sockno)
            return int(status.split(',')[1])
        except:
            return 0
    
    def connect(self, addr):
        try:
            cmd = self.__at.sendCmd('AT#SS')
        except:
            pass
        try:
            self.__at.initGPRSConnection()
            self.addr = addr
            self.__at.connectSocket(self._sockno, addr, ssl=self.__ssl, timeout=self._timeout + 3)
            self.connected = 1
        except(SocketMaxCountError, SocketConfigError), msg:
            raise SocketError(str(msg))
        except:
            raise SocketError('Unable to connect to remote host %s' % str(addr))
        
    def listen(self, addr):
        # Telit module only allows one connection at a time on a listening socket.
        try:
            self.__at.initGPRSConnection()
            self.addr = addr
            self._listenAutoRsp = 1
            self.__configureSocket(self._sockno, ssl=self.__ssl)
            self.__at.socketListen(self._sockno, 1, addr(1), timeout=self._timeout + 3)
            self.connected = 1
            self.accepting = 1
        except(SocketMaxCountError, SocketConfigError), msg:
            raise SocketError(str(msg))
        except:
            raise SocketError('Unable to bind to %s .' % str(addr))
        
    def accept(self):
        try:
            self.__at.socketAccept(self._sockno)
        except:
            raise SocketError('Error in connection accept.')  
                     
    def close(self):
        try:
            cmd = self.__at.sendCmd('AT#SS')
        except:
            pass
        tries = 3
        while(tries > 0):
            try:
                tries = tries - 1
                socketStatus = self.__socketStatus()
                if(socketStatus == 0):return
                if(self.accepting):
                    self.__at.socketListen(self._sockno, 0, self.addr[1], self._timeout) 
                    self.accepting = 0   
                try:
                    #read data before closing. If status 3 closing socket will raise error.
                    self.__at.socketRecv(self._sockno, 1500, self._timeout + 3, self.__ssl)
                except:
                    pass
                self.__at.closeSocket(self._sockno, self._timeout, self.__ssl)
                self.connected = 0
                break
            except:
                if(tries == 0):
                    raise SocketError('Unable to close socket %d' % self._sockno)
  
    def recv(self, bufsize):
        try:
            ss = self.__socketStatus()
            if(ss == 0):raise SocketError(self.socketStates[ss])
            if(ss == 3):
                if(bufsize > 1500 or bufsize < 0):bufsize = 1500
                data = self.__at.socketRecv(self._sockno, bufsize, self._timeout + 3, self.__ssl)
                return data
            else:
                return ''
        except self.__at.timeout:
            raise SocketTimeoutError('Timed out.')
        except Exception, e:
            raise SocketError('Error in recv data - %s' % str(e))

    def send(self, data):
        try:
            ss = self.__socketStatus()
            if(ss == 0):raise SocketError(self.socketStates[ss])
            data = data[:1500]
            return self.__at.socketSend(self._sockno, data, len(data), self._timeout + 3,self.__ssl, 0)
        except self.__at.timeout:
            raise SocketTimeoutError('Timed out.')
        except Exception, e:
            raise SocketError('Error in send data - %s' % str(e))
                 
    def sendall(self, data):
        try:
            ss = self.__socketStatus()
            if(ss == 0):raise SocketError(self.socketStates[ss])
            return self.__at.socketSend(self._sockno, data, len(data), self._timeout + 3, self.__ssl, 0)
        except self.__at.timeout:
            raise SocketTimeoutError('Timed out.')
        except Exception, e:
            raise SocketError('Error in sendall - %s' % str(e)) 


#####Time##################################################################################  
class TimeHelper:

    def __init__(self):
        self.error = TimeHelperError;
        
    def asctime(self):
        try:
            return at.getRtcTime()
        except Exception, e:
            raise self.error('Unable to get time. %s' % repr(e))    
    
    def getTimeAndOffset(self):
        try:
            t = self.asctime()
            now = self.localtime(t)
            timestr = "%04d%02d%02d%01d%02d%02d%02d" % (now[0], now[1], (now[2]), (now[6]), now[3], now[4], now[5])
            offset = str(self.__getOffset(t))
            return [timestr, offset]
        except Exception, e:
            raise self.error('Unable to parse time.')
        
    def localtime(self, time=None):
        if(time is None):
            time = self.asctime()
        t = time[0:-3].split(',')
        date = map(int, t[0].split('/'))
        time = map(int, t[1].split(':'))
        date[0] = date[0] + 2000
        time.append(self.weekDay(date)[0])
        return (date + time)
    
    def weekDay(self, date):
        year = date[0]
        month = date[1]
        day = date[2]
        offset = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        week = {0:'Sunday',
                  1:'Monday',
                  2:'Tuesday',
                  3:'Wednesday',
                  4:'Thursday',
                  5:'Friday',
                  6:'Saturday'}
        afterFeb = 1
        if month > 2: afterFeb = 0
        aux = year - 1700 - afterFeb
        # dayOfWeek for 1700/1/1 = 5, Friday
        dayOfWeek = 5
        # partial sum of days betweem current date and 1700/1/1
        dayOfWeek = dayOfWeek + (aux + afterFeb) * 365                  
        # leap year correction    
        dayOfWeek = dayOfWeek + aux / 4 - aux / 100 + (aux + 100) / 400     
        # sum monthly and day offsets
        dayOfWeek = dayOfWeek + offset[month - 1] + (day - 1) 
        dayOfWeek = dayOfWeek % 7
        return dayOfWeek, week[dayOfWeek]
    
    def __getOffset(self, time):
        offset = int(time[-3:]) * 15 * 60
        return offset
    
#####Modem Initialization#########################################################################
class Modem:
    DEFAULT_NTP_PORT = 23
    MODEM_STATE_SET_SIM_DETECT = 1
    MODEM_STATE_SET_SIM_PIN = 2
    MODEM_STATE_INIT_NETWORK = 3
    MODEM_STATE_SET_GPRS_CONTEXT = 4
    MODEM_STATE_OK = 5
    
    def __init__(self, settings, onDebugMessageCallBack=None):  
        if(onDebugMessageCallBack is not None and not callable(onDebugMessageCallBack)): raise ValueError('[Modem]:: onDebugMessageCallBack should be a callable object.') 
        try:
            self.__onDebugMessageCallBack = onDebugMessageCallBack
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Configuring modem...")
            self.__initOptions(settings)
            self.__state = self.MODEM_STATE_SET_SIM_DETECT
            self.init()
            self.__setPowerMode()
            self.__setFireWall() 
            self.__initGPRSConnection()
            if (self.ntpServer):
                self.__setNtp()
            else:
                self.__enableNetworkTime()
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Configured successfully with settings: %s" % str(self.settings()))
        except Exception, e:
            raise ModemError("[Modem]:: Error while initializing modem. %s" % str(e))
        
    def init(self):
        self.__init()
        
    def getState(self):
        return self.__state
    
    def getSignalQuality(self):
        try:
            return at.getSignalQuality()
        except:
            return - 1
    
    def settings(self):
        try:
            return {
                 'state':self.__state,
                 'imei':self.imei,
                 'model':self.model,
                 'firmware':self.firmware,
                 'power_mode':self.powerMode,
                 'subscriber_number':self.subscriberNumber,
                 'antenna_status':self.__getAntennaStatus(),
                 'signal_quality': self.getSignalQuality(),
                 'ntp_server': self.ntpServer,
                 'sim_detection_mode':self.simDetectionMode,
                 'sim_pin':self.simPin,
                 'gprs_apn':self.gprsApn,
                 'gprs_userid':self.gprsUserId,
                 'gprs_pswd':self.gprsPwd,
                 'firewall_addresses': self.firewallAddresses
                 }
        except:
            return {}
        
    def __getAntennaStatus(self):
        try:
            s = "Unable to determine antenna status. "
            if(self.antennaStatus is 0):
                return  "0 - Antenna Connected."
            elif(self.antennaStatus is 1):
                return "1 - Antenna connector short circuited to ground."
            elif(self.antennaStatus is 2):
                return "2 - Antenna connector short circuited to power."
            elif(self.antennaStatus is 3):
                return "3 - Antenna not detected (open)."
            else:
                return s
        except:
            return s
        
    def __initOptions(self, options):
        if(options.has_key('logLevel')):
            self.__logLevel = options.get('logLevel')
        else:self.__logLevel = 0
        if(options.has_key('firewall_addresses')):
            self.firewallAddresses = options['firewall_addresses']
        else: self.firewallAddresses = None
        if(options.has_key('ntp_server')):
            self.ntpServer = options['ntp_server']
            if(options.has_key('ntp_port')):
                self.ntpPort = options['ntp_port']
            else: self.ntpPort = self.DEFAULT_NTP_PORT
        else: 
            self.ntpServer, self.ntpPort = None, None
        if(options.has_key('sim_detection_mode')):
            self.simDetectionMode = options.get('sim_detection_mode')
        else:self.simDetectionMode = 1  
        if(options.has_key('sim_pin')):
            self.simPin = options.get('sim_pin')
        else:self.simPin = 1    
        if(options.has_key('gprs_apn')):
            self.gprsApn = options.get('gprs_apn')
        else:self.gprsApn = ''    
        if(options.has_key('gprs_userid')):
            self.gprsUserId = options.get('gprs_userid')
        else:self.gprsUserId = '' 
        if(options.has_key('gprs_pswd')):
            self.gprsPwd = options.get('gprs_pswd')
        else:self.gprsPwd = '' 
        
    def __init(self, retry=20):
        try:
            if(retry <= 0): retry = 1
            self.model = at.getModel()
            self.imei = at.getIMEI()
            self.firmware = at.getFirmwareVersion()
            self.powerMode = at.getPowerMode()
            self.subscriberNumber = at.subscriberNumber()
            self.antennaStatus = at.getAntennaStatus()
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Setting extended AT error code...')
            if(not at.setExtendedErrorCode()): 
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Unable to set extended AT error code.')
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Checking and initializing SIM...')
            if (self.__state == self.MODEM_STATE_SET_SIM_DETECT):
                if( not at.initSimDetect(self.simDetectionMode, retry)): 
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Unable to initialize SIM.')
                    return self.__state
                else:
                    self.__state = self.MODEM_STATE_SET_SIM_PIN
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: SIM Detected.')
            if (self.__state == self.MODEM_STATE_SET_SIM_PIN):
                if(not at.initPin(self.simPin, retry)): 
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Unable to set SIM PIN.')
                    return self.__state
                else:
                    self.__state = self.MODEM_STATE_INIT_NETWORK
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: SIM OK.')
            if (self.__state == self.MODEM_STATE_INIT_NETWORK):
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Checking and initializing Network...')
                if(not at.initNetwork(retry)): 
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Unable to initialize Network.')
                    return self.__state
                else:
                    self.__state = self.MODEM_STATE_SET_GPRS_CONTEXT
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Network OK.')
            if (self.__state == self.MODEM_STATE_SET_GPRS_CONTEXT):
                self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Checking and initializing GPRS settings...')
                if(not at.initGPRS(1, self.gprsApn, self.gprsUserId, self.gprsPwd, retry)): 
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Unable to initialize GPRS context.')
                    return self.__state
                else:
                    self.__state = self.MODEM_STATE_OK
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: GPRS Settings OK.')
                    self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Modem OK.')
        except Exception, e:
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[Modem]:: Error configuring modem. %s. Continuing without it..." % str(e))
    
    def __setNtp(self):
        try:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Configuring NTP server...")
            at.setNtpSever(self.ntpServer, self.ntpPort or 123)
        except(ATError, ATTimeoutError):
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Unable to configure NTP server. Enabling Network Time...")
            self.__enableNetworkTime()
                    
    def __enableNetworkTime(self):
        try:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Enabling auto update network time...")
            at.setAutoTimeZoneUpdateFromNetwork()
            at.setAutoDateTimeUpdateFromNetwork()
        except(instamsg.ATError, instamsg.ATTimeoutError):
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[Modem]:: Unable to set auto sync time from network. Continuing without it...")
    
    def __setPowerMode(self):
        try:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Disabling power saving mode...")
            if(at.getPowerMode() is not 1):
                at.setPowerMode(1)
        except:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Unable to disable power saving mode. Continuing without it...")
            
    def __initGPRSConnection(self):
            self.__log(INSTAMSG_LOG_LEVEL_INFO, '[Modem]:: Checking and initializing GPRS connection...')
            gprs = at.initGPRSConnection(pdpContextId=1)
            if(gprs):
                self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: GPRS OK.")
            else:
                self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[Modem]:: Unable to initialize GPRS connection.Continuing without it..")
    
    def __setFireWall(self):
        try:
            self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Dropping all firewall rules...")
            at.dropAllFireWallRules() 
            if(self.firewallAddresses):
                self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Initializing firewall...")
                for address in self.firewallAddresses:
                    at.addToFireWall(address[0], address[1])
                self.__log(INSTAMSG_LOG_LEVEL_INFO, "[Modem]:: Firewall ser. Settings are: %s" % str(at.getFireWallSettings()))
        except:
            self.__log(INSTAMSG_LOG_LEVEL_ERROR, "[Modem]:: Unable to set firewall. Continuing without it...")
    
    def __log(self, level, msg):
        try:
            if(level <= self.__logLevel):
                if(self.__onDebugMessageCallBack):
                    self.__onDebugMessageCallBack(level, msg) 
        except:
            pass

#####AT Functions#########################################################################
class At:
    def __init__(self, mdm=1):
        self.timeout = ATTimeoutError
        self.error = ATError
        if(mdm == 2):
            self.__mdm = MDM2
        else:
            self.__mdm = MDM
    
    def sendCmd(self, cmd, timeOut=2, expected='\r\nOK\r\n', addCR=1, sendByte=0):
        try:
            if (timeOut <= 0): timeOut = 1
            try:
                if(sendByte):
                    r = -1
                    for b in cmd:
                        r = self.__mdm.sendbyte(b,0)
                        if (r < 0):
                            break
                    if (addCR == 1):
                        r = self.__mdm.sendbyte(0x0d,0)
                else:
                    if (addCR == 1):
                        r = self.__mdm.send(cmd + '\r', 5)
                    else:
                        r = self.__mdm.send(cmd, 5)
            finally:
                if (r < 0):
                    raise self.timeout('Send "%s" timed out.' % cmd)
            timer = time.time() + timeOut
            response = cmd + self.__mdm.read()
            while (timeOut > 0 and (not expected or response.find(expected) == -1)):
                response = response + self.__mdm.read()
                timeOut = timer - time.time()
            if(response.find(expected) == -1):
                if (timeOut > 0):
                    raise self.error('Expected response "%s" not received.' % expected.strip())
                else:
                    raise self.timeout('%s receive timed out for %s.' % (self.__mdm.__class__.__name__, cmd))
            if(response.find('ERROR') > 0):
                raise self.error('%s ERROR response received for "%s":%s' % (self.__mdm.__class__.__name__, cmd, "".join(response.split("\r\n")))) 
            else:
                if(response.find("SRING:") >= 0):
                   r = response.split('\r\n')
                   response = '%s\r\n' % r[0] + '\r\n'.join(r[3:])
                return response
        except self.error, e:
            raise self.error(str(e))
        except self.timeout, e:
            raise self.timeout(str(e))
        except Exception, e:
            raise self.error("UnexpectedError, command %s failed. %s" % (cmd, str(e)))
    
    # Module AT commands
    
    def setSmsMode(self,mode=0):
        try:
            response = self.sendCmd('AT#SMSMODE?',5)
            if(response.find('#SMSMODE: %d' % mode) < 0):
                self.sendCmd('AT#SMSMODE=%d' % mode,5)
            return 1
        except Exception,e:
            print "[At:] Error in setSmsMode: %s" % str(e)
            return 0
    
    def setSmsMsgFormat(self,format=1):
        response = self.sendCmd('AT+CMGF?',5)
        if(response.find('+CMGF: %d' % format) < 0):
            self.sendCmd('AT+CMGF=%d' % format,5)
        return 1
        
    def getSmsMsgFormat(self):
        response = self.sendCmd('AT+CMGF?',5)
        if(response.find('+CMGF: 1') < 0):
            return 0
        else : return 1
            
    def getSmses(self, format, status=0):
        s = {0:"REC UNREAD",1:"REC READ", 2:"STO UNSENT", 3:"STO SENT", 4:"ALL"}
        if (format == 1):
            status = s[status]
            cmd = 'AT+CMGL="%s"' % str(status)
        else:
            cmd = 'AT+CMGL=%d' % status
        resp = self.sendCmd(cmd,10)
        respArray= resp.split("\r\n")
        smses = []
        i = 0
        lenRespArray = len(respArray)
        while(i < lenRespArray):
            if (respArray[i].find("AT+CMGL") >= 0):
                pass
            elif (respArray[i].find("+CMGL") >= 0):
                smses.append(respArray[i+1])
            i = i + 1
        
        return smses
    
    def getSms(self, index):
        return self.sendCmd('AT+CMGR=%d' % index,5).split('\r\n')[2]
        
    def deleteSms(self,index=1, delflag =0):
        self.sendCmd('AT+CMGD=%d,%d' % (index, delflag),10)
        return 1
        
    def reboot(self):
        try:
            self.sendCmd('AT#REBOOT')
            return 1
        except Exception,e:
            print "[At:] Error in reboot: %s" % str(e)
            return 0
        
    def factoryReset(self):
        try:
            self.sendCmd('AT&F')
            return 1
        except:
            return 0
     
    def getManufacturerIdentification(self):
        try:
            return self.sendCmd('AT+GMI', 1).split('\r\n')[1]
        except:
            return ''
            
    def getModel(self):
        try:
            return self.sendCmd('AT+GMM', 1).split('\r\n')[1]
        except:
            return ''
    
    def getFirmwareVersion(self):
        try:
            return self.sendCmd('AT+GMR', 1).split('\r\n')[1]
        except:
            return ''
    
    def getSignalQuality(self):
        try:
            return self.sendCmd('AT+CSQ', 1).split('\r\n')[1].replace('+CSQ: ', '').split(',')
        except:
            return []
        
    def subscriberNumber(self):
        try:
            return self.sendCmd('AT+CNUM', 1).split('\r\n')[1].replace('+CNUM: ', '').split(',')
        except:
            return []
    # Python Script AT commands
    
    def setTemperatureMonitor(self, mode, urcmode=1, action=1, hysteresis=255, gpio=None):
    #    parameters: (0,1),(0,1),(0-7),(0-255),(1-8)
        try:
            cmd = 'AT#TEMPMON=%d,%d,%d,%d' % (mode, urcmode, action, hysteresis)
            if(gpio): cmd = cmd + ',%d' % gpio
            self.sendCmd(cmd)
            return mode
        except:
            return -1
    
    def getTemperature(self):
        try:
            return self.sendCmd('AT#TEMPMON=1').split('\r\n')[1].replace('#TEMPMEAS: ', '').split(',')
        except:
            return ''
    
    def setFlowControl(self, value=0):
        try:
            resp = self.sendCmd('AT&K?')
            if(resp.find('00%d' % value) < 0):
                resp = self.sendCmd('AT&K=%d' % value)
            return 1
        except:
            return -1
        
    def setCmux(self, mode=0, baudrate=9600):
        try:
            resp = self.sendCmd('AT#CMUXSCR?')
            if(resp.find('#CMUXSCR: %d' % mode) < 0 or resp.find('#CMUXSCR: %d,%d' % (mode, baudrate)) < 0):
                resp = self.sendCmd('AT#CMUXSCR=%d,%d' % (mode, baudrate))
            return 1
        except:
            return -1
        
    def getAntennaStatus(self):
    # 0 - antenna connected.
    # 1 - antenna connector short circuited to ground.
    # 2 - antenna connector short circuited to power.
    # 3 - antenna not detected (open).
        try:
            return int(self.sendCmd('AT#GSMAD=3', 10).split('\r\n')[1].split(':')[1])
        except:
            return -1
        
    def getActiveScript(self):
        resp = self.sendCmd('AT#ESCRIPT?', 1).split('\r\n')
        expectedResponse = '#ESCRIPT: '
        activeScript = ''
        for r in resp:
            if(r.find(expectedResponse) == 0):    
                activeScript = r.replace(expectedResponse, '').replace('"', '')
                break
        return activeScript
        
    def getfilelist(self):
        resp = self.sendCmd('AT#LSCRIPT', 1).split('\r\n')
        fileList, expectedResponse = {}, '#LSCRIPT: '
        for r in resp:
            if(r.find(expectedResponse) == 0):
                fileinfo = r.replace(expectedResponse, '')
                if(fileinfo.find('free bytes') == 0):
                    fileinfo = fileinfo.replace('free bytes', 'free_bytes').split(':')
                if(fileinfo.find('decoded_seed') == 0):
                    fileinfo = fileinfo.replace('decoded_seed', '')
                else:
                    fileinfo = fileinfo.replace('"', '').split(',')
                if(len(fileinfo) == 2):
                    fileList['name'] = fileList[fileinfo[0]] 
                    fileList['size'] = int(fileinfo[1])
        return fileList
    
    def deleteFile(self, filename):
        resp = self.sendCmd('AT#DSCRIPT = "%s"' % str(filename)).split('\r\n')
        return resp
    
    # Time AT commands
    
    def getRtcTime(self):
        return self.sendCmd('AT+CCLK?', 1).split('\r\n')[1].split('"')[1]
    
    def setRtcTime(self, time):
    # time in "yy/MM/dd,hh:mm:ss±zz"
    # zz is time zone (indicates the difference, expressed in quarter of an hour, 
    # between the local time and GMT; two last digits are mandatory), range is -47..+48
        return self.sendCmd('AT+CCLK = "%s"' % time)
    
    def setDateFormat(self, mode=1, auxmode=1):
        return self.sendCmd('AT+CSDF=%d,%d' % (mode, auxmode))
    
    def setAutoTimeZoneUpdateFromNetwork(self, value=1):
        resp = self.sendCmd('AT+CTZU?')
        if(resp.find('+CTZU: %d' % value) < 0):
            resp = self.sendCmd('AT+CTZU=%d' % value)
        return resp
    
    def setAutoDateTimeUpdateFromNetwork(self, value=7, mode=0):
        resp = self.sendCmd('AT#NITZ?')
        if(resp.find('#NITZ: %d,%d' % (value, mode)) < 0):
            resp = self.sendCmd('AT#NITZ=%d,%d' % (value, mode))
        return resp
    
    def setNtpSever(self, ip='ntp.ioeye.com', port=123):
        resp = self.sendCmd('AT#NTP?')
        if(resp.find('#NTP="%s",%d,%d,%d' % (ip, port, 1, 5)) < 0):
            resp = self.sendCmd('AT#NTP="%s",%d,%d,%d' % (ip, port, 1, 5))
        return resp
    
    def setPowerMode(self, mode=1):
    # 0 - minimum functionality, NON-CYCLIC SLEEP mode: in this mode, the AT interface is not accessible. Consequently, once you have set <fun> level 0, do not send further characters. Otherwise these characters remain in the input buffer and may delay the output of an unsolicited result code. The first wake-up event, or rising RTS line, stops power saving and takes the ME back to full functionality level <fun>=1.
    # 1 - mobile full functionality with power saving disabled (factory default)
    # 2 - disable TX
    # 4 - disable either TX and RX
    # 5 - mobile full functionality with power saving enabled
        resp = self.getPowerMode(self)
        if(resp != mode):
            return self.sendCmd('AT+CFUN= %d' % (mode))  
        return resp
    
    def setInterfaceStyle(self):
        if(self.sendCmd('AT#SELINT?', 1).find('AT#SELINT: 2') > 0): return 1
        else:self.sendCmd('AT#SELINT=2', 1)
    
    def getPowerMode(self):
        return int(self.sendCmd('AT+CFUN?').split('\r\n')[1].split(':')[1])
    
    def getBatteryStatus(self):
        return self.sendCmd('AT+CBC').split('\r\n')[1].replace('+CBC: ', '').split(',')
    
    def getFireWallSettings(self):
        return self.sendCmd('AT#FRWL?')
    
    def addToFireWall(self, ip, subnet):
        cmdValue = 'AT#FRWL=1,"%s","%s"' % (ip, subnet)
        return self.sendCmd(cmdValue)
    
    def removeFromFireWall(self, ip, subnet):
        cmdValue = 'AT#FRWL=0,"%s","%s"' % (ip, subnet)
        return self.sendCmd(cmdValue)
    
    def dropAllFireWallRules(self):
        return self.sendCmd('AT#FRWL=2')
    
    def getIMEI(self, retry=20):
        imei = ''
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(5)
                retry = retry - 1
                imei = self.sendCmd('AT+CGSN').split('\r\n')[1]
                if(imei): break
            except Exception,e:
                print "[At:] Error in getIMEI: %s" % str(e)
                continue
        return imei
    
    def initSimDetect(self, simDetectMode=2, retry=20):  
        if simDetectMode < 0 or simDetectMode > 2: return 0
        success = 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(5)
                retry = retry - 1
                response = self.sendCmd('AT#SIMDET?', 5)
                if (response.find(str(simDetectMode) + ',') > 0):
                    success = 1
                    break
                else:
                    self.sendCmd('AT#SIMDET=' + str(simDetectMode) , 5)
                    success = 1
                    break
            except Exception,e:
                print "[At:] Error in initSimDetect: %s" % str(e)
                continue
        return success
    
    def initPin(self, pin='', retry=20):  
        success = 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(5)
                retry = retry - 1
                response = self.sendCmd('AT+CPIN?', 5)
                if (response.find('READY') > 0):
                    success = 1
                    break
                if (response.find('SIM PIN') > 0):
                    self.sendCmd('AT+CPIN=' + pin, 5)
                    success = 1
                    break
            except Exception,e:
                print "[At:] Error in initPin: %s" % str(e)
                continue
        return success
    
    def setExtendedErrorCode(self):
        try:
            response = self.sendCmd('AT+CMEE?', 5)
            if (response.find('+CMEE: 0') > 0):
                self.sendCmd('AT+CMEE=2', 5)
            return 1
        except:
            return 0
        
    def initNetwork(self, retry=20):
        success = 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(5)
                retry = retry - 1
                response = self.sendCmd('AT+CREG?', 5)
                if (response.find('+CREG: 0,1') > 0 or response.find('+CREG: 0,5') > 0):
                    success = 1
                    break
            except Exception,e:
                print "[At:] Error in initNetwork: %s" % str(e)
                continue
        return success  
    
    def getNetworkStatus(self):
        try:
            return self.sendCmd('AT#MONI', 5).split("\r\n")[1].replace('#MONI: ', '')
        except:
            return ""
        
    def initGPRS(self, pdpContextId=1, apn='', userid='', passw='', retry=20):
        success = 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(3)
                retry = retry - 1
                self.sendCmd('AT+CGDCONT=%d,"IP","%s";#USERID="%s";#PASSW="%s"' % (pdpContextId, apn, userid, passw))    
                self.sendCmd('AT+CGATT?', 5, '+CGATT: 1')
                self.setGPRSContextConfig()
                success = 1
                break
            except Exception,e:
                print "[At:] Error in initGPRS: %s" % str(e)
                continue
        return success  
    
    def activateGPRSContext(self, pdpContextId=1, retry=20):
    # "Activates the GPRS context for internet."
        success = 0
        if(pdpContextId > 5 or pdpContextId < 1): return 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(3)
                retry = retry - 1
                self.sendCmd('AT#SGACT=%d,1' % pdpContextId, 1, 'IP')
                success = 1
                break
            except Exception,e:
                print "[At:] Error in activateGPRSContext: %s" % str(e)
                continue
        return success  
    
    def deactivateGPRSContext(self, pdpContextId=1, retry=20):
    # "Activates the GPRS context for internet."
        success = 0
        if(pdpContextId > 5 or pdpContextId < 1): return 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(3)
                retry = retry - 1
                self.sendCmd('AT#SGACT=%d,0' % pdpContextId, 1)
                success = 1
                break
            except Exception,e:
                print "[At:] Error in deactivateGPRSContext: %s" % str(e)
                continue
        return success 
    
    def setGPRSAutoAttach(self, value=1):
        resp = self.sendCmd('AT#AUTOATT?')
        if(resp.find('#AUTOATT: %d' % value) < 0):
            cmdValue = 'AT#AUTOATT=%d' % value
            resp = self.sendCmd(cmdValue)
        return resp
    
    def getGPRSContextStatus(self, pdpContextId=1, retry=5):  
        status = 0
        if(retry <= 0): retry = 1
        while (retry > 0):
            try:
                time.sleep(3)
                retry = retry - 1
                if(self.sendCmd('AT#SGACT?', 5).find('#SGACT: %d,1' % pdpContextId) > 0): status = 1
                break
            except Exception,e:
                print "[At:] Error in getGPRSContextStatus: %s" % str(e)
                continue
        return status  
    
    def initGPRSConnection(self, pdpContextId=1, retry=20, drop=0):
    # Set drop=1 if you want to drop existing GPRS context create new one.
        try:
            status = 0
            if(retry <= 0): retry = 1
            status = self.getGPRSContextStatus(pdpContextId, 1)
            while((not status or drop) and retry > 0):
                retry = retry - 1
                if(status == 0):
                    self.activateGPRSContext(1)
                elif(status == 1 and drop == 1):
                    self.deactivateGPRSContext(pdpContextId, 1)
                    self.activateGPRSContext(pdpContextId, 1)
                drop = 0
                status = self.getGPRSContextStatus(pdpContextId, 1)
            return status
        except Exception,e:
            print "[At:] Error in initGPRSConnection: %s" % str(e)
            return 0
        
    def getGPRSAddress(self, connId=1):
        resp = self.sendCmd('AT+CGPADDR=', 1).split('\r\n')
        i, expectedResponse = 0, "+CGPADDR: %d" % connId
        for r in resp:
            i = i + 1
            if(r.find(expectedResponse) == 0):
                res = r.split(',')
                return res[1]
                break
        return ''
    
    def setGPRSContextConfig(self, pdpContextId=1, retry=15, delay=180):
        self.sendCmd('AT#SGACTCFG=%d,%d,%d' % (pdpContextId, retry, delay))
        
    def getRemainingMemorySpace(self):
        resp = self.sendCmd('AT#LSCRIPT').split('\r\n')
        for r in resp:
            if(r.find('#LSCRIPT: free bytes:') == 0):
                res = r.split(' ')
                return res[3]
        return ''
      
    def enableSslSocket(self, connId=1, enableSsl=1):
        resp = self.sendCmd('AT#SSLEN?')
        if(resp.find('#SSLEN: 1,0') >= 0): 
            self.sendCmd('AT#SSLEN=%d,%d' % (connId, enableSsl))
     
    def configureSslSocketSecurity(self, connId=1, cipherSuite=0, authMode=0):
        if (self.sendCmd('AT#SSLS=1').find('#SSLEN: 1,1') >= 0):
            self.sendCmd('AT#SSLSECCFG=%d,%d,%d' % (connId, cipherSuite, authMode))
 
    def configureSocket(self, connId, ssl=0, cid=1, pktSz=512, maxTo=0, connTo=600, txTo=50, keepAlive=0, listenAutoRsp=0, timeout=62, encoding=0):
    # connId(1-6),cid(0-5),pktSz(0-1500),maxTo(0-65535),connTo(10-1200),txTo(0-255)
    # keepAlive(0 – 240)min
        if(ssl):
            if (self.sendCmd('AT#SSLS=1').find('#SSLEN: 1,1') >= 0):
                self.sendCmd('AT#SSLCFG=%d,%d,%d,%d,%d,%d' % (connId, cid, pktSz, maxTo, connTo, txTo),timeout)
        else:
            self.sendCmd('AT#SCFG=%d,%d,%d,%d,%d,%d' % (connId, cid, pktSz, maxTo, connTo, txTo),timeout)
        self.sendCmd('AT#SCFGEXT= %d,0,%d,%d,%d' % (connId, encoding, keepAlive, listenAutoRsp),timeout)
        
    def connectSocket(self, connId, addr, ssl=0, proto=0, closureType=0, IPort=0, timeout=60):
        connMode = 1  # always connect in command mode
        if(ssl):
            self.sendCmd('AT#SSLD=%d,%d,"%s",%d,%d' % (connId, addr[1], addr[0], closureType, connMode), timeout)
        else:
            self.sendCmd('AT#SD=%d,%d,%d,"%s",%d,%d,%d' % (connId, proto, addr[1], addr[0], closureType, IPort, connMode), timeout)
        
    
    def closeSocket(self, connId, timeout, ssl=0):
        if(ssl):
            self.sendCmd('AT#SSLH=%d' % connId, timeout)
        else:
            self.sendCmd('AT#SH=%d' % connId, timeout)
        
    def socketRecv(self, connId, maxByte, timeout, ssl=0):
        #receives data in hex mode
        if(ssl):
            resp = self.sendCmd('AT#SSLRECV=%d,%d' % (connId, maxByte), timeout).strip('\r\nOK\r\n').split('\r\n')
            i, expectedResponse = 0, "#SSLRECV:"
        else:
            cmd = self.sendCmd('AT#SRECV=%d,%d' % (connId, maxByte), timeout)
            resp = cmd.strip('\r\nOK\r\n').split('\r\n')
            i, expectedResponse = 0, "#SRECV: %d" % connId
        for r in resp:
            i = i + 1
            if(r.find(expectedResponse) == 0):
                break
        return '\r\n'.join(resp[i:len(resp)])
    
    def socketSend(self, connId, data, bytestosend, timeout, ssl=0, multiPart=0):
    # bytestosend(1-1500)
        while(data):
            partData = data[:1500]
            sendDataSize = len(partData)
            try:
                if(ssl):
                    self.sendCmd('AT#SSLSENDEXT=%d,%d' % (connId, sendDataSize), 1, '')
                else:
                    self.sendCmd('AT#SSENDEXT=%d,%d' % (connId, sendDataSize), 1, '')
                self.sendCmd(partData, timeout, expected='OK\r\n', addCR=0, sendByte=0)
            except:
                pass    
            data = data[sendDataSize:]
        return bytestosend

    def socketStatus(self, ssl=0, connId=None):
        if(ssl):
            if(connId):
                return self.sendCmd('AT#SSLS=1',5).split('\r\n')[connId].replace('#SSLS: ', '')
            else:
                return self.sendCmd('AT#SSLS=1',5).replace('#SSLS: ', '').split('\r\n')[1:7]            
        else:
            cmd = self.sendCmd('AT#SS',5)
            if(connId):
                return cmd.split('\r\n')[connId].replace('#SS: ', '')
            else:
                return cmd.replace('#SS: ', '').split('\r\n')[1:7]
    
    def suspendSocket(self):   
        self.sendCmd('+++')
        time.sleep(2)
    
    def resumeSocket(self, connId,ssl=0):
        if(ssl):
            self.sendCmd('AT#SSLO=%d' % connId)
        else:
            self.sendCmd('AT#SO=%d' % connId)
        
    def socketInfo(self, connId):
        return self.sendCmd('AT#SI=%d' % connId).split('\r\n')[1].replace('#SI: ', '').split(',')
    
    def socketListen(self, connId, listenState, listenPort, closureType=0, timeout=60):
        self.sendCmd('AT#SL=%d,%d,%d,%d' % (connId, listenState, listenPort, closureType), timeout)
        
    def socketAccept(self, connId, connMode=1):
        self.sendCmd('AT#SA=%d,%d' % (connId, connMode))
    
    def socketBase64(self, connId, enc, dec):
        self.sendCmd('#AT#BASE64=%d,%d,%d' % (connId, enc, dec))
        
class HexEcoderDecoder:
    @staticmethod
    def hexlify(data):
        a = []
        for x in data:
            a.append("%02X" % (ord(x)))
        return ''.join(a)
    @staticmethod
    def unhexlify(data):
        a = []
        for i in range(0, len(data), 2):
            a.append(chr(int(data[i:i + 2], 16)))   
        return ''.join(a) 
    
class Sha256(object):
    SHA_BLOCKSIZE = 64
    SHA_DIGESTSIZE = 32
    digest_size = digestsize = SHA_DIGESTSIZE
    block_size = SHA_BLOCKSIZE
    ROR = lambda self, x, y: (((x & 0xffffffff) >> (y & 31)) | (x << (32 - (y & 31)))) & 0xffffffff
    Ch = lambda self, x, y, z: (z ^ (x & (y ^ z)))
    Maj = lambda self, x, y, z: (((x | y) & z) | (x & y))
    S = lambda self, x, n: self.ROR(x, n)
    R = lambda self, x, n: (x & 0xffffffff) >> n
    Sigma0 = lambda self, x: (self.S(x, 2) ^ self.S(x, 13) ^ self.S(x, 22))
    Sigma1 = lambda self, x: (self.S(x, 6) ^ self.S(x, 11) ^ self.S(x, 25))
    Gamma0 = lambda self, x: (self.S(x, 7) ^ self.S(x, 18) ^ self.R(x, 3))
    Gamma1 = lambda self, x: (self.S(x, 17) ^ self.S(x, 19) ^ self.R(x, 10))

    def __init__(self, s=None):
        self._sha = self.sha_init()
        if s:
            self.sha_update(self._sha, self.getbuf(s))
    
    def update(self, s):
        self.sha_update(self._sha, self.getbuf(s))
    
    def digest(self):
        return self.sha_final(self._sha.copy())[:self._sha['digestsize']]
    
    def hexdigest(self):
        return ''.join(['%.2x' % ord(i) for i in self.digest()])

    def copy(self):
        new = Sha256.__new__(Sha256)
        new._sha = self._sha.copy()
        return new
    
    def new_shaobject(self):
        return {
            'digest': [0]*8,
            'count_lo': 0,
            'count_hi': 0,
            'data': [0]* self.SHA_BLOCKSIZE,
            'local': 0,
            'digestsize': 0
        }
    
    def sha_transform(self, sha_info):
        W = []
        
        d = sha_info['data']
        for i in xrange(0,16):
            W.append( (d[4*i]<<24) + (d[4*i+1]<<16) + (d[4*i+2]<<8) + d[4*i+3])
        
        for i in xrange(16,64):
            W.append( (self.Gamma1(W[i - 2]) + W[i - 7] + self.Gamma0(W[i - 15]) + W[i - 16]) & 0xffffffff )
        
        ss = sha_info['digest'][:]
        
        def RND(a,b,c,d,e,f,g,h,i,ki):
            t0 = h + self.Sigma1(e) + self.Ch(e, f, g) + ki + W[i];
            t1 = self.Sigma0(a) + self.Maj(a, b, c);
            d += t0;
            h  = t0 + t1;
            return d & 0xffffffff, h & 0xffffffff
        
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],0,0x428a2f98);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],1,0x71374491);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],2,0xb5c0fbcf);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],3,0xe9b5dba5);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],4,0x3956c25b);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],5,0x59f111f1);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],6,0x923f82a4);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],7,0xab1c5ed5);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],8,0xd807aa98);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],9,0x12835b01);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],10,0x243185be);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],11,0x550c7dc3);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],12,0x72be5d74);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],13,0x80deb1fe);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],14,0x9bdc06a7);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],15,0xc19bf174);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],16,0xe49b69c1);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],17,0xefbe4786);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],18,0x0fc19dc6);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],19,0x240ca1cc);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],20,0x2de92c6f);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],21,0x4a7484aa);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],22,0x5cb0a9dc);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],23,0x76f988da);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],24,0x983e5152);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],25,0xa831c66d);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],26,0xb00327c8);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],27,0xbf597fc7);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],28,0xc6e00bf3);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],29,0xd5a79147);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],30,0x06ca6351);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],31,0x14292967);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],32,0x27b70a85);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],33,0x2e1b2138);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],34,0x4d2c6dfc);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],35,0x53380d13);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],36,0x650a7354);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],37,0x766a0abb);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],38,0x81c2c92e);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],39,0x92722c85);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],40,0xa2bfe8a1);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],41,0xa81a664b);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],42,0xc24b8b70);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],43,0xc76c51a3);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],44,0xd192e819);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],45,0xd6990624);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],46,0xf40e3585);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],47,0x106aa070);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],48,0x19a4c116);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],49,0x1e376c08);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],50,0x2748774c);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],51,0x34b0bcb5);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],52,0x391c0cb3);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],53,0x4ed8aa4a);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],54,0x5b9cca4f);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],55,0x682e6ff3);
        ss[3], ss[7] = RND(ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],56,0x748f82ee);
        ss[2], ss[6] = RND(ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],57,0x78a5636f);
        ss[1], ss[5] = RND(ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],ss[5],58,0x84c87814);
        ss[0], ss[4] = RND(ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],ss[4],59,0x8cc70208);
        ss[7], ss[3] = RND(ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],ss[3],60,0x90befffa);
        ss[6], ss[2] = RND(ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],ss[2],61,0xa4506ceb);
        ss[5], ss[1] = RND(ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],ss[1],62,0xbef9a3f7);
        ss[4], ss[0] = RND(ss[1],ss[2],ss[3],ss[4],ss[5],ss[6],ss[7],ss[0],63,0xc67178f2);
        
        dig = []
        for i, x in enumerate(sha_info['digest']):
            dig.append( (x + ss[i]) & 0xffffffff )
        sha_info['digest'] = dig
    
    def sha_init(self):
        sha_info = self.new_shaobject()
        sha_info['digest'] = [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]
        sha_info['count_lo'] = 0
        sha_info['count_hi'] = 0
        sha_info['local'] = 0
        sha_info['digestsize'] = 32
        return sha_info
    
    def getbuf(self, s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return str(s)
        else:
            return buffer(s)
    
    def sha_update(self, sha_info, buffer):
        count = len(buffer)
        buffer_idx = 0
        clo = (sha_info['count_lo'] + (count << 3)) & 0xffffffff
        if clo < sha_info['count_lo']:
            sha_info['count_hi'] += 1
        sha_info['count_lo'] = clo
        
        sha_info['count_hi'] += (count >> 29)
        
        if sha_info['local']:
            i = self.SHA_BLOCKSIZE - sha_info['local']
            if i > count:
                i = count
            
            # copy buffer
            for x in enumerate(buffer[buffer_idx:buffer_idx+i]):
                sha_info['data'][sha_info['local']+x[0]] = self.unpack(x[1])
            
            count -= i
            buffer_idx += i
            
            sha_info['local'] += i
            if sha_info['local'] == self.SHA_BLOCKSIZE:
                self.sha_transform(sha_info)
                sha_info['local'] = 0
            else:
                return
        
        while count >= self.SHA_BLOCKSIZE:
            # copy buffer
            sha_info['data'] = [self.unpack(c) for c in buffer[buffer_idx:buffer_idx + self.SHA_BLOCKSIZE]]
            count -= self.SHA_BLOCKSIZE
            buffer_idx += self.SHA_BLOCKSIZE
            self.sha_transform(sha_info)
            
        
        # copy buffer
        pos = sha_info['local']
        sha_info['data'][pos:pos+count] = [self.unpack(c) for c in buffer[buffer_idx:buffer_idx + count]]
        sha_info['local'] = count
    
    def sha_final(self, sha_info):
        lo_bit_count = sha_info['count_lo']
        hi_bit_count = sha_info['count_hi']
        count = (lo_bit_count >> 3) & 0x3f
        sha_info['data'][count] = 0x80;
        count += 1
        if count > self.SHA_BLOCKSIZE - 8:
            # zero the bytes in data after the count
            sha_info['data'] = sha_info['data'][:count] + ([0] * (self.SHA_BLOCKSIZE - count))
            self.sha_transform(sha_info)
            # zero bytes in data
            sha_info['data'] = [0] * self.SHA_BLOCKSIZE
        else:
            sha_info['data'] = sha_info['data'][:count] + ([0] * (self.SHA_BLOCKSIZE - count))
        
        sha_info['data'][56] = (hi_bit_count >> 24) & 0xff
        sha_info['data'][57] = (hi_bit_count >> 16) & 0xff
        sha_info['data'][58] = (hi_bit_count >>  8) & 0xff
        sha_info['data'][59] = (hi_bit_count >>  0) & 0xff
        sha_info['data'][60] = (lo_bit_count >> 24) & 0xff
        sha_info['data'][61] = (lo_bit_count >> 16) & 0xff
        sha_info['data'][62] = (lo_bit_count >>  8) & 0xff
        sha_info['data'][63] = (lo_bit_count >>  0) & 0xff
        
        self.sha_transform(sha_info)
        
        dig = []
        for i in sha_info['digest']:
            dig.extend([ ((i>>24) & 0xff), ((i>>16) & 0xff), ((i>>8) & 0xff), (i & 0xff) ])
        return ''.join([chr(i) for i in dig])
    
    def unpack(self, s):
        return ord(s)
    
    def test(self):
        a_str = "just a test string"
        assert 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' == Sha256().hexdigest()
        assert 'd7b553c6f09ac85d142415f857c5310f3bbbe7cdd787cce4b985acedd585266f' == Sha256(a_str).hexdigest()
        assert '8113ebf33c97daa9998762aacafe750c7cefc2b2f173c90c59663a57fe626f21' == Sha256(a_str*7).hexdigest()
        
        s = Sha256(a_str)
        s.update(a_str)
        assert '03d9963e05a094593190b6fc794cb1a3e1ac7d7883f0b5855268afeccc70d461' == s.hexdigest()


class Sha224(Sha256):
    digest_size = digestsize = 28

    def __init__(self, s=None):
        self._sha = self.sha224_init()
        if s:
            self.sha_update(self._sha, self.getbuf(s))

    def copy(self):
        new = Sha224.__new__(Sha224)
        new._sha = self._sha.copy()
        return new
    
    def sha224_init(self):
        sha_info = self.new_shaobject()
        sha_info['digest'] = [0xc1059ed8, 0x367cd507, 0x3070dd17, 0xf70e5939, 0xffc00b31, 0x68581511, 0x64f98fa7, 0xbefa4fa4]
        sha_info['count_lo'] = 0
        sha_info['count_hi'] = 0
        sha_info['local'] = 0
        sha_info['digestsize'] = 28
        return sha_info

#####Exceptions######################################################################## 
    
class ATError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class ATTimeoutError(IOError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class TimeHelperError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class SocketError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class SocketTimeoutError(IOError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class SocketMaxCountError(IOError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class SocketConfigError(IOError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class ModemError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)

class MqttClientError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class MqttFrameError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class MqttDecoderError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)

class MqttEncoderError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class HTTPResponseError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class HTTPClientError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class InstaMsgError(Exception):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class InstaMsgSubError(InstaMsgError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class InstaMsgUnSubError(InstaMsgError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class InstaMsgPubError(InstaMsgError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class InstaMsgSendError(InstaMsgError):
    def __init__(self, value=''):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
    
at = instamsg.At()
at2 = instamsg.At(mdm=2)

#time = instamsg.TimeHelper()
