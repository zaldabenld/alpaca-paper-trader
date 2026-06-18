Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
pythonExe = fso.BuildPath(root, ".venv\Scripts\python.exe")
dashboardScript = fso.BuildPath(root, "scripts\strategy_simulation_dashboard.py")
cmdLauncher = fso.BuildPath(root, "Launch Strategy Simulator Dashboard.cmd")
dashboardUrl = "http://127.0.0.1:8787/"
expectedVersion = "2026.06.18-controls-v2"
edgeProfile = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\AlpacaPaperTrader\StrategySimulatorEdgeProfile"

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Function DashboardState(url)
    DashboardState = ""
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 500, 500, 500, 500
    http.open "GET", url & "api/state", False
    http.send
    If Err.Number = 0 And http.status >= 200 And http.status < 500 Then
        DashboardState = http.responseText
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function IsAlive(url)
    IsAlive = Len(DashboardState(url)) > 0
End Function

Sub StopStaleDashboard()
    ps = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*strategy_simulation_dashboard.py*' -and $_.CommandLine -like '*--port 8787*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command " & Quote(ps), 0, True
End Sub

Function EdgePath()
    candidates = Array( _
        shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe", _
        shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\Edge\Application\msedge.exe" _
    )
    EdgePath = ""
    For Each candidate In candidates
        If fso.FileExists(candidate) Then
            EdgePath = candidate
            Exit Function
        End If
    Next
End Function

Sub OpenDashboard(url)
    edge = EdgePath()
    If Len(edge) > 0 Then
        If Not fso.FolderExists(edgeProfile) Then
            fso.CreateFolder edgeProfile
        End If
        shell.Run Quote(edge) & " --user-data-dir=" & Quote(edgeProfile) & " --no-first-run --new-window --app=" & Quote(url) & " --window-size=1280,900 --window-position=120,80", 1, False
    Else
        shell.Run Quote(url), 1, False
    End If
End Sub

stateText = DashboardState(dashboardUrl)
If Len(stateText) > 0 Then
    If InStr(1, stateText, expectedVersion, vbTextCompare) > 0 Or InStr(1, stateText, """status"": ""running""", vbTextCompare) > 0 Then
        OpenDashboard dashboardUrl
        WScript.Quit
    End If
    StopStaleDashboard
    WScript.Sleep 800
End If

If fso.FileExists(pythonw) Then
    shell.CurrentDirectory = root
    shell.Run Quote(pythonw) & " " & Quote(dashboardScript) & " --port 8787", 0, False
ElseIf fso.FileExists(pythonExe) Then
    shell.CurrentDirectory = root
    shell.Run Quote(pythonExe) & " " & Quote(dashboardScript) & " --port 8787", 0, False
Else
    shell.Run Quote(cmdLauncher), 1, False
    WScript.Quit
End If

For i = 1 To 40
    WScript.Sleep 500
    If IsAlive(dashboardUrl) Then
        OpenDashboard dashboardUrl
        WScript.Quit
    End If
Next

shell.Popup "Strategy simulator dashboard did not start. Try Launch Strategy Simulator Dashboard.cmd to see the error.", 10, "Alpaca Strategy Simulator", 48
