# instamsg-telitpy2.7
This is a client for InstaMsg IoT messaging cloud service to be used on telit modules that use multi threaded python version 2.x. The code had been tested on telit modules that run python version 2.7 and firmware version 13.xx.

## Telit modules supported ##

#### Firmware Version 12.00.xx5: ####

* **HE910 Family**
* HE910 1
* HE910-GA 
* HE910-D
* HE910-EUR / HE910-EUD
* HE910-EUG / HE910-NAG 
* HE910-NAR / HE910-NAD 
* **UE910 Family**
* UE910-EUR / UE910-EUD
* UE910-NAR / UE910-NAD
* **UL865 Family**
* UL865-EUR / UL865-EUD
* UL865-NAR / UL865-NAD
* UL865 N3G 

#### Firmware Version 13.00.xx6: ####

* **GE910 Family** 
* GE910-QUAD
* GE910-GNSS

#### Firmware Version 18.11.004 : ####

* **CE910 Family ** 
* C910-DUAL

## How to compile the python scripts for my telit module? ##
You can use python 2.7.x (intalled on your computer) to compile the python scripts. Its a better practise to compile the instamsg.py script and load the instamsg.pyc file on the module. Use the compileall.py python script in your python installation directory. On windows you can compile it with the following command:

python -v -S C:\Python27\Lib\compileall.py -l -f C:\instamsg-telitpy2.7\src

If you do not want to build and use the library directly you can use the instamsg.pyc in the build folder.

***
## Telit GL86X Setup Guide ##
#### Step 1: Installing RSTerm Plus <br/>  
Please download RSTerm Plus in your windows system from [here](http://www.antrax.de/site/Onlineshop/Downloads/Software-RS-Term-Plus:::370_435_437.htm)  and install it.
#### Step 2: Connecting to GL865 gateway   
* Use a _straight RS232 DB9_ cable and connect the GL865 (Serial Port 0 /ASC0)  to the COM port on your computer. 
* Open RSterm and configure the com port settings `Init > Com-Port`. Set the com port no and baudrate. `Click AT button` and the module should respond with  `OK` 
* Click on `Python tab`. Disable the serial port multiplexer `Python > AT#CMUXSCR=0`  
* Check start mode script by entering `Python > AT#STARTMODESCR?` and send. It should display `#STARTMODESCR: 1,10`	. Else click on `STARTMODESCR = 1,10`  
* Note down the IMEI number of the device. Send the following AT command to the device `AT+CGSN ` 
* Check the Version number of the firmware by sending following AT command to the device `AT+ GMR`. This should be one supported by ioEYE connect. Presently we support version 10.00.xx4

#### Step 3: List Scripts Installed  
* On the header menu click on `Python`
* Click on `AT#LSCRIPT`. This will list all the script files inside the module. Incase of a new module it should not list any files. In case of an old module it will list the files that are loaded on the module. If you want to delete obsolete or old files you can do it by `AT#DSCRIPT`.

#### Step 4: Install Scripts on Module
* Upload the following 9 scripts one by one on the module using `AT#WSCRIPT:`  <br/>
(a) **at.pyo**, (b) **broker.pyo**, (c) **config.pyo**, (d) **exceptions.pyo**, (e) **gateway.pyo**, 
(f) **logger.pyo** (g) **serial.pyo**, (h) **socket.pyo**, (i) **time.pyo**
* Click on` AT#LSCRIPT`. All the nine scripts uploaded should now be listed.
* Enable the script **gateway.pyo** for execution. Click on `AT#ESCRIPT` and select **gateway.pyo**.
* Check if the script is enabled by clicking `AT#ESCRIPT?.` This should display  **gateway.pyo**.

#### Setup Module on ioEYE
* Login to your `ioEYE` account. 
* Click on `Manage`.
* Click on the `Device` link.
* Click `Create New` and enter the `IMEI number` of the module in the S.N field and save the device.

#### Step 6: Connect the device to the Module
* Disconnect the Telit module from your computer and connect it to the serial device via `RS232 cross cable`. 
*  Restart the module power supply.

### Config File Settings
Settings in config file for connect and send data to our server as follows :
* **Network Settings :** Set `GPRS_APN` according to your network provider. <br/>
e.g. www is for vodafone and airtelgprs for airtel.
* **Firewall Settings :** Currently there are no firewall installed.
* **Logging Settings :** We can enable logging on our gateway for troubleshooting. But in case of production it should be off.
* **NTP Settings :** You don’t need to change these settings.
* **Data Logger Settings :**  You don’t need to change these settings.
* **ioEYE Server Settings :** we can change these settings according to our requirement :
      * **Publisher :** It can be TCP or HTTP. If device send data over tcp then it should be tcp or if device send data over http then it should be http.
      * **TCP_HOST Or HTTP HOST :** If device send data over ioeye `test server` then it should be `test.ioeye.com` or in case of `production server` it should be `gateway.ioeye.com`.
      * **TCP_PORT Or HTTP PORT :** We don’t need to change these settings.
* **Serial Port Settings :** 
      * **SERIAL_POLLING_INTERVAL :** This is the interval time in seconds. It means this is the time after which a device poll and send data over ioEYE server.
      * **serial_cmd_list :** These are hex commands for reading data from devices like meters. These varies meter to meter. 
      * **serial_port :** These are serial port settings of gateway.  All options are well defined in config file.
 

***


## Who do I talk to? ##

* Repo owner or admin
* Other community or team contact
