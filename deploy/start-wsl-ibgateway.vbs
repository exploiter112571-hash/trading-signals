Set WshShell = CreateObject("WScript.Shell")
' Boot WSL at Windows login and keep it running: systemd (linger=yes) then
' starts cron, IB Gateway, osiris and the pollers. 'sleep infinity' holds a
' wsl.exe session open so WSL does not idle-shut-down when no terminal is open.
' Runs as the distro's default user; add -u <name> if that isn't the pipeline user.
WshShell.Run "wsl.exe -d Ubuntu --exec sleep infinity", 0, False
