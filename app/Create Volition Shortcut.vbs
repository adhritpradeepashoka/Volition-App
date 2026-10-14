' Create Volition Shortcut.vbs
' ==============================
' Run this ONCE (double-click it). It creates a "Volition.lnk" shortcut
' on your Desktop that:
'   - Launches Volition with pythonw.exe (NO console window ever appears)
'   - Uses the custom Volition icon
'   - Sets the correct working directory automatically
'
' After running this once, you can:
'   - Double-click the new "Volition" desktop icon to launch normally
'   - Right-click it → "Pin to taskbar" for a permanent one-click launch
'   - Right-click it → "Pin to Start" if you prefer the Start menu
'
' You only need to run this script ONCE. After the shortcut exists,
' just use it — you don't need this script again unless you move the
' Volition folder to a new location, in which case run it again to
' recreate the shortcut with the correct paths.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir   = fso.GetParentFolderName(WScript.ScriptFullName)
venvPythonw = scriptDir & "\..\.venv\Scripts\pythonw.exe"
mainScript  = scriptDir & "\volition_main.py"
iconPath    = scriptDir & "\volition_icon.ico"
desktopDir  = shell.SpecialFolders("Desktop")
shortcutPath = desktopDir & "\Volition.lnk"

' Verify prerequisites exist before creating the shortcut
If Not fso.FileExists(venvPythonw) Then
    MsgBox "Could not find pythonw.exe at:" & vbCrLf & venvPythonw & vbCrLf & vbCrLf & _
           "Make sure this script is inside the NPG-Lite-SNES folder" & vbCrLf & _
           "and .venv exists one level up in NPG-Lite-SNES-main.", _
           vbCritical, "Volition — Cannot Create Shortcut"
    WScript.Quit
End If

If Not fso.FileExists(mainScript) Then
    MsgBox "Could not find volition_main.py in this folder.", _
           vbCritical, "Volition — Cannot Create Shortcut"
    WScript.Quit
End If

' Create the shortcut
Set link = shell.CreateShortcut(shortcutPath)
link.TargetPath = venvPythonw
link.Arguments  = """" & mainScript & """"
link.WorkingDirectory = scriptDir
link.WindowStyle = 1
link.Description = "Volition — Adaptive Biosignal Control System"

If fso.FileExists(iconPath) Then
    link.IconLocation = iconPath & ",0"
End If

link.Save

MsgBox "Done! A 'Volition' shortcut has been created on your Desktop." & vbCrLf & vbCrLf & _
       "Next steps:" & vbCrLf & _
       "  - Double-click it any time to launch Volition (no console window)" & vbCrLf & _
       "  - Right-click it -> Pin to taskbar for one-click access" & vbCrLf & _
       "  - Right-click it -> Pin to Start for the Start menu", _
       vbInformation, "Volition — Shortcut Created"
