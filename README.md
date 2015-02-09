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

## How do I get set up? ##

* Summary of set up
* Configuration
* Dependencies
* Database configuration
* How to run tests
* Deployment instructions

## Contribution guidelines ##

* Writing tests
* Code review
* Other guidelines

## Who do I talk to? ##

* Repo owner or admin
* Other community or team contact
