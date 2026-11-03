"""A TeamSpeak 3 ServerQuery in memory, answering exec_run calls fed stdin (FakeDockerGateway).

Its answers copy those of a real 3.13.8 server (format, escapes, error ids)."""

from typing import Any

from hivora.teamspeak.query import SCRIPT, escape, rows

GREETING = 'TS3\n\rWelcome to the TeamSpeak 3 ServerQuery interface, type "help" for a list.\n\r'


def _line(records: list[dict[str, Any]]) -> str:
    return "|".join(
        " ".join(f"{k}={escape(v)}" if v != "" else k for k, v in r.items()) for r in records
    )


class FakeTeamSpeak:
    def __init__(self, password: str | None = None) -> None:
        self.password = password  # None: any login accepted
        self.server: dict[str, Any] = {
            "virtualserver_name": "TeamSpeak ]I[ Server",
            "virtualserver_welcomemessage": "Welcome",
            "virtualserver_maxclients": 32,
            "virtualserver_clientsonline": 2,
            "virtualserver_queryclientsonline": 1,
            "virtualserver_version": "3.13.8 [Build: 1]",
            "virtualserver_uptime": 120,
            "virtualserver_flag_password": 0,
            "virtualserver_log_client": 0,
        }
        self.clients: list[dict[str, Any]] = [
            {
                "clid": 1,
                "client_nickname": "serveradmin",
                "client_type": 1,
                "connection_client_ip": "127.0.0.1",
                "client_idle_time": 0,
            },
            {
                "clid": 5,
                "client_nickname": "Alice Liddell",
                "client_type": 0,
                "connection_client_ip": "198.51.100.4",
                "client_country": "FR",
                "client_lastconnected": 1793709000,
                "client_idle_time": 4000,
            },
        ]
        self.bans: list[dict[str, Any]] = []
        self.keys: list[str] = ["firstkey"]
        self.messages: list[str] = []
        self.received: list[str] = []  # every command line, as sent
        self.log = [
            "2026-11-03 12:51:17.05|INFO    |VirtualServer |1  |client connected "
            "'Alice Liddell'(id:5) from 198.51.100.4:51234",
            "2026-11-03 12:50:00.00|INFO    |VirtualServer |1  |client disconnected "
            "'Bob'(id:4) reason 'reasonmsg=leaving'",
            "2026-11-03 12:49:00.00|INFO    |VirtualServer |1  |query client connected "
            "'serveradmin'(id:1) from 127.0.0.1:40321",
        ]

    def install(self, gateway: Any) -> None:
        gateway.exec_handler = self.handle

    def handle(self, cmd: list[str], stdin: bytes) -> tuple[int, str]:
        if cmd[:3] != ["sh", "-c", SCRIPT]:
            return 127, "not a ServerQuery session"
        out = [GREETING]
        for line in stdin.decode().splitlines()[: int(cmd[4])]:
            self.received.append(line)
            data, error = self._answer(line)
            if data:
                out.append(data + "\n\r")
            out.append(error + "\n\r")
        return 0, "".join(out)

    def _answer(self, line: str) -> tuple[str, str]:
        name, _, rest = line.partition(" ")
        args = {k: v for r in rows(rest) for k, v in r.items()} if rest else {}
        ok = "error id=0 msg=ok"
        match name:
            case "login":
                if self.password is not None and args.get("client_login_password") != self.password:
                    return "", "error id=520 msg=invalid\\sloginname\\sor\\spassword"
                return "", ok
            case "use" | "quit" | "gm":
                if name == "gm":
                    self.messages.append(args["msg"])
                return "", ok
            case "serverinfo":
                return _line([self.server]), ok
            case "serveredit":
                for k, v in args.items():
                    if k == "virtualserver_password":
                        self.server["virtualserver_flag_password"] = int(bool(v))
                    else:
                        self.server[k] = v
                return "", ok
            case "clientlist":
                return _line(self.clients), ok
            case "clientkick":
                self.clients = [c for c in self.clients if str(c["clid"]) != args["clid"]]
                return "", ok
            case "banlist":
                if not self.bans:
                    return "", "error id=1281 msg=database\\sempty\\sresult\\sset"
                return _line(self.bans), ok
            case "banadd" | "banclient":
                ip = args.get("ip") or next(
                    c["connection_client_ip"]
                    for c in self.clients
                    if str(c["clid"]) == args["clid"]
                )
                self.bans.append(
                    {
                        "banid": len(self.bans) + 1,
                        "ip": ip,
                        "lastnickname": "",
                        "created": 1793710277,
                        "duration": args.get("time", "0"),
                        "invokername": "serveradmin",
                        "reason": args.get("banreason", ""),
                    }
                )
                return f"banid={len(self.bans)}", ok
            case "bandel":
                self.bans = [b for b in self.bans if str(b["banid"]) != args["banid"]]
                return "", ok
            case "logview":
                return _line([{"l": entry} for entry in self.log]), ok
            case "servergrouplist":
                return _line(
                    [
                        {"sgid": 3, "name": "Server Admin", "type": 0},
                        {"sgid": 6, "name": "Server Admin", "type": 1},
                        {"sgid": 8, "name": "Guest", "type": 1},
                    ]
                ), ok
            case "privilegekeylist":
                if not self.keys:
                    return "", "error id=1281 msg=database\\sempty\\sresult\\sset"
                return _line(
                    [
                        {
                            "token": k,
                            "token_type": 0,
                            "token_id1": 6,
                            "token_created": 1793709499,
                            "token_description": "default key",
                        }
                        for k in self.keys
                    ]
                ), ok
            case "privilegekeydelete":
                self.keys.remove(args["token"])
                return "", ok
            case "privilegekeyadd":
                assert args["tokenid1"] == "6"
                key = f"newkey{len(self.received)}"
                self.keys.append(key)
                return f"token={key}", ok
        return "", "error id=256 msg=command\\snot\\sfound"
