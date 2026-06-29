Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""V:\projects\mcp-handcraft\scripts\start-handcraft-http-at-login.ps1""", 0, False
