#!/usr/bin/env python3
"""A simple gui interface"""
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename

import config

# Expanded 'from pmca.commands.usb import *' and removed unused functions
# from pmca.commands.usb import printStatus, listApps, installApp, checkApk, importDriver, listDevices, listDevices,
# getDevice, infoCommand, installCommand, appSelectionCommand, getFdats, getFdat, firmwareUpdateCommand, updaterShellCommand, firmwareUpdateCommandInternal, guessFirmwareCommand, gpsUpdateCommand, streamingCommand, wifiCommand, senserShellCommand
from pmca.commands.usb import (
    listApps,
    installCommand,
    infoCommand,
    firmwareUpdateCommand,
    updaterShellCommand,
    senserShellCommand,
)

from pmca.platform.backend.senser import SenserPlatformBackend

# Expanded 'from pmca.platform.backend.usb import *' but unused
# from pmca.platform.backend.usb import usb_transfer_socket, usb_transfer_read, usb_transfer_write
from pmca.platform.backend.usb import UsbPlatformBackend
from pmca.platform.tweaks import TweakInterface
from pmca.ui import BackgroundTask, UiRoot, UiFrame, UiDialog, ScrollingText

if getattr(sys, "frozen", False):
    from frozenversion import version
else:
    version = None


class PrintRedirector(object):
    """Redirect writes to a function"""

    def __init__(self, func, parent=None):
        self.func = func
        self.parent = parent

    def write(self, str):
        if self.parent:
            self.parent.write(str)
        self.func(str)

    def flush(self):
        self.parent.flush()


class AppLoadTask(BackgroundTask):
    def doBefore(self):
        self.ui.setAppList([])
        self.ui.appLoadButton.config(state=tk.DISABLED)

    def do(self, arg):
        try:
            print("")
            return list(listApps().values())
        except Exception:
            traceback.print_exc()

    def doAfter(self, result):
        if result:
            self.ui.setAppList(result)
        self.ui.appLoadButton.config(state=tk.NORMAL)


class InfoTask(BackgroundTask):
    """Task to run infoCommand()"""

    def doBefore(self):
        self.ui.infoButton.config(state=tk.DISABLED)

    def do(self, arg):
        try:
            print("")
            infoCommand()
        except Exception:
            traceback.print_exc()

    def doAfter(self, result):
        self.ui.infoButton.config(state=tk.NORMAL)


class InstallTask(BackgroundTask):
    """Task to run installCommand()"""

    def doBefore(self):
        self.ui.installButton.config(state=tk.DISABLED)
        return self.ui.getMode(), self.ui.getSelectedApk(), self.ui.getSelectedApp()

    def do(self, args):
        (mode, apkFilename, app) = args
        try:
            print("")
            if mode == self.ui.MODE_APP and app:
                installCommand(appPackage=app.package)
            elif mode == self.ui.MODE_APK and apkFilename:
                with open(apkFilename, "rb") as f:
                    installCommand(apkFile=f)
            else:
                installCommand()
        except Exception:
            traceback.print_exc()

    def doAfter(self, result):
        self.ui.installButton.config(state=tk.NORMAL)


class FirmwareUpdateTask(BackgroundTask):
    """Task to run firmwareUpdateCommand()"""

    def doBefore(self):
        self.ui.fwUpdateButton.config(state=tk.DISABLED)
        return self.ui.getSelectedDat()

    def do(self, datFile):
        try:
            if datFile:
                print("")
                with open(datFile, "rb") as f:
                    firmwareUpdateCommand(f)
        except Exception:
            traceback.print_exc()

    def doAfter(self, result):
        self.ui.fwUpdateButton.config(state=tk.NORMAL)


class StartPlatformShellTask(BackgroundTask):
    def doBefore(self):
        self.ui.startUpdaterShellButton.config(state=tk.DISABLED)
        self.ui.startSenserShellButton.config(state=tk.DISABLED)

    def do(self, arg):
        try:
            print("")
            self.start()
        except Exception:
            traceback.print_exc()

    def start(self):
        pass

    def launchShell(self, backend):
        backend.start()
        tweaks = TweakInterface(backend)

        if next(tweaks.getTweaks(), None):
            endFlag = threading.Event()
            root = self.ui.master
            root.run(lambda: root.after(0, lambda: TweakDialog(root, tweaks, endFlag)))
            endFlag.wait()
        else:
            print("No tweaks available")

        backend.stop()

    def doAfter(self, result):
        self.ui.startUpdaterShellButton.config(state=tk.NORMAL)
        self.ui.startSenserShellButton.config(state=tk.NORMAL)


