' Hidden launcher for the retirement tripwires scheduled task.
' Runs run.bat with no visible console window (window style 0).
Set shell = CreateObject("WScript.Shell")
shell.Run """" & Replace(WScript.ScriptFullName, "run-hidden.vbs", "run.bat") & """", 0, False
