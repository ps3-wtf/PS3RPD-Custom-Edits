import json
from pathlib import Path
from socket import socket, AF_INET, SOCK_DGRAM  # used to get host IP address
import re  # used for regular expressions
import networkscan  # used for automatic obtaining IP address, requires pip install
import os  # used to test if config exists
import requests  # used to test if given IP belongs to PS3, requires pip install
from requests.exceptions import (
    ConnectionError,
)  # used to handle thrown errors on connecting to webpage
from bs4 import BeautifulSoup  # used for webpage scraping, requires pip install
from time import (
    sleep,
)  # used to add delay to mitigate rate limiting and webmanMOD memory consumption
import subprocess  # used to send ICMP  ping packets to PS3
import platform  # used to get operating system of PC
import sqlite3  # used for getting image from database
from pypresence import (
    Presence,
    InvalidPipe,
    InvalidID,
    DiscordNotFound,
)  # used for sending details to Discord, requires pip install
from time import time


default_config = {
    "ip": "",
    "client_id": 780389261870235650,
    "wait_seconds": 35,
    "show_temp": True,
    "retro_covers": False,
    "show_elapsed": True,
    "hibernate_seconds": 600,
    "ip_prompt": True,
    "show_timer": True,
}


class PrepWork:  # Python2 class should be "class PrepWork(object):" ?
    config_path = Path("config.txt")

    def __init__(self):
        self.RPC = None
        self.config = {}

    def read_config(self):
        if self.config_path.is_file():
            with self.config_path.open(mode="r") as f:
                self.config = json.load(f)
            self.config["wait_seconds"] = max(15, self.config["wait_seconds"])
            if not self.test_for_webman(self.config["ip"]) and self.config["ip_prompt"]:
                print("PS3 cannot be reached via the IP saved in the config file.")
                self.prompt_user()
        else:
            self.config = default_config
            self.prompt_user()

    def prompt_user(self):
        choice = "placeholder"
        accepted = ["a", "m"]
        print("\nGet PS3's IP address automatically, or manually?")
        while (
            choice[0].lower() not in accepted
        ):  # test if first character of choice is in array
            choice = input('Please enter either "A", or "M": ')
        if choice[0].lower() == "a":
            self.grab_host_network()
        elif choice[0].lower() == "m":
            self.get_IP_from_user()
        else:
            exit("Unexpected input")

    def grab_host_network(
        self,
    ):  # hard to account for what users firewall and network will look like. Function may not work for all users.
        hostNetwork = None
        try:
            tempSock = socket(AF_INET, SOCK_DGRAM)
            tempSock.connect(("8.8.8.8", 80))
            hostNetwork = tempSock.getsockname()[0]
            tempSock.close()
        except Exception as e:
            print(f'Error while getting host network. "{e}"')

        if hostNetwork is not None:
            hostNetwork = re.search("^(.*)\.", hostNetwork).group(
                0
            )  # remove machine's octet
            print(f'expected network is "{hostNetwork}"')
            self.scan_network(hostNetwork)

    def scan_network(self, my_network):  # takes IPv4 address in form 'x.x.x.'
        found = False
        # adapted from nychron's code
        my_network += "0/24"  # append 4th octet and short-form subnet mask

        # Run the scan of hosts using pings
        while True:
            my_scan = networkscan.Networkscan(my_network)
            my_scan.run()

            # Display the IP address of all the hosts found
            print("Completed network scan.")
            print(my_scan.list_of_hosts_found)

            for i in range(len(my_scan.list_of_hosts_found)):
                if self.test_for_webman(my_scan.list_of_hosts_found[i]):
                    self.save_config(my_scan.list_of_hosts_found[i])
                    found = True
                    break  # do not test further IPs if one is found to belong to webman
            if found is True:  # need second IF statement to break out of while loop
                break
            else:
                print("PS3 not found on network, waiting 20 seconds before retry")
                sleep(20)

    def get_IP_from_user(self):
        while True:
            ip = input("Enter PS3's IP address: ")
            if self.test_for_webman(ip):
                self.save_config(ip)
                break

    def test_for_webman(self, ip):
        response = None
        url = f"http://{ip}"
        try:  # test if ANY webpage is running on given IP
            response = requests.get(url, headers=headers)
        except ConnectionError:
            print(f'No webpage found on "{ip}"')
            return False
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            pageTitle = str(
                soup.find("title")
            )  # default type is bs4.element.tag, needs to be string
            if (
                "wMAN" in pageTitle or "webMAN" in pageTitle
            ):  # test for known value in <title>
                print(f'given IP "{ip}" belongs to webman.')
                return True
            else:  # a webpage was found, but does not satisfy check to belong to webman
                print(
                    f'WebmanMOD not found on "{ip}", reports "{pageTitle}". If you believe this is an error, please contact the developer. '
                    f"Please ensure the PS3 is turned on, has webmanMOD installed and running, "
                    f"and is connected to the same network as the PC."
                )
                return False

    def save_config(self, valid_ip):
        self.config["ip"] = valid_ip
        with self.config_path.open(mode="w+") as f:
            json.dump(self.config, f, indent=4)

    def connect_to_discord(self):
        while True:
            try:
                self.RPC = Presence(self.config["client_id"])
                self.RPC.connect()
                print("connected to Discord client")
                break
            except DiscordNotFound as e:
                print(f'could not find Discord client running. "{e}"')
                sleep(20)


