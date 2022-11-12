#编译AdbWinUsbApi.dll,AdbWinApi.dll
ttps://github.com/PixysOS-Beta/development.git
https://codeload.github.com/PixysOS-Beta/development/zip/fd4b83b4f2765d8dc30dee51ba4928b4453b5ac1

error1./usb/api/adb_api_instance.h
#pragma comment(lib,"Setupapi.lib")
typedef void* ADBAPIINSTANCEHANDLE; 

error2.stdafx.h
注释掉_WIN32_WINNT...这些宏