class StartUpdaterShellTask(StartPlatformShellTask):
    """Task to run updaterShellCommand() and open TweakDialog"""

    def start(self):
        updaterShellCommand(complete=lambda dev: self.launchShell(UsbPlatformBackend(dev)))


class StartSenserShellTask(StartPlatformShellTask):
    """Task to run senserShellCommand() and open TweakDialog"""

    def start(self):
        senserShellCommand(complete=lambda dev: self.launchShell(SenserPlatformBackend(dev)))


class TweakApplyTask(BackgroundTask):
    """Task to run TweakInterface.apply()"""

    def doBefore(self):
        self.ui.setState(tk.DISABLED)

    def do(self, arg):
        try:
            print("Applying tweaks...")
            self.ui.tweakInterface.apply()
        except Exception:
            traceback.print_exc()

    def doAfter(self, result):
        self.ui.setState(tk.NORMAL)
        self.ui.cancel()


class MainUi(UiRoot):
    """Main window"""

    def __init__(self, title):
        UiRoot.__init__(self)

        self.title(title)
        self.geometry("450x500")
        self["menu"] = tk.Menu(self)

        tabs = ttk.Notebook(self, padding=5)
        tabs.pack(fill="x")

        tabs.add(InfoFrame(self, padding=10), text="Camera info")
        tabs.add(InstallerFrame(self, padding=10), text="Install app")
        tabs.add(UpdaterShellFrame(self, padding=10), text="Tweaks")
        tabs.add(FirmwareFrame(self, padding=10), text="Update firmware")

        docsLink = ttk.Label(self, text="Camera compatibility", foreground="blue", cursor="hand2")
        docsLink.bind("<Button-1>", lambda e: webbrowser.open_new(config.docsUrl + "/devices.html"))
        docsLink.pack(pady=(0, 5))

        self.logText = ScrollingText(self)
        self.logText.text.configure(state=tk.DISABLED)
        self.logText.pack(fill="both", expand=True)

        self.redirectStreams()

    def log(self, msg):
        self.logText.text.configure(state=tk.NORMAL)
        self.logText.text.insert(tk.END, msg)
        self.logText.text.configure(state=tk.DISABLED)
        self.logText.text.see(tk.END)

    def redirectStreams(self):
        for stream in ["stdout", "stderr"]:
            setattr(sys, stream, PrintRedirector(lambda str: self.run(lambda: self.log(str)), getattr(sys, stream)))


class InfoFrame(UiFrame):
    def __init__(self, parent, **kwargs):
        UiFrame.__init__(self, parent, **kwargs)

        self.infoButton = ttk.Button(self, text="Get camera info", command=InfoTask(self).run, padding=5)
        self.infoButton.pack(fill="x")


class InstallerFrame(UiFrame):
    MODE_APP = 0
    MODE_APK = 1

    def __init__(self, parent, **kwargs):
        UiFrame.__init__(self, parent, **kwargs)

        self.modeVar = tk.IntVar(value=self.MODE_APP)

        appFrame = ttk.Labelframe(self, padding=5)
        appFrame["labelwidget"] = ttk.Radiobutton(
            appFrame, text="Select an app from the app list", variable=self.modeVar, value=self.MODE_APP
        )
        appFrame.columnconfigure(0, weight=1)
        appFrame.pack(fill="x")

        self.appCombo = ttk.Combobox(appFrame, state="readonly")
        self.appCombo.bind("<<ComboboxSelected>>", lambda e: self.modeVar.set(self.MODE_APP))
        self.appCombo.grid(row=0, column=0, sticky=tk.W + tk.E)
        self.setAppList([])

        self.appLoadButton = ttk.Button(appFrame, text="Refresh", command=AppLoadTask(self).run)
        self.appLoadButton.grid(row=0, column=1)

        appListLink = ttk.Label(appFrame, text="Source", foreground="blue", cursor="hand2")
        appListLink.bind(
            "<Button-1>",
            lambda e: webbrowser.open_new(
                "https://github.com/" + config.githubAppListUser + "/" + config.githubAppListRepo
            ),
        )
        appListLink.grid(columnspan=2, sticky=tk.W)

        apkFrame = ttk.Labelframe(self, padding=5)
        apkFrame["labelwidget"] = ttk.Radiobutton(
            apkFrame, text="Select an apk", variable=self.modeVar, value=self.MODE_APK
        )
        apkFrame.columnconfigure(0, weight=1)
        apkFrame.pack(fill="x")

        self.apkFile = ttk.Entry(apkFrame)
        self.apkFile.grid(row=0, column=0, sticky=tk.W + tk.E)

        self.apkSelectButton = ttk.Button(apkFrame, text="Open apk...", command=self.openApk)
        self.apkSelectButton.grid(row=0, column=1)

        self.installButton = ttk.Button(self, text="Install selected app", command=InstallTask(self).run, padding=5)
        self.installButton.pack(fill="x", pady=(5, 0))

        self.run(AppLoadTask(self).run)

    def getMode(self):
        return self.modeVar.get()

    def openApk(self):
        fn = askopenfilename(filetypes=[("Apk files", ".apk"), ("All files", ".*")])
        if fn:
            self.apkFile.delete(0, tk.END)
            self.apkFile.insert(0, fn)
            self.modeVar.set(self.MODE_APK)

    def getSelectedApk(self):
        return self.apkFile.get()

    def setAppList(self, apps):
        self.appList = apps
        self.appCombo["values"] = [""] + [app.name for app in apps]
        self.appCombo.current(0)

    def getSelectedApp(self):
        if self.appCombo.current() > 0:
            return self.appList[self.appCombo.current() - 1]