class GatherDetails:
    def __init__(self):
        self.soup = None
        self.thermalData = None
        self.name = None
        self.titleID = None
        self.image = None
        self.isRetroGame = False

    def ping_PS3(
        self,
    ):  # Will work if webman is unloaded for some reason, will hopefully greatly reduce risk of
        # PS3 crashing when webman is contacted while also loading or quitting out of a game. (! Needs further testing !)
        if platform.system().lower() == "windows":
            command = ["ping", "-n", "5", prepWork.config["ip"]]
        else:
            command = ["ping", "-c", "5", prepWork.config["ip"]]
        with open(
            os.devnull, "w"
        ) as DEVNULL:  # used so output of ping doesn't spam console
            try:
                subprocess.check_call(
                    command, stdout=DEVNULL
                )  # ! needs to be tested on Linux !
                return True
            except subprocess.CalledProcessError:
                return False

    def get_html(self):
        url = f"http://{prepWork.config['ip']}/cpursx.ps3?/sman.ps3"
        if not self.ping_PS3():
            return False

        try:
            response = requests.get(url, headers=headers)
            self.soup = BeautifulSoup(response.text, "html.parser")
            return True
        except ConnectionError as e:
            print(f'get_html():  webman not found. "{e}".')
            return False

    def get_thermals(self):
        thermalData = str(self.soup.find("a", href="/cpursx.ps3?up"))
        # you can change to Fahrenheit by changing "C" to "F".
        cpu = re.search("CPU(.+?)C", thermalData)
        rsx = re.search("RSX(.+?)C", thermalData)
        try:
            cpu = cpu.group(0)
            rsx = rsx.group(0)
            self.thermalData = f"{cpu} | {rsx}"
            print(f"get_thermals():     {self.thermalData}")
        except AttributeError:
            print(
                f"get_thermals(): could not find html for thermal data, has webmanMOD been updated since {wmanVer}?"
            )

    def decide_game_type(self):
        # PS3 games will only be detected when they are OPEN, however PS2 and PS1 games will be detected when they are MOUNTED
        self.isRetroGame = False  # reset boolean each test
        if (
            self.soup.find("a", target="_blank") is not None
        ):  # PS3ISO, JB Folder Format, and PS3 PKG games will display this field in wman
            print("decide_game_type():  PS3 Game or Homebrew")
            self.get_PS3_details()
        elif (
            self.soup.find(
                "a", href=re.compile("/(dev_hdd0|dev_usb00[0-9])/(PSXISO|PS2ISO)")
            )
            is not None
        ):  # search for PSX or PS2 mounted game
            self.isRetroGame = True
            print("decide_game_type():  Retro")
            self.get_retro_details()
        else:
            print("decide_game_type():  XMB")
            self.name = "XMB"
            self.image = "xmb"
            self.titleID = None  # even though not used needs to be reset so prev titleID is not shown when on XMB

    def get_PS3_details(self):
        titleID = self.soup.find(
            "a", target="_blank"
        )  # get titleID of open game/homebrew
        name = self.soup.find(
            "a", target="_blank"
        ).find_next_sibling()  # get name of open game/homebrew
        name = str(name).replace(
            "\n", ""
        )  # need to remove newline characters as they break regex
        try:
            titleID = re.search(">(.*)<", str(titleID)).group(
                1
            )  # remove surrounding HTML
            name = re.search(">(.*)<", str(name)).group(1)
            if (
                re.search("(.+)[0-9]{2}.[0-9]{2}", name) is not None
            ):  # remove game version info if present
                name = re.search("(.+)[0-9]{2}.[0-9]{2}", name).group(1)
        except AttributeError:
            print(
                f"get_PS3_details(): could not find html for game data, has webmanMOD been updated since {wmanVer}?"
            )
        self.name = name
        self.titleID = titleID
        print(f"get_PS3_details():  {titleID} | {name}")
        if prevTitle != titleID:  # only get new image if a new game is found
            self.get_PS3_image()

    def get_retro_details(
        self,
    ):  # only tested with PSX and PS2 games, PSP and retroarch game compatibility unknown
        name = "Retro"  # if a PSX or PS2 game is not detected, or extern variable is False, this default will be used
        if prepWork.config["retro_covers"]:
            # name detected is based on name of file
            if (
                self.soup.find(
                    "a", href=re.compile("/(dev_hdd0|dev_usb00[0-9])/PSXISO")
                )
                is not None
            ):  # only PSX
                name = self.soup.find(
                    "a", href=re.compile("/(dev_hdd0|dev_usb00[0-9])/PSXISO")
                ).find_next_sibling()
            elif (
                self.soup.find(
                    "a", href=re.compile("/(dev_hdd0|dev_usb00[0-9])/PS2ISO")
                )
                is not None
            ):  # only PS2
                name = self.soup.find(
                    "a", href=re.compile("/(dev_hdd0|dev_usb00[0-9])/PS2ISO")
                ).find_next_sibling()
                # ! can set a boolean here if need to know a PS2 game is mounted !
            try:
                name = re.search('">(.*)</a>', str(name)).group(1)
            except AttributeError as e:
                print(f'! get_retro_details(): error with regex "{e}" !')
        self.name = name
        print(f"get_retro_details(): {name}")
        self.get_retro_image()

    def get_PS3_image(
        self,
    ):  # can use psimg.db if present, otherwise try aldo's title db before falling back on Discord dev app
        self.image = self.titleID.lower()  # by default set titleID as image name for Discord developer application (must be lowercase)
        if os.path.isfile(
            "psimg.db"
        ):  # test if database is in same directory as script
            self.image = self.use_local_db()
        else:  # attempt to get image from Aldo's Title DB
            self.image = self.use_aldotitledb()
        print(f"get_PS3_image():    {self.image}")

    def use_local_db(
        self,
    ):  # Google might of broken this, doesn't seem to work on my end anymore
        con = sqlite3.connect("psimg.db")  # connect to DB
        cur = con.cursor()
        result = cur.execute(
            f"SELECT * FROM PS3 WHERE titleID == '{self.titleID.upper()}'"
        )  # must be uppercase for db
        result = result.fetchall()
        if len(result) == 0:  # no value found
            print(
                f'titleID "{self.titleID}" not found in database, using Discord developer application'
            )
            con.close()
            return self.titleID.lower()  # bandaid fix
        else:
            imgName = result[0][2]  # [][0] = titleID, [][1] = name, [][2] = imageURL
            imgName = re.sub(
                "[ \n]", "", imgName
            )  # removes newline (\n) and space ( ) that is present in database for some reason
            con.close()
            print("using psimg.db")
            return imgName

    def use_aldotitledb(self):  # Original idea from AndreCox
        region_map = {  # this needs further testing
            "A": "ZH",  # ?
            "E": "EN",
            "H": "US",  # ?
            "J": "JA",
            "K": "KO",
            "U": "US",
        }
        val = region_map.get(
            self.titleID[2]
        )  # feed region_map 3rd char of titleID. use get() to handle unexpected keys
        if not val:
            print(
                f"! use_aldotitledb(): Unexpected key: {self.titleID[2]} ! \nFalling back to Discord dev app images"
            )
            return self.titleID.lower()  # bandaid fix, use Discord dev app
        else:
            url = f"https://raw.githubusercontent.com/aldostools/resources/master/COV/{self.titleID}.jpg"  # build URL
            status = requests.get(url)
            if status.status_code == 200:  # test if page exists
                print("using Aldo's Title DB")
                return url
            else:
                print(
                    f"use_aldotitledb(): no image found at {url}, using Discord dev app image"
                )
                return self.titleID.lower()  # bandaid fix, use Discord dev app

    def get_retro_image(self):  # uses 'name' for image names
        # apply Discord developer application naming conventions
        imgName = self.name.lower()  # must be lowercase
        imgName = imgName.replace(" ", "_")  # replace spaces with underscores
        imgName = imgName.replace(
            "&amp;", ""
        )  # regex below would only remove "&" without this
        imgName = re.sub(
            "[\W]+", "", imgName
        )  # replace any non-letter, digit, or underscore
        imgName = imgName[:32]  # maximum length of 32 characters
        self.image = imgName
        print(f"get_retro_image():  {imgName}")


