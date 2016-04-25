########################################################################################################################
# Volume Tab for use with sonospyGUI.py
########################################################################################################################
# virtualsTab.py copyright (c) 2010-2016 John Chowanec
# mutagen copyright (c) 2005 Joe Wreschnig, Michael Urman (mutagen is Licensed under GPL version 2.0)
# Sonospy Project copyright (c) 2010-2014 Mark Henkelis
#   (specifics for this file: scan.py)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# virtualsTab.py Author: John Chowanec <chowanec@gmail.com>
########################################################################################################################
# TO DO:
# - Build the actual loop.

########################################################################################################################
# IMPORTS FOR PYTHON
########################################################################################################################
import wx
import re
import os
import subprocess
from threading import *
import guiFunctions
from wx.lib.pubsub import setuparg1
from wx.lib.pubsub import pub
import urllib
import socket

socket.setdefaulttimeout(15)

def get_ip_address(ifname):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ip = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, pack('256s', str(ifname[:15])))[20:24])
        return ip
    except:
        return socket.gethostbyname(socket.gethostname())

def get_active_ifaces():
    if os.name == 'nt':
        return [socket.gethostbyname(socket.gethostname())]
    else:
        try:
            rd = open('/proc/net/route').readlines()
        except (IOError, OSError):
            return [socket.gethostbyname(socket.gethostname())]
        net = [line.split('\t')[0:2] for line in rd]
        return [v[0] for v in net if v[1] == '00000000']    

active_ifaces = get_active_ifaces()
ip_address = get_ip_address(active_ifaces[0])

# Comment this out, only doing this to test on a remote machine.
ip_address = '192.168.1.110'
portNum = '50108'

# Get raw zone names from Sonospy
zoneNAME=urllib.urlopen('http://' + ip_address + ':50108/data/deviceData').read()
# Positive look behind, positive look forward 
# http://stackoverflow.com/questions/36827128/stripping-multiple-types-of-strings-from-a-master-string/
zoneNAME = re.findall('(?<=R::).*?(?=_\|_)', zoneNAME)
if len(zoneNAME) < 1:
    guiFunctions.errorMsg("Error!", "You don't have any discoverable zones!")