class FirmwareFrame(UiFrame):
    def __init__(self, parent, **kwargs):
        UiFrame.__init__(self, parent, **kwargs)

        datFrame = ttk.Labelframe(self, padding=5)
        datFrame["labelwidget"] = ttk.Label(datFrame, text="Firmware file")
        datFrame.pack(fill="x")

        self.datFile = tk.Entry(datFrame)
        self.datFile.pack(side=tk.LEFT, fill="x", expand=True)

        self.datSelectButton = ttk.Button(datFrame, text="Open...", command=self.openDat)
        self.datSelectButton.pack()

        self.fwUpdateButton = ttk.Button(self, text="Update firmware", command=FirmwareUpdateTask(self).run, padding=5)
        self.fwUpdateButton.pack(fill="x", pady=(5, 0))

    def openDat(self):
        fn = askopenfilename(filetypes=[("Firmware files", ".dat"), ("All files", ".*")])
        if fn:
            self.datFile.delete(0, tk.END)
            self.datFile.insert(0, fn)

    def getSelectedDat(self):
        return self.datFile.get()


class UpdaterShellFrame(UiFrame):
    def __init__(self, parent, **kwargs):
        UiFrame.__init__(self, parent, **kwargs)

        self.startUpdaterShellButton = ttk.Button(
            self, text="Start tweaking (updater mode)", command=StartUpdaterShellTask(self).run, padding=5
        )
        self.startUpdaterShellButton.pack(fill="x")

        self.startSenserShellButton = ttk.Button(
            self, text="Start tweaking (service mode)", command=StartSenserShellTask(self).run, padding=5
        )
        self.startSenserShellButton.pack(fill="x", pady=(5, 0))


class TweakDialog(UiDialog):
    def __init__(self, parent, tweakInterface, endFlag=None):
        self.tweakInterface = tweakInterface
        self.endFlag = endFlag
        UiDialog.__init__(self, parent, "Tweaks")

    def body(self, top):
        tweakFrame = ttk.Labelframe(top, padding=5)
        tweakFrame["labelwidget"] = ttk.Label(tweakFrame, text="Tweaks")
        tweakFrame.pack(fill="x")

        self.boxFrame = ttk.Frame(tweakFrame)
        self.boxFrame.pack(fill="both", expand=True)

        self.applyButton = ttk.Button(top, text="Apply", command=TweakApplyTask(self).run, padding=5)
        self.applyButton.pack(fill="x")

        self.updateStatus()

    def updateStatus(self):
        for child in self.boxFrame.winfo_children():
            child.destroy()
        for id, desc, status, value in self.tweakInterface.getTweaks():
            var = tk.IntVar(value=status)
            c = tk.Checkbutton(
                self.boxFrame,
                text=desc + "\n" + value,
                variable=var,
                command=lambda id=id, var=var: self.setTweak(id, var.get()),
            )
            c.pack(fill="x")

    def setTweak(self, id, enabled):
        self.tweakInterface.setEnabled(id, enabled)
        self.updateStatus()

    def setState(self, state):
        for widget in self.boxFrame.winfo_children() + [self.applyButton]:
            widget.config(state=state)

    def cancel(self, event=None):
        UiDialog.cancel(self, event)
        if self.endFlag:
            self.endFlag.set()


def main():
    """Gui main"""
    ui = MainUi("OpenMemories: pmca-gui" + (" " + version if version else ""))
    ui.mainloop()


if __name__ == "__main__":
    main()