headers = {
    "User-Agent": "Mozilla/5.0"
}  # Alternatively {'Content-Type': 'text/html'}. Used by both classes
wmanVer = "1.47.45"  # static string so I can indicate what ver the script was last tested with

prepWork = PrepWork()
prepWork.read_config()  # runs through majority of functions in PrepWork class
prepWork.connect_to_discord()  # running NetworkScan before PyPresence breaks asyncIO, I am not motivated enough to find proper fix.
closed = False  # boolean for RPC pipe
gatherDetails = GatherDetails()
timer = None  # default value for if config set to false
if prepWork.config["show_timer"]:
    timer = time()  # start timer
prevTitle = ""  # set default value to be compared in get_PS3_details()

if (
    prepWork.config["ip"] is None
):  # very basic error notification for if PrepWork breaks
    exit("script failed to execute critical functions.")

while True:
    if not gatherDetails.get_html():  # triggered if webman goes down
        if (
            gatherDetails.isRetroGame is True
        ):  # should only occur if PS2 game is mounted
            print(
                f"PS2 game previously mounted, keeping RPC active and waiting {prepWork.config['wait_seconds']} seconds"
            )
            sleep(prepWork.config["wait_seconds"])
        else:
            print(
                f"PS3 not found on network, closing RPC and hibernating {prepWork.config['hibernate_seconds']} seconds."
            )
            if not closed:
                prepWork.RPC.clear()
            prepWork.RPC.close()  # destroy pipe
            closed = True
            sleep(float(prepWork.config["hibernate_seconds"]))
    else:  # continue with normal program loop
        print("")
        if closed:  # decide if RPC needs to be reconnected
            prepWork.connect_to_discord()
            timer = time()
            closed = False
        if prepWork.config["show_temp"]:  # first character of variable in lowercase
            gatherDetails.get_thermals()
            gatherDetails.thermalData = gatherDetails.thermalData.replace(
                "Â", ""
            )  # ! bandaid fix ! ANSI encoding is being used on some users??
        gatherDetails.decide_game_type()
        # print(f'{gatherDetails.name}, {gatherDetails.thermalData}, {gatherDetails.image}, {gatherDetails.titleID}')   # debugging
        gatherDetails.name = gatherDetails.name.replace(
            "Â", ""
        )  # ! bandaid fix ! ANSI encoding is being used on some users??

        try:
            prepWork.RPC.update(
                details=gatherDetails.name,
                state=gatherDetails.thermalData,
                large_image=gatherDetails.image,
                large_text=gatherDetails.titleID,
                start=timer,
            )
        except (InvalidPipe, InvalidID):
            prepWork.RPC.close()  # close Presence if Discord is not found     ! Does this actually do anything? !
            prepWork.connect_to_discord()  # start connection loop
        prevTitle = gatherDetails.titleID  # set new value for next loop
        sleep(prepWork.config["wait_seconds"])
