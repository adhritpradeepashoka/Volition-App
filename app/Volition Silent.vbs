' Volition — Silent Launcher
' ============================
' Launches Volition with ZERO console window using pythonw.exe.
' Double-click this file, or better: create a shortcut to it and
' pin that shortcut to your taskbar/desktop (see instructions below).
'
' If Volition ever fails to start, no error will be visible since the
' console is hidden. If you need to debug, temporarily double-click
' "Launch Volition.bat" instead — that one shows the console with any
' error messages.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Resolve paths relative to this script's own location, so it works
' regardless of where the folder is moved
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
venvPythonw = scriptDir & "\..\.venv\Scripts\pythonw.exe"
mainScript  = scriptDir & "\volition_main.py"

' Verify the venv actually exists before trying to launch — if it
' doesn't, fall back to showing the visible .bat launcher instead so
' the person can see what went wrong
If Not fso.FileExists(venvPythonw) Then
    MsgBox "Could not find pythonw.exe at:" & vbCrLf & venvPythonw & vbCrLf & vbCrLf & _
           "Make sure this shortcut is inside the NPG-Lite-SNES folder" & vbCrLf & _
           "and .venv exists one level up in NPG-Lite-SNES-main." & vbCrLf & vbCrLf & _
           "Falling back to the visible launcher so you can see the error.", _
           vbExclamation, "Volition — Setup Issue"
    shell.Run """" & scriptDir & "\Launch Volition.bat""", 1, False
    WScript.Quit
End If

' Launch completely silently — window style 0 = hidden, False = don't wait
command = """" & venvPythonw & """ """ & mainScript & """"
shell.CurrentDirectory = scriptDir
shell.Run command, 0, False