########################################################################################################################
# VolumePanel: The layout and binding section for the frame.
########################################################################################################################
class VolumePanel(wx.Panel):
    """
    Volume Tab for creating subset databases.
    """
    #----------------------------------------------------------------------
    def __init__(self, parent):
        """"""
        wx.Panel.__init__(self, parent=parent, id=wx.ID_ANY)

        panel = self
        sizer = wx.GridBagSizer(13, 4)
        self.currentDirectory = os.getcwd()

        xIndex = 0
        curZoneNum = 0

    # -------------------------------------------------------------------------
    # [1] - Server IP address and Port

        label_serverIP = wx.StaticText(panel, label="Server IP/Port:")
        help_serverIP = "The IP address of the running server"
        label_serverIP.SetToolTip(wx.ToolTip(help_serverIP))
        sizer.Add(label_serverIP, pos=(xIndex, 0), flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL|wx.TOP, border=10)
    
        self.tc_serverIP = wx.TextCtrl(panel)
        self.tc_serverIP.SetToolTip(wx.ToolTip(help_serverIP))
        self.tc_serverIP.Value = ip_address
        sizer.Add(self.tc_serverIP, pos=(xIndex, 1), flag=wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER_VERTICAL|wx.TOP, border=10)

        self.tc_serverPort = wx.TextCtrl(panel)
        self.tc_serverPort.SetToolTip(wx.ToolTip(help_serverIP))
        self.tc_serverPort.Value = portNum
        sizer.Add(self.tc_serverPort, pos=(xIndex, 2), flag=wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER_VERTICAL|wx.TOP, border=10).SetMinSize((30,22))

        xIndex +=0
    # -------------------------------------------------------------------------
    # [2] - Sleep Interval
    
        label_CheckInterval = wx.StaticText(panel, label="Vol Check Frequency (sec):")
        help_CheckInterval = "How frequently do you want to check for volume levels?"
        label_CheckInterval.SetToolTip(wx.ToolTip(help_CheckInterval))
        sizer.Add(label_CheckInterval, pos=(xIndex, 3), flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL|wx.TOP, border=10)
        
        self.tc_CheckInterval = wx.TextCtrl(panel)
        self.tc_CheckInterval.SetToolTip(wx.ToolTip(help_CheckInterval))
        self.tc_CheckInterval.Value = '1'
        sizer.Add(self.tc_CheckInterval, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL|wx.TOP, border=10).SetMinSize((30,22))  

        xIndex +=1

    # -------------------------------------------------------------------------
    # [3] - Quiet Hours
        
        self.ck_QuietHours = wx.CheckBox(self, -1, 'Quiet Hours')
        self.ck_QuietHours.SetToolTip(wx.ToolTip("Click here to turn on Quiet Hours"))
        help_QuietHours = "Set time HHMM in 24 hour notation to drop volume. 2300 for example."
        self.ck_QuietHours.Bind(wx.EVT_CHECKBOX, self.quietCkClick)
        sizer.Add(self.ck_QuietHours, pos=(xIndex, 0), flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
            
        self.tc_quietHr = wx.TextCtrl(panel)
        self.tc_quietHr.SetToolTip(wx.ToolTip(help_QuietHours))
        self.tc_quietHr.Value = '2300'
        sizer.Add(self.tc_quietHr, pos=(xIndex, 1), flag=wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER_VERTICAL, border=10)

        xIndex +=1
        
        label_QuietVol = wx.StaticText(panel, label="Quiet Volume:")
        help_QuietVol = "Set desired Quiet Hour max volume."
        label_QuietVol.SetToolTip(wx.ToolTip(help_QuietVol))
        sizer.Add(label_QuietVol, pos=(xIndex, 0), flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
        
        self.quietSlider = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
        self.quietSlider.Bind(wx.EVT_SLIDER, self.quietSliderUpdate)
        sizer.Add(self.quietSlider, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
        
        self.tc_QuietVol = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
        self.tc_QuietVol.SetToolTip(wx.ToolTip(help_QuietVol))
        sizer.Add(self.tc_QuietVol, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))        
        
        if self.tc_QuietVol.Value == "":
            self.tc_QuietVol.SetValue(str(self.quietSlider.GetValue()))
    
        self.tc_quietHr.Disable()
        label_QuietVol.Disable()
        self.quietSlider.Disable()
        self.tc_QuietVol.Disable()

        xIndex +=2

    # -------------------------------------------------------------------------
    # [4] - Mute Hours
            
        self.ck_MuteHours = wx.CheckBox(self, -1, 'Mute Hours')
        self.ck_MuteHours.SetToolTip(wx.ToolTip("Click here to turn on Mute Hours"))
        self.ck_MuteHours.Bind(wx.EVT_CHECKBOX, self.muteHoursClick)
        sizer.Add(self.ck_MuteHours, pos=(xIndex, 0), flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
                
        self.tc_MuteHr = wx.TextCtrl(panel)
        self.tc_MuteHr.SetToolTip(wx.ToolTip("Time to start muting zones. 0000 = midnight, for instance"))
        self.tc_MuteHr.Value = '0'
        sizer.Add(self.tc_MuteHr, pos=(xIndex, 1), flag=wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER_VERTICAL, border=10)
    
        self.tc_MuteHrStop = wx.TextCtrl(panel)
        self.tc_MuteHrStop.SetToolTip(wx.ToolTip("Time to end muting zones. 700 = 7am, for instance."))
        self.tc_MuteHrStop.Value = '700'
        sizer.Add(self.tc_MuteHrStop, pos=(xIndex, 2), flag=wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER_VERTICAL, border=10)
        
        self.tc_MuteHr.Disable()
        self.tc_MuteHrStop.Disable()
        
        xIndex +=1

    # -------------------------------------------------------------------------
    # [5] Make Header Columns 

        self.label_ProxyName = wx.StaticText(panel, label="Zone")
        self.label_UserIndexName = wx.StaticText(panel, label="Max. Volume %")
        sizer.Add(self.label_ProxyName, pos=(xIndex, 0), flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT|wx.TOP, border=10)
        sizer.Add(self.label_UserIndexName, pos=(xIndex, 2), flag=wx.ALIGN_CENTER_VERTICAL|wx.CENTER|wx.TOP, border=10)        
        xIndex +=1
        
    # -------------------------------------------------------------------------
    # [6] Separator line 

        hl_SepLine1 = wx.StaticLine(panel, 0, (250, 50), (300,1))
        sizer.Add(hl_SepLine1, pos=(xIndex, 0), span=(1, 5), flag=wx.EXPAND)
        xIndex +=1

    # -------------------------------------------------------------------------
    # Zones, sliders and max volume
    # -------------------------------------------------------------------------
    # [7,8] - Zone 1
        self.ck_ZONE1 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
        self.ck_ZONE1.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
        self.ck_ZONE1.Bind(wx.EVT_CHECKBOX, self.zone1CkClick)
        sizer.Add(self.ck_ZONE1, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
    
        self.tc_ZONEVOL1 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
        self.tc_ZONEVOL1.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
        sizer.Add(self.tc_ZONEVOL1, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))

        self.sliderZone1 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
        self.sliderZone1.Bind(wx.EVT_SLIDER, self.slider1Update)
        sizer.Add(self.sliderZone1, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        

        if self.tc_ZONEVOL1.Value == "":
            self.tc_ZONEVOL1.SetValue(str(self.sliderZone1.GetValue()))

        self.tc_ZONEVOL1.Disable()
        self.sliderZone1.Disable()
        
        curZoneNum += 1
        xIndex += 2
    # -------------------------------------------------------------------------
    # [9,10] - Zone2
        if curZoneNum < len(zoneNAME):
            self.ck_ZONE2 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE2.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE2.Bind(wx.EVT_CHECKBOX, self.zone2CkClick)
            sizer.Add(self.ck_ZONE2, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
        
            self.tc_ZONEVOL2 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL2.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL2, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
        
            self.sliderZone2 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone2.Bind(wx.EVT_SLIDER, self.slider2Update)
            sizer.Add(self.sliderZone2, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
            
            if self.tc_ZONEVOL2.Value == "":
                self.tc_ZONEVOL2.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL2.Disable()
            self.sliderZone2.Disable()

        curZoneNum += 1  
        xIndex +=2

    # -------------------------------------------------------------------------
    # [10,11] - Zone3
        if curZoneNum < len(zoneNAME):
            self.ck_ZONE3 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE3.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE3.Bind(wx.EVT_CHECKBOX, self.zone3CkClick)            
            sizer.Add(self.ck_ZONE3, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
            
            
            self.tc_ZONEVOL3 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL3.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL3, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
            
            self.sliderZone3 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone3.Bind(wx.EVT_SLIDER, self.slider3Update)
            sizer.Add(self.sliderZone3, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
                
            if self.tc_ZONEVOL3.Value == "":
                self.tc_ZONEVOL3.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL3.Disable()
            self.sliderZone3.Disable()            

        curZoneNum +=1
        xIndex +=2
    
    # -------------------------------------------------------------------------
    # [12,13] - Zone4
        if curZoneNum < len(zoneNAME):
            self.ck_ZONE4 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE4.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE4.Bind(wx.EVT_CHECKBOX, self.zone4CkClick)
            sizer.Add(self.ck_ZONE4, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
            
            self.tc_ZONEVOL4 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL4.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL4, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                
            self.sliderZone4 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone4.Bind(wx.EVT_SLIDER, self.slider4Update)
            sizer.Add(self.sliderZone4, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
    
            if self.tc_ZONEVOL4.Value == "":
                self.tc_ZONEVOL4.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL4.Disable()
            self.sliderZone4.Disable()

        curZoneNum += 1     
        xIndex +=2

    # -------------------------------------------------------------------------
    # [14,15] - Zone5
        if curZoneNum < len(zoneNAME):        
            self.ck_ZONE5 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE5.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            sizer.Add(self.ck_ZONE5, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
            self.ck_ZONE5.Bind(wx.EVT_CHECKBOX, self.zone5CkClick)
                    
            self.tc_ZONEVOL5 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL5.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL5, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                    
            self.sliderZone5 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone5.Bind(wx.EVT_SLIDER, self.slider5Update)
            sizer.Add(self.sliderZone5, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        

            if self.tc_ZONEVOL5.Value == "":
                self.tc_ZONEVOL5.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL5.Disable()
            self.sliderZone5.Disable()

        curZoneNum += 1                    
        xIndex +=2

    # -------------------------------------------------------------------------
    # [16,17] - Zone6
        if curZoneNum < len(zoneNAME):        
            self.ck_ZONE6 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE6.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE6.Bind(wx.EVT_CHECKBOX, self.zone6CkClick)
            sizer.Add(self.ck_ZONE6, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
                    
            self.tc_ZONEVOL6 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL6.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL6, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                    
            self.sliderZone6 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone6.Bind(wx.EVT_SLIDER, self.slider6Update)
            sizer.Add(self.sliderZone6, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
                
            if self.tc_ZONEVOL6.Value == "":
                self.tc_ZONEVOL6.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL6.Disable()
            self.sliderZone6.Disable()        

        curZoneNum += 1                    
        xIndex +=2
    # -------------------------------------------------------------------------
    # [18,19] - Zone7
        if curZoneNum < len(zoneNAME):        
            self.ck_ZONE7 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE7.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE7.Bind(wx.EVT_CHECKBOX, self.zone7CkClick)
            sizer.Add(self.ck_ZONE7, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
                    
            self.tc_ZONEVOL7 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL7.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL7, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                    
            self.sliderZone7 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone7.Bind(wx.EVT_SLIDER, self.slider7Update)
            sizer.Add(self.sliderZone7, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
                
            if self.tc_ZONEVOL7.Value == "":
                self.tc_ZONEVOL7.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL7.Disable()
            self.sliderZone7.Disable()            

        curZoneNum += 1                    
        xIndex +=2

    # -------------------------------------------------------------------------
    # [20,21] - Zone8
        if curZoneNum < len(zoneNAME):        
            self.ck_ZONE8 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE8.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE8.Bind(wx.EVT_CHECKBOX, self.zone8CkClick)
            sizer.Add(self.ck_ZONE8, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
                    
            self.tc_ZONEVOL8 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL8.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL8, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                    
            self.sliderZone8 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone8.Bind(wx.EVT_SLIDER, self.slider8Update)
            sizer.Add(self.sliderZone8, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
                
            if self.tc_ZONEVOL8.Value == "":
                self.tc_ZONEVOL8.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL8.Disable()
            self.sliderZone8.Disable()                

        curZoneNum += 1                    
        xIndex +=2

    # -------------------------------------------------------------------------
    # [22,23] - Zone9
        if curZoneNum < len(zoneNAME):        
            self.ck_ZONE9 = wx.CheckBox(self, -1, zoneNAME[curZoneNum])
            self.ck_ZONE9.SetToolTip(wx.ToolTip("Click here to monitor volume for this zone."))
            self.ck_ZONE9.Bind(wx.EVT_CHECKBOX, self.zone9CkClick)
            sizer.Add(self.ck_ZONE9, pos=(xIndex,0), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)
                    
            self.tc_ZONEVOL9 = wx.TextCtrl(panel, -1, "", (0,0), (30,21))
            self.tc_ZONEVOL9.SetToolTip(wx.ToolTip("Set max volume for the zone (0-100)"))
            sizer.Add(self.tc_ZONEVOL9, pos=(xIndex,4), flag=wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10).SetMinSize((30,22))
                    
            self.sliderZone9 = wx.Slider(self, -1, 50, 0, 100, size=(400,10), style=wx.SL_HORIZONTAL)
            self.sliderZone9.Bind(wx.EVT_SLIDER, self.slider9Update)
            sizer.Add(self.sliderZone9, pos=(xIndex,1), span=(2, 3), flag=wx.EXPAND|wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)        
                
            if self.tc_ZONEVOL9.Value == "":
                self.tc_ZONEVOL9.SetValue(str(self.sliderZone1.GetValue()))

            self.tc_ZONEVOL9.Disable()
            self.sliderZone9.Disable()                    

            xIndex +=4

    # -------------------------------------------------------------------------
    # [22,23] - Zone9

        # - LAUNCH BUTTON
        self.bt_Launch = wx.Button(panel, label="Enable Volume Monitor")
        help_bt_Launch = "Click here to enable the volume monitor."
        self.bt_Launch.SetToolTip(wx.ToolTip(help_bt_Launch))
        self.bt_Launch.Bind(wx.EVT_BUTTON, self.launchVolClick, self.bt_Launch)    
    
        # SAVE AS DEFAULTS
        self.bt_SaveDefaults = wx.Button(panel, label="Save Defaults")
        help_SaveDefaults = "Save current settings as default."
        self.bt_SaveDefaults.SetToolTip(wx.ToolTip(help_SaveDefaults))
        self.bt_SaveDefaults.Bind(wx.EVT_BUTTON, self.bt_SaveDefaultsClick, self.bt_SaveDefaults)
    
        sizer.Add(self.bt_Launch, pos=(xIndex,0), span=(1,2), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10)
        sizer.Add(self.bt_SaveDefaults, pos=(xIndex,2), span=(1,3), flag=wx.EXPAND|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=10)

    # -------------------------------------------------------------------------
    # Finalize the sizer
        pub.subscribe(self.setVolumePanel, 'setVolumePanel')
        sizer.AddGrowableCol(1)
        panel.SetSizer(sizer)


    def slider1Update(self, event):
        self.tc_ZONEVOL1.SetValue(str(self.sliderZone1.GetValue()))

    def slider2Update(self, event):
        self.tc_ZONEVOL2.SetValue(str(self.sliderZone2.GetValue()))

    def slider3Update(self, event):
        self.tc_ZONEVOL3.SetValue(str(self.sliderZone3.GetValue()))

    def slider4Update(self, event):
        self.tc_ZONEVOL4.SetValue(str(self.sliderZone4.GetValue()))
        
    def slider5Update(self, event):
        self.tc_ZONEVOL5.SetValue(str(self.sliderZone5.GetValue()))
        
    def slider6Update(self, event):
        self.tc_ZONEVOL6.SetValue(str(self.sliderZone6.GetValue()))

    def slider7Update(self, event):
        self.tc_ZONEVOL7.SetValue(str(self.sliderZone7.GetValue()))

    def slider8Update(self, event):
        self.tc_ZONEVOL8.SetValue(str(self.sliderZone8.GetValue()))
        
    def slider9Update(self, event):
        self.tc_ZONEVOL9.SetValue(str(self.sliderZone9.GetValue()))
        
    def quietSliderUpdate(self, event):
        self.tc_QuietVol.SetValue(str(self.quietSlider.GetValue()))    

    def zone1CkClick(self, event):
        if self.ck_ZONE1.Value == False:
            self.sliderZone1.Disable()
            self.tc_ZONEVOL1.Disable()
        else:
            self.sliderZone1.Enable()
            self.tc_ZONEVOL1.Enable()

    def zone2CkClick(self, event):
        if self.ck_ZONE2.Value == False:
            self.sliderZone2.Disable()
            self.tc_ZONEVOL2.Disable()
        else:
            self.sliderZone2.Enable()
            self.tc_ZONEVOL2.Enable()

    def zone3CkClick(self, event):
        if self.ck_ZONE3.Value == False:
            self.sliderZone3.Disable()
            self.tc_ZONEVOL3.Disable()
        else:
            self.sliderZone3.Enable()
            self.tc_ZONEVOL3.Enable()

    def zone4CkClick(self, event):
        if self.ck_ZONE4.Value == False:
            self.sliderZone4.Disable()
            self.tc_ZONEVOL4.Disable()
        else:
            self.sliderZone4.Enable()
            self.tc_ZONEVOL4.Enable()
    
    def zone5CkClick(self, event):
        if self.ck_ZONE5.Value == False:
            self.sliderZone5.Disable()
            self.tc_ZONEVOL5.Disable()
        else:
            self.sliderZone5.Enable()
            self.tc_ZONEVOL5.Enable()

    def zone6CkClick(self, event):
        if self.ck_ZONE6.Value == False:
            self.sliderZone6.Disable()
            self.tc_ZONEVOL6.Disable()
        else:
            self.sliderZone6.Enable()
            self.tc_ZONEVOL6.Enable()

    def zone7CkClick(self, event):
        if self.ck_ZONE7.Value == False:
            self.sliderZone7.Disable()
            self.tc_ZONEVOL7.Disable()
        else:
            self.sliderZone7.Enable()
            self.tc_ZONEVOL7.Enable()
            
    def zone8CkClick(self, event):
        if self.ck_ZONE8.Value == False:
            self.sliderZone8.Disable()
            self.tc_ZONEVOL8.Disable()
        else:
            self.sliderZone8.Enable()
            self.tc_ZONEVOL8.Enable()

    def zone9CkClick(self, event):
        if self.ck_ZONE9.Value == False:
            self.sliderZone9.Disable()
            self.tc_ZONEVOL9.Disable()
        else:
            self.sliderZone9.Enable()
            self.tc_ZONEVOL9.Enable()

    def quietCkClick(self, event):
        if self.ck_QuietHours.Value == False:
            self.quietSlider.Disable()
            self.tc_QuietVol.Disable()
            self.tc_quietHr.Disable()
        else:
            self.quietSlider.Enable()
            self.tc_QuietVol.Enable()
            self.tc_quietHr.Enable()

    def muteHoursClick(self, event):
        if self.ck_MuteHours.Value == False:
            self.tc_MuteHr.Disable()
            self.tc_MuteHrStop.Disable()
        else:
            self.tc_MuteHr.Enable()
            self.tc_MuteHrStop.Enable()     

    def launchVolClick(self, event):
        if self.bt_Launch.Label == "Enable Volume Monitor":
            self.volMonitor()
            self.bt_Launch.Label = "Disable Volume Monitor"
        else:
            print "Disable Loop Here"
            self.bt_Launch.Label = "Enable Volume Monitor"
            
########################################################################################################################
# setVolumePanel: This is for the pubsub to receive a call to disable or enable the panel buttons.
########################################################################################################################
    def setVolumePanel(self, msg):
        if msg.data == "Disable":
            self.Disable()
        else:
            self.Enable()

########################################################################################################################
# bt_SaveDefaultsClick: A simple function to write out the defaults for the panel to GUIpref.ini
########################################################################################################################
    def bt_SaveDefaultsClick(self, event):
        section = "virtuals"
        guiFunctions.configWrite(section, "type", self.combo_typeOptions.GetCurrentSelection())
        guiFunctions.configWrite(section, "title", self.tc_Title.Value)

        guiFunctions.configWrite(section, "artist", self.tc_Artist.Value)
        guiFunctions.configWrite(section, "albumartist", self.tc_AlbumArtist.Value)
        guiFunctions.configWrite(section, "composer", self.tc_Composer.Value)
        guiFunctions.configWrite(section, "year", self.tc_Year.Value)
        guiFunctions.configWrite(section, "genre", self.tc_Genre.Value)
        guiFunctions.configWrite(section, "cover", self.tc_Cover.Value)
        guiFunctions.configWrite(section, "discnumber", self.tc_DiscNumber.Value)

        folders = ""
        numLines = 0
        maxLines=(int(self.tc_FilesFolders.GetNumberOfLines()))
        while (numLines < maxLines):
            folders += str(self.tc_FilesFolders.GetLineText(numLines))
            numLines += 1
            if numLines != maxLines:
                folders += "|"
        guiFunctions.configWrite(section, "tracks", folders)


        guiFunctions.statusText(self, "Defaults saved...")

########################################################################################################################
# volMonitor: Enable or disable the volume monitor loop
########################################################################################################################
    def volMonitor(self):
        print "Made it into volMonitor"
        # Steps:
        #
        # ---- Find a python equivalent to curl (urlib.open?)
        #
        # - Check to ensure Sonospy is running.
        # - Setup while loop during #1 = True.
        # - Grab timeout value from ck_Interval
        # - Grab zones set for monitoring from ck_ZONEVOL*
        # - Loop through #4
        # - setup zoneNAME and maxVOLUME
        # - Set the input zone: curl -s http://"$ipADDR":"$portNUM"/data/rendererData?data=R::"$zoneNAME"%20%28ZP%29 &>/dev/null
        # - Grab relevant info about the active zone: INFO=$(curl -s $(echo "http://$ipADDR:$portNUM/data/rendererAction?data=class" | sed 's/ //g'))
        # - Check for current time to get curTIME
        # - Setup loop for curTIME vs. Quiet Hours vs. Mute Hours
        # - Strip INFO to just the Volume number to test against, assign to OUTPUT
        # - If sonospy died, check for OUTPUT != "" or "NOCHANGE::0_|_"
        # - If maxVOLME is not set, set it to 0
        # - Check OUTPUT > maxVOLUME, if true: curl -s http://"$ipADDR":"$portNUM"/data/rendererAction?data=VOLUME::"$maxVOLUME" &>/dev/null
        
    